"""Sprint 6 typo-candidate benchmark -- ANALYSIS ONLY, no production code
touched, no LLM, no API calls. Evaluation artifact.

Question: should ranking.correct_unmatched_terms' single-nearest-token
choice (rapidfuzz.process.extractOne) be replaced by deterministic top-K
catalog candidate generation plus evidence-based selection?

METHOD A (current, reimplemented here EXACTLY as ranking.py does it, so
the comparison is apples-to-apples and production stays untouched):
  token with zero postings -> process.extractOne(token, postings.keys(),
  scorer=fuzz.ratio); accept iff score >= 80 and df(match) >= 3.

METHOD B (candidate mode, proposed): same vocabulary, same thresholds --
no threshold is lowered anywhere -- but process.extract(limit=K) instead
of extractOne, then a selection step that uses whole-query catalog
evidence rather than string distance alone:
  1. keep candidates with score >= 80 and df >= 3 (identical gates to A)
  2. build CONTEXT from the query's literally-matching tokens:
     context = intersection of their postings, falling back to the union
     when the intersection is empty
  3. if context exists: support(c) = |postings(c) & context|; pick argmax
     support (ties: df, then score). If every candidate has support 0,
     REJECT the correction -- the catalog has no product where the
     candidate and the rest of the query co-occur at all.
  4. if there is no context (single-token query): pick argmax df (ties:
     score) among the surviving candidates.

Rule 3 is the part that matters for false corrections of ordinary
conversational filler: a filler word sitting next to real product words
has no candidate that co-occurs with them, so B declines instead of
substituting. Nothing about any specific word is encoded.

Usage: python evaluation/sprint6_typo_candidate_benchmark.py
Writes: evaluation/sprint6_typo_candidate_dataset.json
        evaluation/sprint6_typo_candidate_results.json
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rapidfuzz import fuzz, process  # noqa: E402

from src.ingestion.text_normalize import is_arabic  # noqa: E402
from src.search_engine.index import get_index  # noqa: E402
from src.search_engine.ranking import (  # noqa: E402
    SPELLING_CORRECTION_MIN_TARGET_DOCS,
    SPELLING_CORRECTION_THRESHOLD,
)

SEED = 20260915
TOP_K = 5
PER_BUCKET = 10          # per (language x mutation type x arity) bucket
MIN_SOURCE_DF = 5
MIN_LEN_EN, MIN_LEN_AR = 5, 4

# Ordinary conversational filler -- NOT product vocabulary and NOT a
# blocklist: these are CONTROL INPUTS for measuring whether a method
# damages a clean query, never consulted by either method under test.
FILLER_EN = ["please", "maybe", "really", "quickly", "kindly", "actually",
             "possibly", "something", "anything", "tomorrow"]
FILLER_AR = ["لوسمحت", "بسرعة", "ممكن", "يعني", "بصراحة", "خالص",
             "النهاردة", "كمان", "شوية", "طبعا"]

EN_ALPHABET = "abcdefghijklmnopqrstuvwxyz"
AR_ALPHABET = list("ابتثجحخدذرزسشصضطظعغفقكلمنهوي")


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


# --- deterministic single-edit mutations ------------------------------

def _alphabet(word: str) -> list[str]:
    return AR_ALPHABET if is_arabic(word) else list(EN_ALPHABET)


def mutate(word: str, kind: str, rng: random.Random) -> str | None:
    if kind == "deletion":
        i = rng.randrange(len(word))
        return word[:i] + word[i + 1:]
    if kind == "insertion":
        i = rng.randrange(len(word) + 1)
        return word[:i] + rng.choice(_alphabet(word)) + word[i:]
    if kind == "substitution":
        i = rng.randrange(len(word))
        alt = [c for c in _alphabet(word) if c != word[i]]
        return word[:i] + rng.choice(alt) + word[i + 1:]
    if kind == "transposition":
        if len(word) < 2:
            return None
        i = rng.randrange(len(word) - 1)
        if word[i] == word[i + 1]:
            return None
        return word[:i] + word[i + 1] + word[i] + word[i + 2:]
    raise ValueError(kind)


def make_typo(word: str, kind: str, rng: random.Random, vocab: set[str]) -> str | None:
    """A mutation that lands on another REAL vocabulary word is not a typo
    for our purposes (it is a different real query), so reject and retry."""
    for _ in range(30):
        m = mutate(word, kind, rng)
        if m and m != word and m not in vocab and len(m) >= 3:
            return m
    return None


# --- the two methods under test ---------------------------------------

def method_a(index, tokens: list[str], typo_index: int) -> dict:
    """Current production logic, per-token, reimplemented verbatim."""
    token = tokens[typo_index]
    match = process.extractOne(token, list(index.postings.keys()), scorer=fuzz.ratio)
    top1 = match[0] if match else None
    accepted = None
    if (match is not None
            and match[1] >= SPELLING_CORRECTION_THRESHOLD
            and len(index.postings[match[0]]) >= SPELLING_CORRECTION_MIN_TARGET_DOCS):
        accepted = match[0]
    return {"generated": [top1] if top1 else [], "selected": accepted}


def method_b(index, tokens: list[str], typo_index: int, k: int = TOP_K) -> dict:
    token = tokens[typo_index]
    raw = process.extract(token, list(index.postings.keys()), scorer=fuzz.ratio, limit=k)
    generated = [c for c, _s, _i in raw]
    survivors = [
        (c, s) for c, s, _i in raw
        if s >= SPELLING_CORRECTION_THRESHOLD
        and len(index.postings[c]) >= SPELLING_CORRECTION_MIN_TARGET_DOCS
    ]
    if not survivors:
        return {"generated": generated, "selected": None}

    matching = [t for i, t in enumerate(tokens) if i != typo_index and t in index.postings]
    context: set[int] = set()
    if matching:
        context = set(index.postings[matching[0]])
        for t in matching[1:]:
            context &= set(index.postings[t])
        if not context:
            for t in matching:
                context |= set(index.postings[t])

    if context:
        scored = [
            (len(set(index.postings[c]) & context), len(index.postings[c]), s, c)
            for c, s in survivors
        ]
        best = max(scored)
        if best[0] == 0:
            return {"generated": generated, "selected": None}
        return {"generated": generated, "selected": best[3]}

    scored = [(len(index.postings[c]), s, c) for c, s in survivors]
    return {"generated": generated, "selected": max(scored)[2]}


# --- dataset ----------------------------------------------------------

def build_dataset(index, rng: random.Random) -> list[dict]:
    vocab = set(index.postings.keys())
    en_words, ar_words = [], []
    for token, pids in index.postings.items():
        if len(pids) < MIN_SOURCE_DF or not token.isalpha():
            continue
        if is_arabic(token):
            if len(token) >= MIN_LEN_AR:
                ar_words.append(token)
        elif len(token) >= MIN_LEN_EN:
            en_words.append(token)
    en_words.sort()
    ar_words.sort()
    log(f"source pools: en={len(en_words)} ar={len(ar_words)}")

    def context_word_for(word: str) -> str | None:
        """A real catalog word that genuinely co-occurs with `word` in some
        product -- so a multi-word case is realistic, not synthetic."""
        for pid in sorted(index.postings[word])[:40]:
            others = [t for t in index.doc_term_freq.get(pid, {})
                      if t != word and t in vocab and len(index.postings[t]) >= MIN_SOURCE_DF
                      and t.isalpha() and is_arabic(t) == is_arabic(word)]
            if others:
                return sorted(others)[0]
        return None

    cases: list[dict] = []
    cid = 0
    for lang, pool in (("en", en_words), ("ar", ar_words)):
        for kind in ("deletion", "insertion", "substitution", "transposition"):
            for arity in ("single", "multiword"):
                picked = 0
                attempts = 0
                while picked < PER_BUCKET and attempts < PER_BUCKET * 40:
                    attempts += 1
                    source = rng.choice(pool)
                    typo = make_typo(source, kind, rng, vocab)
                    if typo is None:
                        continue
                    if arity == "single":
                        query_tokens = [typo]
                    else:
                        ctx = context_word_for(source)
                        if ctx is None:
                            continue
                        query_tokens = [ctx, typo]
                    cid += 1
                    picked += 1
                    cases.append({
                        "id": cid, "kind": "typo", "language": lang,
                        "mutation": kind, "arity": arity,
                        "tokens": query_tokens, "typo_index": query_tokens.index(typo),
                        "truth": source,
                    })
    # --- controls: clean catalog words (must not be changed) ----------
    for lang, pool in (("en", en_words), ("ar", ar_words)):
        for _ in range(10):
            w = rng.choice(pool)
            ctx = context_word_for(w)
            cid += 1
            cases.append({
                "id": cid, "kind": "clean_catalog", "language": lang,
                "mutation": None, "arity": "multiword" if ctx else "single",
                "tokens": [ctx, w] if ctx else [w],
                "typo_index": (1 if ctx else 0), "truth": w,
            })
    # --- controls: conversational filler beside a real product word ----
    for lang, fillers, pool in (("en", FILLER_EN, en_words), ("ar", FILLER_AR, ar_words)):
        for f in fillers:
            if f in vocab:
                continue
            w = rng.choice(pool)
            cid += 1
            cases.append({
                "id": cid, "kind": "clean_filler", "language": lang,
                "mutation": None, "arity": "multiword",
                "tokens": [w, f], "typo_index": 1, "truth": None,
            })
    return cases


# --- scoring ----------------------------------------------------------

def blank() -> dict:
    return {"n": 0, "available": 0, "correct": 0, "wrong": 0, "unresolved": 0,
            "not_generated": 0, "generated_wrong_selection": 0}


def tally(bucket: dict, truth: str | None, out: dict) -> None:
    bucket["n"] += 1
    sel, gen = out["selected"], out["generated"]
    if truth is None:                       # control: any change is damage
        if sel is not None:
            bucket["wrong"] += 1
        else:
            bucket["correct"] += 1
        return
    if truth in gen:
        bucket["available"] += 1
    if sel == truth:
        bucket["correct"] += 1
    elif sel is None:
        bucket["unresolved"] += 1
        if truth in gen:
            bucket["generated_wrong_selection"] += 1
        else:
            bucket["not_generated"] += 1
    else:
        bucket["wrong"] += 1
        if truth in gen:
            bucket["generated_wrong_selection"] += 1
        else:
            bucket["not_generated"] += 1


def rates(b: dict) -> dict:
    n = b["n"] or 1
    return {"n": b["n"],
            "available_rate": round(b["available"] / n, 4),
            "correct_rate": round(b["correct"] / n, 4),
            "wrong_rate": round(b["wrong"] / n, 4),
            "unresolved_rate": round(b["unresolved"] / n, 4),
            "fail_not_generated": b["not_generated"],
            "fail_generated_wrong_selection": b["generated_wrong_selection"]}


def main() -> None:
    index = get_index()
    rng = random.Random(SEED)
    cases = build_dataset(index, rng)
    log(f"{len(cases)} cases "
        f"(typo={sum(1 for c in cases if c['kind'] == 'typo')}, "
        f"clean_catalog={sum(1 for c in cases if c['kind'] == 'clean_catalog')}, "
        f"clean_filler={sum(1 for c in cases if c['kind'] == 'clean_filler')})")

    (ROOT / "evaluation" / "sprint6_typo_candidate_dataset.json").write_text(
        json.dumps({"seed": SEED, "top_k": TOP_K, "cases": cases}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    results = {"A_extractOne": {}, "B_topk": {}}
    per_case = []
    for label, fn in (("A_extractOne", method_a), ("B_topk", method_b)):
        overall = blank()
        by_lang = {"en": blank(), "ar": blank()}
        by_mut = {k: blank() for k in ("deletion", "insertion", "substitution", "transposition")}
        by_arity = {"single": blank(), "multiword": blank()}
        controls = {"clean_catalog": blank(), "clean_filler": blank()}
        for c in cases:
            out = fn(index, c["tokens"], c["typo_index"])
            if label == "A_extractOne":
                per_case.append({"id": c["id"], "kind": c["kind"], "tokens": c["tokens"],
                                 "truth": c["truth"], "a_selected": out["selected"]})
            else:
                per_case[c["id"] - 1]["b_generated"] = out["generated"]
                per_case[c["id"] - 1]["b_selected"] = out["selected"]
            if c["kind"] == "typo":
                tally(overall, c["truth"], out)
                tally(by_lang[c["language"]], c["truth"], out)
                tally(by_mut[c["mutation"]], c["truth"], out)
                tally(by_arity[c["arity"]], c["truth"], out)
            else:
                tally(controls[c["kind"]], c["truth"], out)
        results[label] = {
            "overall_typo": rates(overall),
            "by_language": {k: rates(v) for k, v in by_lang.items()},
            "by_mutation": {k: rates(v) for k, v in by_mut.items()},
            "by_arity": {k: rates(v) for k, v in by_arity.items()},
            "controls": {k: {"n": v["n"], "damage_rate": round(v["wrong"] / (v["n"] or 1), 4),
                              "damaged": v["wrong"]} for k, v in controls.items()},
        }

    (ROOT / "evaluation" / "sprint6_typo_candidate_results.json").write_text(
        json.dumps({"seed": SEED, "top_k": TOP_K, "summary": results, "cases": per_case},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    log(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
