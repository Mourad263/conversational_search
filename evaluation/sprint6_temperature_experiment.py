"""Sprint 6 temperature experiment -- run LAST, on the frozen HOLDOUT set
(unseen: never used to tune the prompt, no result from it was ever patched
back into SYSTEM_PROMPT or the ground truth). Evaluation artifact only.

For each temperature in {0.0, 0.1, 0.2, 0.3}, runs a fixed 24-case subset
3 times each (72 calls per temperature, 288 total) and measures:
  - field-level correctness, per field, averaged over all 3 runs
  - whole-Action exact correctness (all fields simultaneously right)
  - run-to-run CONSISTENCY: for each case, do all 3 runs at this
    temperature produce the identical Action (all fields)? -- the number
    a parameter-extraction step actually needs, independent of whether
    that identical answer happens to be correct.

Usage: python evaluation/sprint6_temperature_experiment.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation.sprint6_semantic_benchmark_run import role_match  # noqa: E402
from src.understanding.llm import understand  # noqa: E402

TEMPERATURES = [0.0, 0.1, 0.2, 0.3]
N_RUNS = 3
N_CASES = 24
FIELDS_EXACT = ("intent", "price_min", "price_max", "target_facet")
FIELDS_ROLE = ("raw_query_text", "category_hint", "brand_text", "free_from")


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def action_signature(action) -> tuple:
    return (
        action.intent.value, action.price_min, action.price_max,
        action.target_facet.value if action.target_facet else None,
        (action.raw_query_text or "").strip().lower(),
        (action.category_hint or "").strip().lower(),
        (action.brand_text or "").strip().lower(),
        (action.free_from or "").strip().lower(),
    )


def field_correct(action, expected: dict, roles: dict) -> dict:
    out = {}
    for f in FIELDS_EXACT:
        actual = action.target_facet.value if f == "target_facet" and action.target_facet else getattr(action, f)
        if f == "intent":
            actual = action.intent.value
        out[f] = actual == expected[f]
    for f in FIELDS_ROLE:
        out[f] = role_match(getattr(action, f), roles[f])
    return out


def main() -> None:
    holdout = json.loads((ROOT / "evaluation" / "sprint6_semantic_benchmark_holdout.json").read_text(encoding="utf-8"))
    cases = holdout["cases"][:N_CASES]
    log(f"Using {len(cases)} holdout cases, {N_RUNS} runs x {len(TEMPERATURES)} temperatures "
        f"= {len(cases) * N_RUNS * len(TEMPERATURES)} calls.")

    all_results = {}
    for temp in TEMPERATURES:
        log(f"--- temperature={temp} ---")
        per_case_runs: dict[int, list] = {c["id"]: [] for c in cases}
        field_hits = {f: 0 for f in FIELDS_EXACT + FIELDS_ROLE}
        exact_hits = 0
        total = 0
        for run_idx in range(N_RUNS):
            for case in cases:
                action = understand(case["sentence"], history=case.get("history"), temperature=temp)
                fc = field_correct(action, case["expected"], case["roles"])
                for f, ok in fc.items():
                    field_hits[f] += int(ok)
                if all(fc.values()):
                    exact_hits += 1
                total += 1
                per_case_runs[case["id"]].append(action_signature(action))
            log(f"  run {run_idx + 1}/{N_RUNS} done")

        consistent = sum(1 for sigs in per_case_runs.values() if len(set(sigs)) == 1)
        summary = {
            "temperature": temp,
            "n_calls": total,
            "field_accuracy": {f: field_hits[f] / total for f in field_hits},
            "exact_action_accuracy": exact_hits / total,
            "run_to_run_consistency": consistent / len(cases),
        }
        log(json.dumps(summary, indent=2))
        all_results[str(temp)] = summary

    out_path = ROOT / "evaluation" / "sprint6_temperature_results.json"
    out_path.write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
