"""EN/AR tokenizer for the hand-rolled search engine (research.md §2).

Reuses src.ingestion.text_normalize's per-script normalization rules so the
search tokenizer and the brand/category canonicalization pipeline can never
drift apart (both trace back to research.md's one set of Arabic/Latin rules).
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.ingestion.text_normalize import is_arabic, normalize_arabic, normalize_latin  # noqa: E402

_WORD_RE = re.compile(r"\w+", re.UNICODE)

# This threshold gates only the DEFAULT (old single-candidate rule)
# side of the comparison below, not the alternative: the default is
# treated as displaceable when its own frequency is at or below this
# value, i.e. it looks like a coincidental one-off fragment rather than
# an established word (e.g. "glasse", 1 occurrence). It does NOT mean an
# alternative candidate must itself clear this bar to win -- the actual
# rule is relative (alt_freq > default_freq), so a real but corpus-rare
# alternative (freq=1, e.g. "radish" for "radishes", "smoothie" for
# "smoothies") still wins against a totally-unattested default (freq=0).
# Verified against the full vocabulary: raising this into an absolute
# minimum on the alternative too (e.g. requiring alt_freq > 1) would
# regress those two confirmed-correct cases while fixing nothing that the
# separate _SEMANTIC_FALSE_CONFLATION_BLOCKLIST below doesn't already
# handle more precisely -- a real but rare word and a coincidental
# fragment can share the exact same (0, 1) frequency signature, so no
# frequency threshold alone can tell them apart; only individually-
# audited semantic evidence can.
_UNATTESTED_FREQ = 1

# Confirmed via an exhaustive corpus-wide semantic audit of every -es/-ies
# token this disambiguation ever changes (research.md): these 5 source
# tokens' corpus-attested "alt" candidate is a real semantic false
# conflation, not the correct base form -- in each case the SHORT
# candidate's real occurrences are dominated by an unrelated brand/
# marketing name, not the generic word: "burnes" (a likely raw-data typo
# of "Burners" on a gas cooker) vs "burn" (a skincare product name,
# "Matcha Burn"); "kisses" (Hershey's Kisses candy) vs "kiss" (perfume/
# fragrance products); "ashes" (an ashtray) vs "ash" (the hair-dye shade
# "Ash Blonde"); "matches" (safety matches) vs "match" (the "Sugar Match"
# sweetener brand); "patches" (medical adhesive patches) vs "patch" (the
# "Sour Patch" candy brand). Raising _UNATTESTED_FREQ instead (requiring
# the alt candidate to also clear a minimum count) was tried and rejected:
# verified against the full vocabulary that it would regress two DIFFERENT,
# confirmed-correct cases with the identical (0, 1) frequency signature --
# "radishes"->"radish" and "smoothies"->"smoothie" -- since a real but
# corpus-rare word looks statistically identical to a coincidental
# fragment. A small, closed, individually-verified exclusion list (the
# same established pattern as keyword_baseline.py's brand/category fuzzy
# blocklists), not a growing dictionary: every entry here was found by
# auditing 100% of this rule's real effects, not guessed in advance.
_SEMANTIC_FALSE_CONFLATION_BLOCKLIST = {"burnes", "kisses", "ashes", "matches", "patches"}


def _raw_tokens(text: str | None) -> list[tuple[str, bool]]:
    """Word-split + per-script normalize, WITHOUT English suffix trimming.
    Returns (normalized_token, is_arabic) pairs. Exposed so index-building
    can collect a corpus-wide base-form vocabulary (see tokenize()'s
    base_freq parameter) using the exact same splitting/normalization
    rules the final tokenizer itself uses -- one source of truth, not two
    parallel implementations that could drift."""
    if not text:
        return []
    out: list[tuple[str, bool]] = []
    for raw in _WORD_RE.findall(text):
        arabic = is_arabic(raw)
        norm = normalize_arabic(raw) if arabic else normalize_latin(raw)
        if norm:
            out.append((norm, arabic))
    return out


def _trim_plural(token: str, base_freq: Counter | None = None) -> str:
    """Light suffix trim only (not a full stemmer, per research.md §2, to
    stay inspectable) -- skip short tokens where trimming would be too
    aggressive (e.g. 'gas' -> 'ga').

    Two English plural suffixes are GENUINELY AMBIGUOUS from spelling
    alone, not just imperfectly handled by a stricter regex (confirmed via
    a corpus-wide sweep of all 11,390 real English-like product-name
    tokens, research.md):
    - "-ies": "berries" -> "berry" (consonant+y pluralization) is spelled
      identically to "cookies" -> "cookie" (a word already ending in "ie",
      just +s). The letter before the suffix can't tell them apart --
      "cook" (from cookies) and "berr" (from berries) both end in a
      consonant.
    - "-es": "boxes"/"dishes" -> "box"/"dish" (real -es pluralization,
      singular loses BOTH letters) is spelled identically to "prices" ->
      "price" (singular already ends in "e", loses only the "s"). Nothing
      in the plural spelling says which happened.

    Without a real base-form vocabulary (base_freq=None), this falls back
    to the plain single-candidate suffix rule, same as before. WITH one
    (built once at index time over the whole corpus, see index.py), a
    genuinely ambiguous case is resolved by asking which candidate base
    form actually occurs elsewhere in this corpus: if the plain-rule
    default is itself unattested or a one-off (<= _UNATTESTED_FREQ) while
    the alternative reduction is a real, more-attested word, prefer the
    alternative. A default that's already well-attested is never
    overridden by a merely-more-frequent alternative (e.g. "bones" stays
    "bone" even though the coincidental fragment "bon" is more frequent in
    this corpus -- overriding an already-real word on frequency alone
    would trade one false-normalization class for another, confirmed via
    a full-vocabulary regression check finding zero cases where this rule
    should fire the other way)."""
    if len(token) <= 4:
        return token
    if token.endswith("ies"):
        default = token[:-3] + "y"   # berry-style: real -y pluralization
        alt = token[:-1]             # cookie-style: already ends "ie", +s
    elif token.endswith("es"):
        default = token[:-1]         # price-style: singular already ends "e"
        alt = token[:-2]             # box/dish-style: real -es pluralization
    elif token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    else:
        return token

    if base_freq is not None and token not in _SEMANTIC_FALSE_CONFLATION_BLOCKLIST:
        default_freq = base_freq.get(default, 0)
        alt_freq = base_freq.get(alt, 0)
        if default_freq <= _UNATTESTED_FREQ and alt_freq > default_freq:
            return alt
    return default


def tokenize(text: str | None, base_freq: Counter | None = None) -> list[str]:
    """Unicode-block classification per raw token BEFORE normalizing, so a
    mixed-script string (spec.md's explicit edge case, e.g. an Arabic
    sentence with an English brand name) never has one script's normalizer
    mangle the other's tokens.

    `base_freq` (a corpus-wide Counter of pre-stem token frequencies, see
    SearchIndex.base_freq) is optional so this function still works
    standalone (e.g. one-off calls, tests) -- callers that need the
    disambiguation above (indexing and query tokenization both must, to
    stay consistent with each other) pass the same index's base_freq."""
    tokens: list[str] = []
    for norm, arabic in _raw_tokens(text):
        final = norm if arabic else _trim_plural(norm, base_freq)
        if final:
            tokens.append(final)
    return tokens
