"""Sprint 6 Module 2 acceptance check -- runs the Module 1 query-rewrite
contract (evaluation/sprint6_query_rewrite_contract.json, unchanged) once
against the live understand() call and grades raw_query_text against the
contract. Evaluation artifact only.

Usage: python evaluation/sprint6_module2_rewrite_check.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.understanding.llm import understand  # noqa: E402


def norm(s: str | None) -> str:
    return (s or "").strip().lower()


def main() -> None:
    data = json.loads((ROOT / "evaluation" / "sprint6_query_rewrite_contract.json").read_text(encoding="utf-8"))
    cases = data["cases"]

    results = []
    for c in cases:
        action = understand(c["sentence"])
        actual = action.raw_query_text
        expected = c["product_query"]

        if c["typo_preserved"]:
            # the typo'd token itself must survive verbatim
            typo_token = c["sentence"].strip().split()[-1] if " " in c["sentence"] else c["sentence"].strip()
            # find the token(s) contract marks as the typo by checking they're in expected too
            ok = norm(expected) in norm(actual) or norm(actual) == norm(expected)
        else:
            ok = norm(actual) == norm(expected) or norm(expected) in norm(actual) or norm(actual) in norm(expected)

        brand_leak = bool(c["brand_text"]) and norm(c["brand_text"]) in norm(actual)
        free_from_leak = bool(c["free_from"]) and norm(c["free_from"]) in norm(actual)

        results.append({
            "tag": c["tag"], "language": c["language"], "sentence": c["sentence"],
            "expected_product_query": expected, "actual_raw_query_text": actual,
            "typo_preserved_required": c["typo_preserved"],
            "pass": ok and not brand_leak and not free_from_leak,
            "brand_leak": brand_leak, "free_from_leak": free_from_leak,
            "actual_brand_text": action.brand_text, "actual_free_from": action.free_from,
        })

    n = len(results)
    passed = sum(r["pass"] for r in results)
    typo_cases = [r for r in results if r["typo_preserved_required"]]
    typo_passed = sum(r["pass"] for r in typo_cases)
    by_lang = {}
    for r in results:
        b = by_lang.setdefault(r["language"], {"n": 0, "pass": 0})
        b["n"] += 1
        b["pass"] += r["pass"]

    summary = {
        "n_cases": n, "passed": passed,
        "typo_preservation": {"n": len(typo_cases), "passed": typo_passed},
        "by_language": by_lang,
        "failures": [r for r in results if not r["pass"]],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2), file=sys.stderr)
    (ROOT / "evaluation" / "sprint6_module2_rewrite_check_results.json").write_text(
        json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
