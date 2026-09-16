"""Sprint 6 Part 1: runs the FROZEN blind holdout benchmark built by
sprint6_build_manifest.py. Evaluation script only -- imports production
code read-only (parse_keyword_query/search_keyword/handle_message/
correct_unmatched_terms for diagnosis), never modifies it, never adds to
any blocklist/alias/threshold. The first blind score from this run is
final and is not patched based on what it finds (spec section 14).

Usage: python evaluation/sprint6_run_benchmark.py
Writes: evaluation/sprint6_holdout_results.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ingestion.text_normalize import is_arabic  # noqa: E402
from src.scenario.orchestrator import handle_message  # noqa: E402
from src.scenario.session_activity import SessionActivityStore  # noqa: E402
from src.search_engine import keyword_baseline as kb  # noqa: E402
from src.search_engine.index import get_index  # noqa: E402
from src.search_engine.ranking import correct_unmatched_terms  # noqa: E402
from src.search_engine.tokenizer import tokenize  # noqa: E402
from src.state_manager.state_manager import StateManager  # noqa: E402

MANIFEST_PATH = ROOT / "evaluation" / "sprint6_holdout_manifest.json"


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def top5(result) -> list[dict]:
    return [{"id": p["id"], "name_en": p.get("name_en"), "name_ar": p.get("name_ar")} for p in result.products[:5]]


def id_set(entries: list[dict]) -> set:
    return {e["id"] for e in entries}


# ============================================================
# Section 4/7/8: deterministic product-word / brand / category benchmark
# ============================================================

def eval_product_word_entry(entry: dict, idx) -> dict:
    clean = entry["source_clean"]
    typo = entry["mutated"]

    clean_result = kb.search_keyword(clean, limit=5)
    clean_top5 = top5(clean_result)
    clean_ok = (not clean_result.zero_result) and clean_result.total_count > 0 and any(
        clean in tokenize((p["name_en"] or "") + " " + (p["name_ar"] or ""), idx.base_freq)
        for p in clean_result.products[:5]
    )
    if not clean_ok:
        return {
            **entry, "verdict": "excluded_clean_baseline_failure",
            "failure_layer": "clean_baseline_failure",
            "clean_total_count": clean_result.total_count,
            "clean_top5": clean_top5,
        }

    typo_result = kb.search_keyword(typo, limit=5)
    typo_top5 = top5(typo_result)
    overlap = id_set(clean_top5) & id_set(typo_top5)
    corrected = correct_unmatched_terms(idx, typo)
    corrected_tokens = tokenize(corrected, idx.base_freq) if corrected else []
    exact_correction = clean in corrected_tokens

    if typo_result.zero_result or typo_result.total_count == 0:
        verdict, layer = "FAIL", "typo_not_corrected"
    elif exact_correction or len(overlap) >= 1:
        verdict, layer = "PASS", None
    else:
        verdict, layer = "FAIL", "wrong_spelling_correction"

    return {
        **entry, "verdict": verdict, "failure_layer": layer,
        "clean_total_count": clean_result.total_count, "clean_top5": clean_top5,
        "typo_total_count": typo_result.total_count, "typo_zero_result": typo_result.zero_result,
        "typo_top5": typo_top5, "top5_id_overlap": len(overlap),
        "corrected_query_text": corrected, "exact_correction_to_source": exact_correction,
    }


def eval_brand_entry(entry: dict) -> dict:
    clean, typo, canonical_slug = entry["source_clean"], entry["mutated"], entry["canonical_slug"]
    clean_fs = kb.parse_keyword_query(clean)
    if clean_fs.brand != canonical_slug:
        return {
            **entry, "verdict": "excluded_clean_baseline_failure",
            "failure_layer": "clean_baseline_failure",
            "clean_resolved_brand": clean_fs.brand,
        }
    typo_fs = kb.parse_keyword_query(typo)
    typo_result = kb.search_keyword(typo, limit=5)
    if typo_fs.brand == canonical_slug:
        verdict, layer, kind = "PASS", None, "correct_brand_recovery"
    elif typo_fs.brand is not None:
        verdict, layer, kind = "FAIL", "brand_hijack", "wrong_brand_recovery"
    elif typo_fs.category is not None:
        verdict, layer, kind = "FAIL", "category_hijack", "category_hijack"
    else:
        verdict, layer, kind = "FAIL", "typo_not_corrected", "no_brand_recovery"
    return {
        **entry, "verdict": verdict, "failure_layer": layer, "recovery_kind": kind,
        "typo_resolved_brand": typo_fs.brand, "typo_resolved_category": typo_fs.category,
        "typo_total_count": typo_result.total_count, "typo_top5": top5(typo_result),
    }


def eval_category_entry(entry: dict) -> dict:
    clean, typo, canonical_slug = entry["source_clean"], entry["mutated"], entry["canonical_slug"]
    clean_fs = kb.parse_keyword_query(clean)
    if clean_fs.category != canonical_slug:
        return {
            **entry, "verdict": "excluded_clean_baseline_failure",
            "failure_layer": "clean_baseline_failure",
            "clean_resolved_category": clean_fs.category,
        }
    typo_fs = kb.parse_keyword_query(typo)
    typo_result = kb.search_keyword(typo, limit=5)
    if typo_fs.category == canonical_slug:
        verdict, layer = ("PASS", None) if not typo_result.zero_result else ("PARTIAL", "lexical_retrieval")
    elif typo_fs.brand is not None:
        verdict, layer = "FAIL", "brand_hijack"
    elif typo_fs.category is not None:
        verdict, layer = "FAIL", "category_hijack"
    else:
        verdict, layer = "FAIL", "typo_not_corrected"
    return {
        **entry, "verdict": verdict, "failure_layer": layer,
        "typo_resolved_category": typo_fs.category, "typo_resolved_brand": typo_fs.brand,
        "typo_total_count": typo_result.total_count, "typo_top5": top5(typo_result),
    }


# ============================================================
# Section 9: natural-query holdout (real pipeline)
# ============================================================

def eval_natural_query(nq: dict, counter: list) -> dict:
    counter[0] += 1
    sm, store = StateManager(), SessionActivityStore()
    resp = handle_message(f"sprint6-natural-{counter[0]}", nq["query"], state_manager=sm, activity_store=store)
    names = [p.name_en or p.name_ar for p in resp.products[:5]]
    source_norm = nq["source_clean"]
    recovered = any(
        source_norm in tokenize((p.name_en or "") + " " + (p.name_ar or ""), get_index().base_freq)
        for p in resp.products[:5]
    )
    if resp.zero_result:
        verdict, layer = "FAIL", "typo_not_corrected"
    elif recovered:
        verdict, layer = "PASS", None
    else:
        verdict, layer = "PARTIAL", "ambiguous_ground_truth"
    return {
        **nq, "verdict": verdict, "failure_layer": layer,
        "intent": str(resp.intent), "resolved_category": resp.resolved_category,
        "resolved_brand": resp.resolved_brand, "total_count": resp.total_count,
        "zero_result": resp.zero_result, "likely_out_of_catalog": resp.likely_out_of_catalog,
        "top5_names": names,
    }


# ============================================================
# Section 10: direct-vs-conversational subset comparison
# ============================================================

def eval_direct_vs_conversational(entry: dict, counter: list) -> dict:
    typo = entry["mutated"]
    direct_fs = kb.parse_keyword_query(typo)
    direct_result = kb.search_keyword(typo, limit=5)
    sm, store = StateManager(), SessionActivityStore()
    counter[0] += 1
    resp = handle_message(f"sprint6-parity-{counter[0]}", typo, state_manager=sm, activity_store=store)
    same_total = direct_result.total_count == resp.total_count
    same_zero = direct_result.zero_result == resp.zero_result
    return {
        "entry_id": entry["id"], "entity_type": entry["entity_type"], "language": entry["language"],
        "source_clean": entry["source_clean"], "typo": typo,
        "direct_category": direct_fs.category, "direct_brand": direct_fs.brand,
        "direct_total_count": direct_result.total_count, "direct_zero_result": direct_result.zero_result,
        "pipeline_intent": str(resp.intent), "pipeline_category": resp.resolved_category,
        "pipeline_brand": resp.resolved_brand, "pipeline_total_count": resp.total_count,
        "pipeline_zero_result": resp.zero_result,
        "agrees": same_total and same_zero,
    }


# ============================================================
# Section 11: multi-turn holdout (fresh entities, not the milk/Juhayna demo)
# ============================================================

def run_multi_turn_conversation(label: str, turns: list[tuple[str, str]], counter: list) -> dict:
    sm, store = StateManager(), SessionActivityStore()
    counter[0] += 1
    session_id = f"sprint6-multiturn-{counter[0]}"
    turn_records = []
    for turn_label, message in turns:
        resp = handle_message(session_id, message, state_manager=sm, activity_store=store)
        turn_records.append({
            "turn": turn_label, "message": message, "intent": str(resp.intent),
            "resolved_category": resp.resolved_category, "resolved_brand": resp.resolved_brand,
            "price_min": resp.price_min, "price_max": resp.price_max,
            "total_count": resp.total_count, "zero_result": resp.zero_result,
        })
    return {"label": label, "turns": turn_records}


# ============================================================
# Section 12: semantic operator (free-from) coverage check
# ============================================================

def eval_free_from_coverage(categories: list[dict]) -> list[dict]:
    out = []
    seen_slugs = set()
    for c in categories:
        if c["slug"] in seen_slugs:
            continue
        seen_slugs.add(c["slug"])
        result = kb.search_keyword(c["name"], limit=5)
        fs = kb.parse_keyword_query(c["name"])
        out.append({
            "slug": c["slug"], "name": c["name"], "resolved_category": fs.category,
            "matches_expected": fs.category == c["slug"],
            "total_count": result.total_count, "zero_result": result.zero_result,
            "top5": [p.get("name_en") for p in result.products[:5]],
        })
    return out


# ============================================================
# Known regression set (explicit, previously-seen examples -- comparison
# baseline only, NEVER counted as holdout generalization evidence)
# ============================================================

_KNOWN_REGRESSION_CASES = [
    ("لانشن", "لانشن"),
    ("milq", "milk"),
    ("choclate", "chocolate"),
    ("شمبو", "شامبو"),
    ("شامنو", "شامبو"),
    ("shmapoo", "shampoo"),
    ("lactose free milk", None),
    ("cream cheese", None),
    ("milk chocolate", None),
    ("chocolate milk", None),
    ("no added sugar", None),
    ("لبن بدون لاكتوز", None),
    ("لبن الشوفان", None),
]


def eval_known_regression(typo_or_query: str, expected_concept: str | None, idx) -> dict:
    result = kb.search_keyword(typo_or_query, limit=5)
    names = [p["name_en"] or p["name_ar"] for p in result.products[:5]]
    if expected_concept is not None:
        recovered = any(
            expected_concept in tokenize((p["name_en"] or "") + " " + (p["name_ar"] or ""), idx.base_freq)
            for p in result.products[:5]
        )
        verdict = "PASS" if (not result.zero_result and recovered) else "FAIL"
    else:
        # semantic/compound cases: judged by non-zero + not an obviously
        # wrong category (spot-checked manually in the report, not scored
        # by a brittle string rule here)
        verdict = "PASS" if not result.zero_result else "FAIL"
    return {
        "query": typo_or_query, "expected_concept": expected_concept, "verdict": verdict,
        "total_count": result.total_count, "zero_result": result.zero_result, "top5": names,
    }


# ============================================================
# Main
# ============================================================

def main() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    idx = get_index()
    results: dict = {"seed": manifest["seed"], "manifest_sha256_path": "evaluation/sprint6_holdout_manifest.sha256.txt"}

    log("=== Known regression set ===")
    known_results = [eval_known_regression(q, exp, idx) for q, exp in _KNOWN_REGRESSION_CASES]
    results["known_regression"] = known_results
    log(f"  {sum(1 for r in known_results if r['verdict']=='PASS')}/{len(known_results)} PASS")

    log("=== Deterministic vocabulary benchmark (product_word/brand/category) ===")
    entries = manifest["vocabulary_entries"]
    vocab_results = []
    for i, e in enumerate(entries):
        if e["entity_type"] == "product_word":
            vocab_results.append(eval_product_word_entry(e, idx))
        elif e["entity_type"] == "brand":
            vocab_results.append(eval_brand_entry(e))
        elif e["entity_type"] == "category":
            vocab_results.append(eval_category_entry(e))
        if (i + 1) % 100 == 0:
            log(f"  ...{i + 1}/{len(entries)} entries scored")
    results["vocabulary_results"] = vocab_results
    log(f"  {len(vocab_results)} entries scored total")

    log("=== Natural-query holdout (real pipeline) ===")
    counter = [0]
    natural_results = [eval_natural_query(nq, counter) for nq in manifest["natural_query_holdout"]]
    results["natural_query_results"] = natural_results
    log(f"  {sum(1 for r in natural_results if r['verdict']=='PASS')}/{len(natural_results)} PASS")

    log("=== Direct-vs-conversational subset ===")
    import random
    rng = random.Random(manifest["seed"])
    product_entries = [e for e in entries if e["entity_type"] == "product_word"]
    subset = rng.sample(product_entries, min(20, len(product_entries)))
    parity_counter = [0]
    parity_results = [eval_direct_vs_conversational(e, parity_counter) for e in subset]
    results["direct_vs_conversational"] = parity_results
    log(f"  {sum(1 for r in parity_results if r['agrees'])}/{len(parity_results)} agree")

    log("=== Multi-turn holdout (fresh entities) ===")
    brands_sample = [e for e in entries if e["entity_type"] == "brand"][:12]
    categories_sample = [e for e in entries if e["entity_type"] == "category"][:12]
    mt_counter = [0]
    multi_turn_results = []
    if len(categories_sample) >= 8 and len(brands_sample) >= 4:
        cat1, cat2 = categories_sample[0]["source_clean"], categories_sample[4]["source_clean"]
        brand1 = brands_sample[0]["source_clean"]
        multi_turn_results.append(run_multi_turn_conversation(
            "initial_search -> add_brand -> add_price -> remove_brand -> replace_category -> topic_switch",
            [
                ("t1_initial_search", cat1),
                ("t2_add_brand", f"من {brand1}" if is_arabic(cat1) else f"from {brand1}"),
                ("t3_add_price", "تحت 200" if is_arabic(cat1) else "under 200"),
                ("t4_remove_brand", "شيل البراند" if is_arabic(cat1) else "remove the brand"),
                ("t5_replace_category", f"عايز {cat2} بدل كده" if is_arabic(cat1) else f"show me {cat2} instead"),
                ("t6_unrelated_topic_switch", "ايه رأيك في الطقس النهاردة؟" if is_arabic(cat1) else "what's the weather like today?"),
            ], mt_counter,
        ))
        cat3, cat4 = categories_sample[8]["source_clean"], categories_sample[9]["source_clean"] if len(categories_sample) > 9 else categories_sample[8]["source_clean"]
        brand2 = brands_sample[1]["source_clean"] if len(brands_sample) > 1 else brand1
        multi_turn_results.append(run_multi_turn_conversation(
            "second fresh-entity conversation",
            [
                ("t1_initial_search", cat3),
                ("t2_add_price", "under 150" if not is_arabic(cat3) else "تحت 150"),
                ("t3_change_price", "actually under 300" if not is_arabic(cat3) else "لا خليه تحت 300"),
                ("t4_add_brand", f"from {brand2}" if not is_arabic(cat3) else f"من {brand2}"),
            ], mt_counter,
        ))
    results["multi_turn_results"] = multi_turn_results

    log("=== Semantic operator (free-from) coverage ===")
    free_from_results = eval_free_from_coverage(manifest["free_from_category_coverage"])
    results["free_from_coverage"] = free_from_results
    log(f"  {len(free_from_results)} distinct free-from categories tested "
        f"(small, honest sample size -- catalog reality, not statistical generalization)")

    out_path = ROOT / "evaluation" / "sprint6_holdout_results.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"Results written to {out_path}")


if __name__ == "__main__":
    main()
