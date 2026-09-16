"""Filtered K=128 recommendation PROTOTYPE -- evaluation/experiment code
only, not wired into the API or src/. Reuses:
  - the FROZEN k=128 artifact from the offline clustering experiment
    (evaluation/artifacts/product_kmeans_128.joblib, NOT retrained here)
  - the project's real FilterSet type (src.search_adapter.adapter)
  - the project's real hard_filter() (src.search_engine.query) as the
    ONLY authoritative filter-enforcement logic -- not reimplemented
  - the project's real validate() (src.validation.validate) to build each
    test case's active FilterSet exactly as production would, without a
    Groq/LLM call (Action objects are hand-constructed with the semantic
    roles a correct LLM call would have produced -- same technique used
    throughout this project's evaluation scripts)
  - the existing local embed() (CPU sentence-transformers, no API)

No embeddings retrained, no KMeans retrained, no production files changed.

Usage: python evaluation/recommendation_filtered_prototype.py
Writes: evaluation/recommendation_filtered_results.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import joblib  # noqa: E402
import numpy as np  # noqa: E402
import psycopg  # noqa: E402
from pgvector.psycopg import register_vector  # noqa: E402

from src.models.config import settings  # noqa: E402
from src.search_adapter.adapter import FilterSet  # noqa: E402
from src.search_engine.embeddings import embed  # noqa: E402
from src.search_engine.query import hard_filter  # noqa: E402
from src.understanding.schema import Action, Intent  # noqa: E402
from src.validation.validate import validate  # noqa: E402

KMEANS_PATH = ROOT / "evaluation" / "artifacts" / "product_kmeans_128.joblib"

# Prototype ranking weights -- NOT claimed optimal, kept in one place so a
# later evaluation pass can sweep them. Query similarity and result-profile
# similarity are combined by a simple weighted sum (both cosine sims live
# in [-1, 1] on unit-normalized vectors, so a linear blend is a reasonable
# starting point, not a tuned formula).
WEIGHT_QUERY = 0.5
WEIGHT_PROFILE = 0.5


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def load_catalog_embeddings() -> dict:
    """Every product id with a real embedding, loaded once. Read-only."""
    url = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url) as conn:
        register_vector(conn)
        cur = conn.cursor()
        cur.execute("SELECT product_id, embedding FROM product_embeddings ORDER BY product_id")
        rows = cur.fetchall()
    pids = np.array([r[0] for r in rows], dtype=np.int64)
    embeddings = np.array([r[1].to_numpy() for r in rows], dtype=np.float32)
    pid_to_idx = {int(pid): i for i, pid in enumerate(pids)}
    return {"pids": pids, "embeddings": embeddings, "pid_to_idx": pid_to_idx}


def cosine_batch(vec: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    return matrix @ vec  # embeddings are unit-normalized (project convention)


class FilteredRecommender:
    """The prototype interface: recommend(query_text, search_result_ids,
    active_filters, limit). Candidate flow, per the task's required order:
    relevant K=128 clusters -> exclude already-shown -> active hard
    filters (via the real hard_filter()) -> query+profile semantic
    ranking -> top N. Nothing here can override a hard filter: filter
    enforcement happens strictly AFTER cluster candidate generation and
    BEFORE ranking, and ranking only ever reorders what already survived
    the filter intersection."""

    def __init__(self, catalog: dict, kmeans_path: Path = KMEANS_PATH):
        self.catalog = catalog
        self.model = joblib.load(kmeans_path)  # frozen, not retrained
        self.labels = self.model.predict(catalog["embeddings"])  # cheap: reuses the frozen centroids

    def recommend(self, query_text: str | None, search_result_ids: list[int],
                   active_filters: FilterSet, limit: int = 5) -> dict:
        pid_to_idx = self.catalog["pid_to_idx"]
        embeddings = self.catalog["embeddings"]
        pids = self.catalog["pids"]

        shown_idx = [pid_to_idx[pid] for pid in search_result_ids if pid in pid_to_idx]
        if not shown_idx:
            # No usable evidence to build a profile from -- do not invent
            # a recommendation (task rule #2).
            return {"products": [], "reason": "no valid search-result embeddings available",
                     "relevant_clusters": [], "candidates_before_filter": 0, "candidates_after_filter": 0}

        profile = embeddings[shown_idx].mean(axis=0)
        profile = profile / (np.linalg.norm(profile) + 1e-9)

        query_vec = None
        if query_text:
            qv = np.array(embed(query_text), dtype=np.float32)
            query_vec = qv / (np.linalg.norm(qv) + 1e-9)

        relevant_clusters = sorted(set(int(self.labels[i]) for i in shown_idx))
        cluster_mask = np.isin(self.labels, relevant_clusters)
        shown_set = set(shown_idx)
        candidate_idx = np.array([i for i in np.where(cluster_mask)[0] if i not in shown_set])
        candidates_before_filter = int(len(candidate_idx))

        if candidates_before_filter == 0:
            return {"products": [], "reason": "no candidates in the relevant clusters after excluding shown",
                     "relevant_clusters": relevant_clusters, "candidates_before_filter": 0,
                     "candidates_after_filter": 0}

        # CRITICAL: enforce the session's real active hard filters via the
        # project's own authoritative hard_filter() -- never reimplemented,
        # never bypassed. This is also where every returned product's real
        # catalog fields (name/price/brand/sku) come from.
        filtered_rows = hard_filter(active_filters.category, active_filters.price_min,
                                     active_filters.price_max, active_filters.brand)
        filtered_by_id = {row["id"]: row for row in filtered_rows}
        candidate_idx = np.array([i for i in candidate_idx if int(pids[i]) in filtered_by_id])
        candidates_after_filter = int(len(candidate_idx))

        if candidates_after_filter == 0:
            return {"products": [], "reason": "no candidates survive the active hard filters",
                     "relevant_clusters": relevant_clusters,
                     "candidates_before_filter": candidates_before_filter, "candidates_after_filter": 0}

        profile_sims = cosine_batch(profile, embeddings[candidate_idx])
        if query_vec is not None:
            query_sims = cosine_batch(query_vec, embeddings[candidate_idx])
            combined = WEIGHT_QUERY * query_sims + WEIGHT_PROFILE * profile_sims
        else:
            combined = profile_sims

        order = np.argsort(-combined)[:limit]
        chosen_idx = candidate_idx[order]

        products = []
        seen = set()
        for i, score in zip(chosen_idx, combined[order]):
            pid = int(pids[i])
            if pid in seen:  # structurally shouldn't happen (unique indices), defensive only
                continue
            seen.add(pid)
            row = filtered_by_id[pid]
            products.append({
                "product_id": pid, "name": row["name_en"], "brand": row["brand_normalized"],
                "price": float(row["price"]) if row["price"] is not None else None,
                "cluster_id": int(self.labels[i]), "combined_similarity": round(float(score), 4),
            })

        return {"products": products, "reason": None, "relevant_clusters": relevant_clusters,
                "candidates_before_filter": candidates_before_filter,
                "candidates_after_filter": candidates_after_filter}


def action_filters(**kwargs) -> FilterSet:
    action = Action(intent=Intent.SEARCH, **kwargs)
    return validate(action)


def shown_products_for(filters: FilterSet, n: int = 5) -> list[dict]:
    rows = hard_filter(filters.category, filters.price_min, filters.price_max, filters.brand)
    return rows[:n]


def satisfies_filters(pid: int, price: float | None, brand: str | None, filters: FilterSet, filtered_ids: set) -> bool:
    if pid not in filtered_ids:
        return False
    if filters.price_min is not None and (price is None or price < filters.price_min):
        return False
    if filters.price_max is not None and (price is None or price > filters.price_max):
        return False
    if filters.brand is not None and brand != filters.brand:
        return False
    return True


def run_case(rec: FilteredRecommender, label: str, query_text: str, filters: FilterSet, limit: int = 5,
             shown_n: int = 5) -> dict:
    shown = shown_products_for(filters, n=shown_n)
    shown_ids = [r["id"] for r in shown]
    result = rec.recommend(query_text, shown_ids, filters, limit=limit)

    filtered_rows = hard_filter(filters.category, filters.price_min, filters.price_max, filters.brand)
    filtered_ids = {r["id"] for r in filtered_rows}
    all_satisfy = all(
        satisfies_filters(p["product_id"], p["price"], p["brand"], filters, filtered_ids)
        for p in result["products"]
    )
    no_overlap_with_shown = not (set(p["product_id"] for p in result["products"]) & set(shown_ids))
    no_duplicates = len({p["product_id"] for p in result["products"]}) == len(result["products"])

    return {
        "case": label, "query": query_text,
        "active_filters": {"category": filters.category, "brand": filters.brand,
                            "price_min": filters.price_min, "price_max": filters.price_max,
                            "unresolved_exclusion": filters.unresolved_exclusion},
        "shown_products": [{"product_id": r["id"], "name": r["name_en"]} for r in shown],
        "relevant_clusters": result["relevant_clusters"],
        "candidates_before_filter": result["candidates_before_filter"],
        "candidates_after_filter": result["candidates_after_filter"],
        "recommended_products": result["products"],
        "reason_if_empty": result["reason"],
        "all_recommendations_satisfy_active_filters": all_satisfy,
        "no_overlap_with_shown_products": no_overlap_with_shown,
        "no_duplicate_recommendations": no_duplicates,
    }


def main() -> None:
    log("Loading catalog embeddings (read-only)...")
    catalog = load_catalog_embeddings()
    log(f"Loaded {len(catalog['pids'])} product embeddings.")
    log("Loading frozen k=128 KMeans artifact (not retrained)...")
    rec = FilteredRecommender(catalog)

    results = []

    # A/B: milk vs lactose-free milk -- the critical comparison.
    results.append(run_case(rec, "A_milk", "milk",
                             action_filters(raw_query_text="milk", category_hint="milk")))
    results.append(run_case(rec, "B_lactose_free_milk", "lactose-free milk",
                             action_filters(raw_query_text="milk", category_hint="milk", free_from="lactose")))
    # B2: same constraint, fewer "already shown" -- checks whether headroom
    # surfaces a genuine remaining lactose-free product (not regular milk)
    # when one exists, since the catalog only has 3 lactose-free products
    # total and B above showed all of them.
    results.append(run_case(rec, "B2_lactose_free_milk_with_headroom", "lactose-free milk",
                             action_filters(raw_query_text="milk", category_hint="milk", free_from="lactose"),
                             shown_n=2))
    # C-E
    results.append(run_case(rec, "C_yogurt", "yogurt",
                             action_filters(raw_query_text="yogurt", category_hint="yogurt")))
    results.append(run_case(rec, "D_olive_oil", "olive oil",
                             action_filters(raw_query_text="olive oil", category_hint="olive oil")))
    results.append(run_case(rec, "E_detergent", "detergent",
                             action_filters(raw_query_text="detergent", category_hint="detergent")))
    # F: price-constrained
    results.append(run_case(rec, "F_milk_under_30", "milk under 30",
                             action_filters(raw_query_text="milk", category_hint="milk", price_max=30.0)))
    # G: brand-constrained
    results.append(run_case(rec, "G_juhayna_milk", "Juhayna milk",
                             action_filters(raw_query_text="milk", category_hint="milk", brand_text="Juhayna")))

    # Edge cases -----------------------------------------------------------
    # fewer-than-limit eligible: a narrow brand+category slice
    results.append(run_case(rec, "H_edge_narrow_brand_category", "Juhayna yogurt",
                             action_filters(raw_query_text="yogurt", category_hint="yogurt", brand_text="Juhayna"),
                             limit=50))
    # zero eligible candidates: an impossible price range on a real category
    zero_filters = action_filters(raw_query_text="milk", category_hint="milk", price_max=0.01)
    results.append(run_case(rec, "I_edge_zero_candidates", "milk under 0.01", zero_filters))
    # empty search-result input
    empty_filters = action_filters(raw_query_text="milk", category_hint="milk")
    empty_result = rec.recommend("milk", [], empty_filters, limit=5)
    results.append({"case": "J_edge_empty_search_results", "query": "milk", "shown_products": [],
                     "recommended_products": empty_result["products"], "reason_if_empty": empty_result["reason"],
                     "candidates_before_filter": empty_result["candidates_before_filter"],
                     "candidates_after_filter": empty_result["candidates_after_filter"]})

    log(json.dumps({r["case"]: {"n_recommended": len(r["recommended_products"]),
                                  "candidates_after_filter": r.get("candidates_after_filter"),
                                  "reason_if_empty": r.get("reason_if_empty")}
                     for r in results}, indent=2, ensure_ascii=False))

    (ROOT / "evaluation" / "recommendation_filtered_results.json").write_text(
        json.dumps({"weight_query": WEIGHT_QUERY, "weight_profile": WEIGHT_PROFILE, "results": results},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    log("Wrote evaluation/recommendation_filtered_results.json")


if __name__ == "__main__":
    main()
