"""Sprint 6 spell-correction CANDIDATE GENERATION benchmark -- ANALYSIS
ONLY. No src/ changes, no LLM/API calls. `symspellpy` was pip-installed
into this environment for this benchmark only (not added to project
dependencies -- see the report).

Question: can a real spell-correction candidate generator (SymSpell) beat
rapidfuzz.extractOne (current production) and plain rapidfuzz top-K at
putting the TRUE catalog word inside the candidate set? Selection (which
candidate to trust) is explicitly OUT of scope -- see
sprint6_typo_selector_benchmark.py for that question.

Vocabulary for EVERY generator is index.postings.keys() only -- the real
catalog/search vocabulary, no external dictionary. SymSpell's dictionary
entries use each word's real document frequency (len(postings[word])) as
its "count", so higher-support catalog words are preferred exactly like
the existing SPELLING_CORRECTION_MIN_TARGET_DOCS signal already does.

Dataset: reuses evaluation/sprint6_typo_candidate_dataset.json UNCHANGED
(199 cases: 160 typo + 20 clean_catalog + 19 clean_filler; not the frozen
semantic holdout). Plus two named regression controls (milq, mliq),
reported separately, never scored into the aggregate metrics.

Usage: python evaluation/sprint6_symspell_candidate_benchmark.py
Writes: evaluation/sprint6_symspell_candidate_results.json
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rapidfuzz import fuzz, process  # noqa: E402
from symspellpy import SymSpell, Verbosity  # noqa: E402

from src.search_engine.index import get_index  # noqa: E402
from src.search_engine.ranking import SPELLING_CORRECTION_THRESHOLD  # noqa: E402

REGRESSION_CONTROLS = ["milq", "mliq"]


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


# --- generators ----------------------------------------------------------

def rapidfuzz_topk(vocab_list: list[str], token: str, k: int) -> list[str]:
    raw = process.extract(token, vocab_list, scorer=fuzz.ratio, limit=k)
    return [c for c, s, _i in raw if s >= SPELLING_CORRECTION_THRESHOLD]


def symspell_topk(sym: SymSpell, token: str, k: int, max_edit_distance: int = 2) -> list[str]:
    suggestions = sym.lookup(token, Verbosity.ALL, max_edit_distance=max_edit_distance)
    return [s.term for s in suggestions[:k]]


# --- benchmark -------------------------------------------------------------

def main() -> None:
    index = get_index()
    vocab_list = list(index.postings.keys())
    log(f"catalog vocabulary size: {len(vocab_list)}")

    t0 = time.perf_counter()
    sym = SymSpell(max_dictionary_edit_distance=2, prefix_length=7)
    for word, pids in index.postings.items():
        sym.create_dictionary_entry(word, len(pids))
    symspell_build_s = time.perf_counter() - t0
    log(f"SymSpell dictionary build time: {symspell_build_s:.3f}s for {len(vocab_list)} words")

    data = json.loads((ROOT / "evaluation" / "sprint6_typo_candidate_dataset.json").read_text(encoding="utf-8"))
    cases = data["cases"]
    log(f"Reusing {len(cases)} cases from the existing dev typo dataset (unchanged).")

    generators = {
        "A_rapidfuzz_extractOne_K1": lambda tok, k: rapidfuzz_topk(vocab_list, tok, 1),
        "B_rapidfuzz_topK3": lambda tok, k: rapidfuzz_topk(vocab_list, tok, 3),
        "B_rapidfuzz_topK5": lambda tok, k: rapidfuzz_topk(vocab_list, tok, 5),
        "C_symspell_topK3": lambda tok, k: symspell_topk(sym, tok, 3),
        "C_symspell_topK5": lambda tok, k: symspell_topk(sym, tok, 5),
    }

    # latency probe (typo tokens only, avoids skew from clean/filler cases)
    typo_tokens = [c["tokens"][c["typo_index"]] for c in cases if c["kind"] == "typo"][:80]
    latency = {}
    for name, fn in generators.items():
        t0 = time.perf_counter()
        for tok in typo_tokens:
            fn(tok, None)
        latency[name] = round((time.perf_counter() - t0) / len(typo_tokens) * 1000, 3)  # ms/lookup
    log("avg lookup latency (ms): " + json.dumps(latency))

    def bucket() -> dict:
        return {"n": 0, "avail": 0}

    results = {}
    for gname in generators:
        results[gname] = {
            "overall": bucket(), "en": bucket(), "ar": bucket(),
            "deletion": bucket(), "insertion": bucket(), "substitution": bucket(), "transposition": bucket(),
            "single": bucket(), "multiword": bucket(),
            "clean_catalog_self_present": {"n": 0, "yes": 0},
            "clean_filler_any_candidate": {"n": 0, "yes": 0},
        }

    def tally(b: dict, hit: bool) -> None:
        b["n"] += 1
        b["avail"] += int(hit)

    for c in cases:
        token = c["tokens"][c["typo_index"]]
        for gname, fn in generators.items():
            cands = fn(token, None)
            r = results[gname]
            if c["kind"] == "typo":
                truth = c["truth"]
                hit = truth in cands
                tally(r["overall"], hit)
                tally(r[c["language"]], hit)
                tally(r[c["mutation"]], hit)
                tally(r[c["arity"]], hit)
            elif c["kind"] == "clean_catalog":
                r["clean_catalog_self_present"]["n"] += 1
                r["clean_catalog_self_present"]["yes"] += int(c["truth"] in cands)
            else:  # clean_filler
                r["clean_filler_any_candidate"]["n"] += 1
                r["clean_filler_any_candidate"]["yes"] += int(len(cands) > 0)

    def rate(b: dict) -> float:
        return round(b["avail"] / (b["n"] or 1), 4)

    summary = {}
    for gname, r in results.items():
        summary[gname] = {
            "overall_availability": rate(r["overall"]), "n": r["overall"]["n"],
            "en_availability": rate(r["en"]), "ar_availability": rate(r["ar"]),
            "deletion": rate(r["deletion"]), "insertion": rate(r["insertion"]),
            "substitution": rate(r["substitution"]), "transposition": rate(r["transposition"]),
            "single_word": rate(r["single"]), "multiword_one_typo": rate(r["multiword"]),
            "clean_catalog_self_present_pct": round(
                100 * r["clean_catalog_self_present"]["yes"] / (r["clean_catalog_self_present"]["n"] or 1), 1),
            "clean_filler_any_candidate_pct": round(
                100 * r["clean_filler_any_candidate"]["yes"] / (r["clean_filler_any_candidate"]["n"] or 1), 1),
        }

    # regression evidence -- never scored
    regression = {}
    for tok in REGRESSION_CONTROLS:
        regression[tok] = {gname: fn(tok, None) for gname, fn in generators.items()}

    out = {
        "vocab_size": len(vocab_list),
        "symspell_build_time_s": round(symspell_build_s, 3),
        "avg_lookup_latency_ms": latency,
        "dataset_n": len(cases),
        "summary": summary,
        "regression_controls": regression,
    }
    log(json.dumps(summary, indent=2))
    log("regression controls: " + json.dumps(regression, ensure_ascii=False))
    (ROOT / "evaluation" / "sprint6_symspell_candidate_results.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    log("Wrote evaluation/sprint6_symspell_candidate_results.json")


if __name__ == "__main__":
    main()
