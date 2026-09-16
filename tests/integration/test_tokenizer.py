"""Sprint 1 tokenizer plural-suffix disambiguation (comprehensive audit,
2026-09): "-es" and "-ies" are genuinely ambiguous from spelling alone --
"boxes"/"box" (real -es pluralization, singular loses 2 chars) is spelled
identically to "prices"/"price" (singular already ends in "e", loses only
1); "cookies"/"cookie" (already ends "ie", +s) is spelled identically to
"berries"/"berry" (real -y pluralization). A stricter suffix regex cannot
tell these apart (confirmed via a corpus-wide sweep of all 11,390 real
English-like product-name tokens, research.md) -- tokenize() now takes an
optional `base_freq` (a corpus-wide Counter of pre-stem token frequencies,
built once by SearchIndex.build_from_db()) and prefers whichever candidate
base form is actually attested elsewhere in real product names, falling
back to the old single-candidate rule when neither/both exist or when
called without a base_freq at all (unchanged behavior, e.g. one-off calls
with no index available).

Tests prefer semantic invariants (normalize(singular) == normalize(plural))
over asserting the literal internal stem, per the project's own stated
principle here: stems don't need to be linguistically pretty, they need to
map real shopper wording consistently.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest  # noqa: E402

from src.search_engine.index import get_index  # noqa: E402
from src.search_engine.tokenizer import tokenize  # noqa: E402

index = get_index()


def _norm(word: str) -> str:
    return tokenize(word, index.base_freq)[0]


# --- The 8 originally-reported pairs: singular and plural must normalize
# to the SAME token, using the real corpus's base_freq. ---

@pytest.mark.parametrize("singular,plural", [
    ("cookie", "cookies"),
    ("brownie", "brownies"),
    ("berry", "berries"),
    ("box", "boxes"),
    ("dish", "dishes"),
    ("glass", "glasses"),
    ("tomato", "tomatoes"),
    ("orange", "oranges"),
])
def test_singular_and_plural_normalize_consistently(singular, plural):
    assert _norm(singular) == _norm(plural), (
        f"{singular!r} -> {_norm(singular)!r}, {plural!r} -> {_norm(plural)!r}"
    )


# --- Additional real corpus pairs discovered by the sweep (not hand-picked
# to fit the fix -- these are genuine other cases from the same "-es"/"-ies"
# ambiguity classes found in the real product-name corpus). ---

@pytest.mark.parametrize("singular,plural", [
    ("potato", "potatoes"),
    ("mango", "mangoes"),
    ("peach", "peaches"),
    ("calorie", "calories"),
    ("radish", "radishes"),
    ("spinach", "spinaches"),
    ("veggie", "veggies"),
    ("cloth", "clothes"),
])
def test_additional_corpus_discovered_pairs_normalize_consistently(singular, plural):
    assert _norm(singular) == _norm(plural), (
        f"{singular!r} -> {_norm(singular)!r}, {plural!r} -> {_norm(plural)!r}"
    )


# --- Words ending in "s" that are NOT ambiguous plurals (real brand names,
# or genuinely different words that happen to share a candidate reduction)
# must NOT be forced together with an unrelated word just because a
# same-suffix reduction happens to also be a real corpus token. ---

@pytest.mark.parametrize("word,must_not_equal", [
    ("bones", "bon"),      # "bon" (a real but unrelated corpus fragment) must not win
    ("mates", "mat"),      # "mat" is a real but unrelated word; tie stays with "mate"
    ("chocolates", "chocolat"),
    ("vegetables", "vegetabl"),
    ("toothpastes", "toothpast"),
])
def test_already_correct_forms_are_not_overridden_by_a_coincidental_fragment(word, must_not_equal):
    assert _norm(word) != must_not_equal


# --- Threshold boundary (independent audit, 2026-09): the disambiguation
# fires when default_freq <= _UNATTESTED_FREQ(1) and alt_freq > default_freq
# -- including the (0, 1) boundary, where the alt candidate is itself only
# a one-off. Verified against the full vocabulary that raising the bar
# (requiring alt_freq > 1 too) would regress these two confirmed-correct
# cases to fix nothing extra (the actual bad (0, 1) cases are handled by
# the semantic blocklist below instead, not by tightening this threshold). ---

@pytest.mark.parametrize("singular,plural", [
    ("radish", "radishes"),   # alt "radish" is corpus-rare (freq=1) but genuinely correct
    ("smoothie", "smoothies"),  # alt "smoothie" is also corpus-rare (freq=1) but correct
])
def test_unattested_freq_boundary_still_resolves_genuinely_correct_rare_words(singular, plural):
    assert _norm(singular) == _norm(plural)


# --- Semantic false-conflation blocklist (independent audit, 2026-09): an
# exhaustive audit of every real -es/-ies token this disambiguation changes
# found 5 cases (out of 35) where the corpus-attested "alt" candidate is a
# real semantic false conflation -- the short form's occurrences are
# dominated by an unrelated brand/marketing name, not the generic word.
# These must NOT be merged, unlike the structurally-identical-looking
# "radish"/"smoothie" cases above (same (0, 1) frequency signature, but
# verified correct via real product names). ---

@pytest.mark.parametrize("singular,plural,singular_context,plural_context", [
    ("burn", "burnes", "a skincare product (\"Matcha Burn\")",
     "a gas cooker's burners (likely a raw-data typo of \"Burners\")"),
    ("kiss", "kisses", "perfume/fragrance products",
     "Hershey's Kisses chocolate candy"),
    ("ash", "ashes", "the hair-dye shade \"Ash Blonde\"",
     "an ashtray"),
    ("match", "matches", "the \"Sugar Match\" sweetener brand",
     "safety matches"),
    ("patch", "patches", "the \"Sour Patch\" candy brand",
     "medical adhesive patches"),
])
def test_confirmed_semantic_false_conflations_stay_unmerged(singular, plural, singular_context, plural_context):
    assert _norm(singular) != _norm(plural), (
        f"{singular!r} ({singular_context}) must not merge with "
        f"{plural!r} ({plural_context})"
    )


def test_brand_like_words_ending_in_s_are_unaffected_by_the_disambiguation_fix():
    # These never match the -es/-ies ambiguity at all (plain "-s" suffix,
    # untouched by this fix) -- locking in that they still tokenize
    # exactly as before, since real product/brand names, not a plural to
    # unify with anything.
    for word in ("spinneys", "pampers", "adidas", "citrus", "hibiscus"):
        tokens = tokenize(word, index.base_freq)
        assert tokens == [word[:-1]]  # unchanged plain "-s" strip behavior


def test_tokenize_without_base_freq_falls_back_to_the_old_single_candidate_rule():
    """Callers with no index available (base_freq=None, the default) must
    still get a deterministic result -- not crash, not require an index."""
    assert tokenize("cookies") == ["cooky"]
    assert tokenize("boxes") == ["boxe"]
    assert tokenize("berries") == ["berry"]  # already consistent even without a vocabulary


# --- Arabic tokenization must be completely unaffected: no suffix
# trimming is ever applied to Arabic tokens, base_freq or not. ---

def test_arabic_tokens_are_never_suffix_trimmed():
    before = tokenize("جهينة")
    after = tokenize("جهينة", index.base_freq)
    assert before == after == ["جهينة"]


def test_mixed_arabic_english_query_still_splits_per_script():
    # spec.md's explicit edge case (research.md): one script's normalizer
    # must never mangle the other's tokens.
    tokens = tokenize("استرا شوكولاتة Munchi", index.base_freq)
    assert "munchi" in tokens
    assert "شوكولاتة" in tokens


# --- Real end-to-end retrieval: singular/plural must retrieve materially
# equivalent products through the actual hybrid search endpoint. ---

@pytest.mark.parametrize("singular,plural", [
    ("cookie", "cookies"),
    ("box", "boxes"),
    ("tomato", "tomatoes"),
    ("dish", "dishes"),
])
def test_genuinely_equivalent_forms_produce_identical_bm25_candidate_sets(singular, plural):
    """Strengthened from a subset check: when two forms normalize to the
    EXACT SAME single query token over the SAME candidate pool,
    candidates_for_tokens() looks up that one token's postings set both
    times -- the resulting doc-ID sets must be identical, not merely one a
    subset of the other. A subset-only assertion would silently pass even
    if the fix were only half-working (e.g. one direction resolved, the
    other still falling to a different stem)."""
    from src.search_engine.ranking import rank
    all_ids = set(index.doc_len.keys())
    singular_ids = {pid for pid, _score in rank(index, all_ids, singular)}
    plural_ids = {pid for pid, _score in rank(index, all_ids, plural)}
    assert singular_ids == plural_ids
    assert len(singular_ids) > 0


def test_semantically_distinct_pairs_do_not_get_identical_bm25_candidate_sets():
    """The exact-equality invariant above must NOT be blindly enforced for
    pairs that don't actually normalize to the same token -- "kiss"/"kisses"
    are a confirmed semantic false conflation (see the blocklist tests
    above) and must keep genuinely different candidate sets."""
    from src.search_engine.ranking import rank
    all_ids = set(index.doc_len.keys())
    kiss_ids = {pid for pid, _score in rank(index, all_ids, "kiss")}
    kisses_ids = {pid for pid, _score in rank(index, all_ids, "kisses")}
    assert kiss_ids != kisses_ids
