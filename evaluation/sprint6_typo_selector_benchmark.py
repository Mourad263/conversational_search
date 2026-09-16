"""Sprint 6 typo SELECTION benchmark -- ANALYSIS ONLY. Reuses the existing
frozen-dev dataset (sprint6_typo_candidate_dataset.json, unchanged, not
rebuilt) and the same top-K generation as sprint6_typo_candidate_benchmark
.py's method_b. The only thing varied here is the SELECTION rule applied
on top of identical candidates -- generation is held fixed throughout.

No LLM/API calls. No src/ changes. Holdout untouched.

Selectors compared (all deterministic, all using only evidence already
computed for method_b -- fuzzy score, candidate document frequency,
candidate/context co-occurrence support):

  A. CURRENT (argmax co-occurrence support; ties -> df, then score;
     falls back to argmax df when the query has no other matching token
     to build context from). This is exactly sprint6_typo_candidate_
     benchmark.py's method_b selection step -- reproduced here to keep
     the two scripts independently runnable.

  B. MARGIN-GATED: same ranking as A, but the winner must beat the
     runner-up by >= MARGIN real documents (co-occurrence support, or df
     when there is no context) or the correction is left unresolved.
     Swept over MARGIN in {1, 2, 3}.

  C. NORMALIZED-MARGIN (combined evidence): ranks by support fraction of
     the context (support / |context|) instead of a raw count, which
     stops a small absolute lead from looking confident inside a huge
     context -- then gates on the fractional margin between winner and
     runner-up. Swept over RATIO_MARGIN in {0.05, 0.10, 0.20}. Falls back
     to B's df-margin gate when there is no context.

Usage: python evaluation/sprint6_typo_selector_benchmark.py
Writes: evaluation/sprint6_typo_selector_results.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rapidfuzz import fuzz, process  # noqa: E402

from src.search_engine.index import get_index  # noqa: E402
from src.search_engine.ranking import (  # noqa: E402
    SPELLING_CORRECTION_MIN_TARGET_DOCS,
    SPELLING_CORRECTION_THRESHOLD,
)

TOP_K = 5
MARGIN_VALUES = [1, 2, 3]
RATIO_MARGIN_VALUES = [0.05, 0.10, 0.20]


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def candidates_for(index, tokens: list[str], typo_index: int, k: int = TOP_K) -> dict:
    """Identical candidate generation + context to method_b. Returns raw
    per-candidate evidence so every selector below reads the SAME numbers."""
    token = tokens[typo_index]
    raw = process.extract(token, list(index.postings.keys()), scorer=fuzz.ratio, limit=k)
    generated = [c for c, _s, _i in raw]
    survivors = [
        (c, s, len(index.postings[c])) for c, s, _i in raw
        if s >= SPELLING_CORRECTION_THRESHOLD and len(index.postings[c]) >= SPELLING_CORRECTION_MIN_TARGET_DOCS
    ]
    matching = [t for i, t in enumerate(tokens) if i != typo_index and t in index.postings]
    context: set[int] = set()
    if matching:
        context = set(index.postings[matching[0]])
        for t in matching[1:]:
            context &= set(index.postings[t])
        if not context:
            for t in matching:
                context |= set(index.postings[t])

    rows = []
    for c, s, df in survivors:
        support = len(set(index.postings[c]) & context) if context else 0
        rows.append({"candidate": c, "score": s, "df": df, "support": support})
    return {"generated": generated, "rows": rows, "has_context": bool(context),
            "context_size": len(context)}


# --- selectors ----------------------------------------------------------

def select_A(ev: dict) -> str | None:
    rows = ev["rows"]
    if not rows:
        return None
    if ev["has_context"]:
        best = max(rows, key=lambda r: (r["support"], r["df"], r["score"]))
        if best["support"] == 0:
            return None
        return best["candidate"]
    return max(rows, key=lambda r: (r["df"], r["score"]))["candidate"]


def select_B(ev: dict, margin: int) -> str | None:
    rows = ev["rows"]
    if not rows:
        return None
    if ev["has_context"]:
        ranked = sorted(rows, key=lambda r: (r["support"], r["df"], r["score"]), reverse=True)
        best = ranked[0]
        if best["support"] == 0:
            return None
        runner_up_support = ranked[1]["support"] if len(ranked) > 1 else 0
        if best["support"] - runner_up_support < margin:
            return None
        return best["candidate"]
    ranked = sorted(rows, key=lambda r: (r["df"], r["score"]), reverse=True)
    best = ranked[0]
    runner_up_df = ranked[1]["df"] if len(ranked) > 1 else 0
    if best["df"] - runner_up_df < margin:
        return None
    return best["candidate"]


def select_C(ev: dict, ratio_margin: float, df_margin: int = 2) -> str | None:
    rows = ev["rows"]
    if not rows:
        return None
    if ev["has_context"]:
        size = max(ev["context_size"], 1)
        ranked = sorted(rows, key=lambda r: (r["support"] / size, r["df"], r["score"]), reverse=True)
        best = ranked[0]
        if best["support"] == 0:
            return None
        best_ratio = best["support"] / size
        runner_ratio = (ranked[1]["support"] / size) if len(ranked) > 1 else 0.0
        if best_ratio - runner_ratio < ratio_margin:
            return None
        return best["candidate"]
    ranked = sorted(rows, key=lambda r: (r["df"], r["score"]), reverse=True)
    best = ranked[0]
    runner_up_df = ranked[1]["df"] if len(ranked) > 1 else 0
    if best["df"] - runner_up_df < df_margin:
        return None
    return best["candidate"]


# --- scoring --------------------------------------------------------------

def blank() -> dict:
    return {"n": 0, "correct": 0, "wrong": 0, "unresolved": 0,
            "avail_selected_correct": 0, "avail_selected_wrong": 0, "avail_rejected": 0,
            "avail_n": 0}


def tally(bucket: dict, truth: str | None, generated: list[str], selected: str | None) -> None:
    bucket["n"] += 1
    if truth is None:  # control: any non-None selection is damage
        if selected is not None:
            bucket["wrong"] += 1
        else:
            bucket["correct"] += 1
        return
    if selected == truth:
        bucket["correct"] += 1
    elif selected is None:
        bucket["unresolved"] += 1
    else:
        bucket["wrong"] += 1
    if truth in generated:
        bucket["avail_n"] += 1
        if selected == truth:
            bucket["avail_selected_correct"] += 1
        elif selected is None:
            bucket["avail_rejected"] += 1
        else:
            bucket["avail_selected_wrong"] += 1


def rates(b: dict) -> dict:
    n = b["n"] or 1
    an = b["avail_n"] or 1
    return {
        "n": b["n"], "correct_pct": round(100 * b["correct"] / n, 2),
        "wrong_pct": round(100 * b["wrong"] / n, 2),
        "unresolved_pct": round(100 * b["unresolved"] / n, 2),
        "when_available": {
            "n": b["avail_n"],
            "selected_correct_pct": round(100 * b["avail_selected_correct"] / an, 2),
            "selected_wrong_pct": round(100 * b["avail_selected_wrong"] / an, 2),
            "rejected_uncertain_pct": round(100 * b["avail_rejected"] / an, 2),
        },
    }


def evaluate(index, cases: list[dict], select_fn) -> tuple[dict, list[dict]]:
    overall = blank()
    by_lang = {"en": blank(), "ar": blank()}
    by_mut = {k: blank() for k in ("deletion", "insertion", "substitution", "transposition")}
    by_arity = {"single": blank(), "multiword": blank()}
    controls = {"clean_catalog": blank(), "clean_filler": blank()}
    wrong_cases = []

    for c in cases:
        ev = candidates_for(index, c["tokens"], c["typo_index"])
        selected = select_fn(ev)
        if c["kind"] == "typo":
            tally(overall, c["truth"], ev["generated"], selected)
            tally(by_lang[c["language"]], c["truth"], ev["generated"], selected)
            tally(by_mut[c["mutation"]], c["truth"], ev["generated"], selected)
            tally(by_arity[c["arity"]], c["truth"], ev["generated"], selected)
            if selected is not None and selected != c["truth"]:
                wrong_cases.append({"id": c["id"], "language": c["language"], "mutation": c["mutation"],
                                     "arity": c["arity"], "tokens": c["tokens"], "truth": c["truth"],
                                     "selected": selected, "evidence": ev})
        else:
            # clean_catalog: the word already has real postings, so a
            # selection equal to ITSELF is correct passthrough, not damage
            # -- only clean_filler genuinely has no right answer (truth=None).
            control_truth = c["truth"] if c["kind"] == "clean_catalog" else None
            tally(controls[c["kind"]], control_truth, ev["generated"], selected)
            if selected is not None and selected != control_truth:
                wrong_cases.append({"id": c["id"], "language": c["language"], "kind": c["kind"],
                                     "tokens": c["tokens"], "truth": None, "selected": selected,
                                     "evidence": ev})

    summary = {
        "overall_typo": rates(overall),
        "by_language": {k: rates(v) for k, v in by_lang.items()},
        "by_mutation": {k: rates(v) for k, v in by_mut.items()},
        "by_arity": {k: rates(v) for k, v in by_arity.items()},
        "controls": {
            "clean_catalog": {"n": controls["clean_catalog"]["n"],
                               "damage_pct": round(100 * controls["clean_catalog"]["wrong"] / (controls["clean_catalog"]["n"] or 1), 2)},
            "clean_filler": {"n": controls["clean_filler"]["n"],
                              "damage_pct": round(100 * controls["clean_filler"]["wrong"] / (controls["clean_filler"]["n"] or 1), 2)},
        },
    }
    return summary, wrong_cases


def classify_failure(row: dict) -> str:
    ev = row["evidence"]
    rows = ev["rows"]
    scores = sorted((r["score"] for r in rows), reverse=True)
    if len(scores) >= 2 and (scores[0] - scores[1]) <= 3:
        return "candidates_too_lexically_similar"
    if not ev["has_context"]:
        return "insufficient_context_single_word"
    supports = sorted((r["support"] for r in rows), reverse=True)
    dfs = sorted((r["df"] for r in rows), reverse=True)
    if supports and supports[0] == 0:
        return "misleading_cooccurrence_no_real_support"
    if len(dfs) >= 2 and dfs[0] > 3 * max(dfs[1], 1) and row["language"] == "en":
        return "corpus_frequency_dominance"
    if row.get("language") == "ar":
        return "arabic_morphology_character_ambiguity"
    return "other_general_cause"


def main() -> None:
    index = get_index()
    data = json.loads((ROOT / "evaluation" / "sprint6_typo_candidate_dataset.json").read_text(encoding="utf-8"))
    cases = data["cases"]
    log(f"Reusing {len(cases)} cases from the existing dataset (unchanged).")

    all_results = {}

    summary_a, wrong_a = evaluate(index, cases, select_A)
    all_results["A_current_argmax"] = summary_a
    log("A (current argmax): " + json.dumps(summary_a["overall_typo"], indent=None))
    log("  controls: " + json.dumps(summary_a["controls"]))

    for m in MARGIN_VALUES:
        summary, wrong = evaluate(index, cases, lambda ev, m=m: select_B(ev, m))
        all_results[f"B_margin_{m}"] = summary
        log(f"B margin={m}: " + json.dumps(summary["overall_typo"], indent=None))
        log("  controls: " + json.dumps(summary["controls"]))

    best_c_name, best_c_wrong, best_c_summary = None, None, None
    for rm in RATIO_MARGIN_VALUES:
        summary, wrong = evaluate(index, cases, lambda ev, rm=rm: select_C(ev, rm))
        name = f"C_ratio_margin_{rm}"
        all_results[name] = summary
        log(f"C ratio_margin={rm}: " + json.dumps(summary["overall_typo"], indent=None))
        log("  controls: " + json.dumps(summary["controls"]))
        if best_c_summary is None or summary["overall_typo"]["wrong_pct"] < best_c_summary["overall_typo"]["wrong_pct"]:
            best_c_name, best_c_wrong, best_c_summary = name, wrong, summary

    # Failure classification for the two safest-looking selectors: A and
    # the safest B margin (by wrong_pct on typo cases; ties -> higher correct_pct).
    b_candidates = [(f"B_margin_{m}", all_results[f"B_margin_{m}"]) for m in MARGIN_VALUES]
    safest_b_name, _ = min(b_candidates, key=lambda kv: (kv[1]["overall_typo"]["wrong_pct"], -kv[1]["overall_typo"]["correct_pct"]))
    safest_b_margin = int(safest_b_name.split("_")[-1])
    _, wrong_b = evaluate(index, cases, lambda ev: select_B(ev, safest_b_margin))

    failure_classes_a = {}
    for row in wrong_a:
        cls = classify_failure(row)
        failure_classes_a[cls] = failure_classes_a.get(cls, 0) + 1
    failure_classes_b = {}
    for row in wrong_b:
        cls = classify_failure(row)
        failure_classes_b[cls] = failure_classes_b.get(cls, 0) + 1

    out = {
        "note": "candidates/context reused unchanged from sprint6_typo_candidate_dataset.json; "
                "only the selection rule varies across A/B/C.",
        "selectors": all_results,
        "safest_B": safest_b_name,
        "safest_C_by_wrong_pct": best_c_name,
        "failure_classes": {"A_current_argmax": failure_classes_a, safest_b_name: failure_classes_b},
    }
    (ROOT / "evaluation" / "sprint6_typo_selector_results.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"Wrote evaluation/sprint6_typo_selector_results.json")
    log(f"safest_B={safest_b_name}  safest_C={best_c_name}")
    log("failure classes A: " + json.dumps(failure_classes_a))
    log(f"failure classes {safest_b_name}: " + json.dumps(failure_classes_b))


if __name__ == "__main__":
    main()
