"""Sprint 6 POST-REFACTOR benchmark runner. Evaluation artifact only.

For each case: understand() [real LLM] -> validate() -> SearchAdapter.search().
Reports 5 metrics separately, per the task's requirement not to collapse
them into one blended score:
  (A) semantic extraction accuracy -- does the LLM's OWN Action match the
      hand-authored intended roles for this sentence (intent/price/target_facet
      exactly; raw_query_text/category_hint/brand_text/free_from by substring
      containment, since natural phrasing varies).
  (B) catalog-grounding accuracy -- does validate(action) land on the SAME
      category/brand as validate() applied to the intended roles (computed at
      build time into expected_grounding).
  (C) exact category recall, UNAMBIGUOUS cases only -- of the cases where a
      category is objectively expected and not marked ambiguous, how many
      does the pipeline actually recall.
  (D) final search success -- adapter.search() returns non-zero results, and
      (when an unambiguous category was expected) most of the top results
      actually belong to it.
  (E) wrong-confident-match rate -- fraction of UNAMBIGUOUS cases where the
      resolved category or brand is non-null but WRONG (the precision/safety
      number Section 8 cares about most).

Usage: python evaluation/sprint6_semantic_benchmark_run.py <dataset.json> [label]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.search_adapter.adapter import FilterSet, SearchAdapter  # noqa: E402
from src.search_engine.keyword_baseline import _get_catalog_names  # noqa: E402
from src.understanding.llm import understand  # noqa: E402
from src.validation.validate import validate  # noqa: E402


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def role_match(actual: str | None, intended: str | None) -> bool:
    if intended is None:
        return True  # not asserting this role for this case
    if actual is None:
        return False
    return intended.strip().lower() in actual.strip().lower()


def run(dataset_path: Path, label: str) -> dict:
    data = json.loads(dataset_path.read_text(encoding="utf-8"))
    cases = data["cases"]
    catalog_ids = _get_catalog_names()
    adapter = SearchAdapter()

    results = []
    for case in cases:
        sentence = case["sentence"]
        history = case.get("history")
        expected = case["expected"]
        roles = case["roles"]
        grounding = case["expected_grounding"]
        ambiguous = case["ambiguous"]

        action = understand(sentence, history=history) if history else understand(sentence)
        filters = validate(action)

        # --- Metric A: semantic extraction accuracy ---
        a_intent = action.intent.value == expected["intent"]
        a_price_min = action.price_min == expected["price_min"]
        a_price_max = action.price_max == expected["price_max"]
        a_target_facet = (action.target_facet.value if action.target_facet else None) == expected["target_facet"]
        a_raw = role_match(action.raw_query_text, roles["raw_query_text"])
        a_cat_hint = role_match(action.category_hint, roles["category_hint"])
        a_brand = role_match(action.brand_text, roles["brand_text"])
        a_free_from = role_match(action.free_from, roles["free_from"])
        a_fields = [a_intent, a_price_min, a_price_max, a_target_facet, a_raw, a_cat_hint, a_brand, a_free_from]
        a_all_correct = all(a_fields)

        # --- Metric B: catalog-grounding accuracy (vs intended-role grounding) ---
        b_category = filters.category == grounding["category"]
        b_brand = filters.brand == grounding["brand"]
        b_all_correct = b_category and b_brand

        # --- Metric D: final search success ---
        search_filters = FilterSet(
            category=filters.category, price_min=filters.price_min, price_max=filters.price_max,
            brand=filters.brand, query_text=filters.query_text,
        )
        try:
            search_result = adapter.search(search_filters, limit=10)
        except Exception as exc:  # noqa: BLE001
            search_result = None
            log(f"  [search error] {sentence!r}: {exc}")

        d_zero_result = search_result.zero_result if search_result else True
        d_category_precision = None
        if search_result and not d_zero_result and grounding["category"] and not ambiguous:
            wanted_ids = catalog_ids["product_ids_by_category_slug"].get(grounding["category"], set())
            hits = [p for p in search_result.products if p.get("id") in wanted_ids]
            d_category_precision = len(hits) / len(search_result.products) if search_result.products else 0.0
        d_success = (not d_zero_result) and (d_category_precision is None or d_category_precision >= 0.5)
        # off_topic / no_op / remove_filter / reset cases carry no product
        # intent at all -- "final search success" is meaningless for them.
        d_applicable = expected["intent"] in ("search", "add_filter", "modify_filter")

        results.append({
            "id": case["id"], "tag": case["tag"], "sentence": sentence, "ambiguous": ambiguous,
            "a_all_correct": a_all_correct, "a_fields": {
                "intent": a_intent, "price_min": a_price_min, "price_max": a_price_max,
                "target_facet": a_target_facet, "raw_query_text": a_raw, "category_hint": a_cat_hint,
                "brand_text": a_brand, "free_from": a_free_from,
            },
            "b_category": b_category, "b_brand": b_brand,
            "actual": {
                "intent": action.intent.value, "price_min": action.price_min, "price_max": action.price_max,
                "raw_query_text": action.raw_query_text, "category_hint": action.category_hint,
                "brand_text": action.brand_text, "free_from": action.free_from,
                "resolved_category": filters.category, "resolved_brand": filters.brand,
            },
            "expected_grounding": grounding,
            "d_applicable": d_applicable, "d_zero_result": d_zero_result,
            "d_category_precision": d_category_precision, "d_success": d_success if d_applicable else None,
        })

    n = len(results)
    metric_a = sum(r["a_all_correct"] for r in results) / n
    metric_b = sum(r["b_category"] and r["b_brand"] for r in results) / n

    unambiguous = [r for r in results if not r["ambiguous"]]
    cat_expected = [r for r in unambiguous if r["expected_grounding"]["category"] is not None]
    metric_c = (sum(r["b_category"] for r in cat_expected) / len(cat_expected)) if cat_expected else None

    applicable = [r for r in results if r["d_applicable"]]
    metric_d = (sum(r["d_success"] for r in applicable) / len(applicable)) if applicable else None

    wrong_confident = 0
    denom_e = 0
    for r in unambiguous:
        exp_cat, exp_brand = r["expected_grounding"]["category"], r["expected_grounding"]["brand"]
        act_cat, act_brand = r["actual"]["resolved_category"], r["actual"]["resolved_brand"]
        if exp_cat is not None or exp_brand is not None or act_cat is not None or act_brand is not None:
            denom_e += 1
            wrong_cat = act_cat is not None and act_cat != exp_cat
            wrong_brand = act_brand is not None and act_brand != exp_brand
            if wrong_cat or wrong_brand:
                wrong_confident += 1
    metric_e = (wrong_confident / denom_e) if denom_e else None

    summary = {
        "label": label, "dataset": str(dataset_path), "n_cases": n,
        "metric_A_semantic_extraction_accuracy": metric_a,
        "metric_B_catalog_grounding_accuracy": metric_b,
        "metric_C_category_recall_unambiguous": metric_c,
        "metric_C_n": len(cat_expected),
        "metric_D_final_search_success": metric_d,
        "metric_D_n": len(applicable),
        "metric_E_wrong_confident_match_rate": metric_e,
        "metric_E_n": denom_e,
    }
    log(json.dumps(summary, indent=2))

    out_path = ROOT / "evaluation" / f"sprint6_semantic_benchmark_results_{label}.json"
    out_path.write_text(json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"Wrote {out_path}")
    return summary


if __name__ == "__main__":
    path = Path(sys.argv[1])
    label = sys.argv[2] if len(sys.argv) > 2 else path.stem
    run(path, label)
