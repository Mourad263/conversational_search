"""Content-based recommendation clustering experiment -- ANALYSIS ONLY.
Evaluation artifact; nothing under src/ is touched, no embeddings are
retrained, no LLM/API calls, search behavior unchanged.

Reuses the EXISTING normalized product_embeddings (pgvector, 768-d,
ibm-granite/granite-embedding-278m-multilingual) and the existing local
`embed()` function (CPU sentence-transformers, no external API) for the
query-embedding comparison in section 7.

Tests whether MiniBatchKMeans clustering of those embeddings is a useful
candidate-generation signal for a future content-based recommender. The
clustering model is a SIGNAL only -- section 8 documents where hard
filters must still be enforced; this script does not enforce them at
runtime because it does not run at runtime.

Usage: python evaluation/recommendation_cluster_experiment.py
Writes: evaluation/recommendation_cluster_results.json
        evaluation/artifacts/product_kmeans_<k>.joblib
"""

from __future__ import annotations

import json
import sys
import time
import tracemalloc
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import psycopg  # noqa: E402
from pgvector.psycopg import register_vector  # noqa: E402
from sklearn.cluster import MiniBatchKMeans  # noqa: E402

from src.models.config import settings  # noqa: E402
from src.search_engine.embeddings import embed  # noqa: E402
from src.search_engine.keyword_baseline import resolve_category_hint  # noqa: E402
from src.search_engine.query import hard_filter  # noqa: E402

K_VALUES = [64, 128, 256]
RANDOM_STATE = 42
QUALITATIVE_K = 128  # the one k we dump representative clusters/examples for
N_SAMPLE_CLUSTERS = 6
N_REPRESENTATIVES = 10
EVAL_QUERIES = ["milk", "lactose-free milk", "yogurt", "olive oil", "chocolate", "shampoo", "detergent"]


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def load_products() -> dict:
    url = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url) as conn:
        register_vector(conn)
        cur = conn.cursor()
        cur.execute("""
            SELECT p.id, p.name_en, p.brand_normalized, pe.embedding
            FROM product p
            JOIN product_embeddings pe ON pe.product_id = p.id
            ORDER BY p.id
        """)
        rows = cur.fetchall()
        cur.execute("""
            SELECT DISTINCT ON (pcx.product_id) pcx.product_id, cc.slug
            FROM product_category pcx
            JOIN category c ON c.id = pcx.category_id
            JOIN canonical_category cc ON cc.id = c.canonical_category_id
            ORDER BY pcx.product_id, cc.slug
        """)
        category_by_pid = dict(cur.fetchall())

    pids = np.array([r[0] for r in rows], dtype=np.int64)
    names = [r[1] for r in rows]
    brands = [r[2] for r in rows]
    categories = [category_by_pid.get(r[0]) for r in rows]
    embeddings = np.array([r[3].to_numpy() for r in rows], dtype=np.float32)
    return {"pids": pids, "names": names, "brands": brands, "categories": categories, "embeddings": embeddings}


def cluster_size_stats(labels: np.ndarray, k: int) -> dict:
    counts = np.bincount(labels, minlength=k)
    return {
        "min": int(counts.min()), "median": float(np.median(counts)),
        "mean": round(float(counts.mean()), 2), "max": int(counts.max()),
        "empty_clusters": int((counts == 0).sum()),
    }


def category_diagnostics(labels: np.ndarray, categories: list, k: int) -> dict:
    purities = []
    cats_per_cluster = []
    for c in range(k):
        idx = np.where(labels == c)[0]
        if len(idx) == 0:
            continue
        cluster_cats = [categories[i] for i in idx if categories[i] is not None]
        if not cluster_cats:
            continue
        from collections import Counter
        counts = Counter(cluster_cats)
        dominant_pct = counts.most_common(1)[0][1] / len(cluster_cats)
        purities.append(dominant_pct)
        cats_per_cluster.append(len(counts))
    return {
        "avg_dominant_category_pct": round(float(np.mean(purities)), 4) if purities else None,
        "avg_categories_per_cluster": round(float(np.mean(cats_per_cluster)), 2) if cats_per_cluster else None,
        "clusters_with_category_data": len(purities),
    }


def representative_products(model, data: dict, labels: np.ndarray, k: int,
                              n_clusters: int, n_products: int) -> list:
    rng = np.random.RandomState(RANDOM_STATE)
    sample_clusters = rng.choice(k, size=min(n_clusters, k), replace=False)
    out = []
    for c in sorted(sample_clusters):
        idx = np.where(labels == c)[0]
        if len(idx) == 0:
            continue
        centroid = model.cluster_centers_[c]
        emb = data["embeddings"][idx]
        dists = np.linalg.norm(emb - centroid, axis=1)
        nearest = idx[np.argsort(dists)[:n_products]]
        out.append({
            "cluster_id": int(c), "cluster_size": int(len(idx)),
            "representative_products": [
                {"product_id": int(data["pids"][i]), "name": data["names"][i],
                 "brand": data["brands"][i], "category": data["categories"][i]}
                for i in nearest
            ],
        })
    return out


def run_kmeans(embeddings: np.ndarray, k: int) -> dict:
    tracemalloc.start()
    t0 = time.perf_counter()
    model = MiniBatchKMeans(n_clusters=k, random_state=RANDOM_STATE, n_init=3, batch_size=1024)
    labels = model.fit_predict(embeddings)
    fit_time = time.perf_counter() - t0
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {"model": model, "labels": labels, "fit_time_s": round(fit_time, 2),
            "peak_python_memory_mb": round(peak / 1e6, 1)}


def cosine_sim(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    # embeddings are already normalized (project convention), but the
    # profile/query vectors built here are re-normalized explicitly to be safe.
    return b @ a


def build_search_result_group(query_word: str, data: dict, pid_to_idx: dict, limit: int = 8) -> dict | None:
    slug = resolve_category_hint(query_word)
    if slug is None:
        return None
    rows = hard_filter(slug, None, None, None)[:limit]
    idxs = [pid_to_idx[r["id"]] for r in rows if r["id"] in pid_to_idx]
    if not idxs:
        return None
    return {"query": query_word, "category_slug": slug, "product_ids": [int(data["pids"][i]) for i in idxs],
            "names": [data["names"][i] for i in idxs], "idxs": idxs}


def recommend(group: dict, data: dict, labels: np.ndarray, mode: str, top_n: int = 8) -> list:
    idxs = group["idxs"]
    profile = data["embeddings"][idxs].mean(axis=0)
    profile = profile / (np.linalg.norm(profile) + 1e-9)

    if mode in ("query", "combined"):
        query_vec = np.array(embed(group["query"]), dtype=np.float32)
        query_vec = query_vec / (np.linalg.norm(query_vec) + 1e-9)
    if mode == "profile":
        target = profile
    elif mode == "query":
        target = query_vec
    else:  # combined -- simple illustrative 0.5/0.5 blend, NOT a tuned production weight
        target = profile + query_vec
        target = target / (np.linalg.norm(target) + 1e-9)

    represented_clusters = set(labels[i] for i in idxs)
    candidate_idx = np.where(np.isin(labels, list(represented_clusters)))[0]
    candidate_idx = np.array([i for i in candidate_idx if i not in set(idxs)])
    if len(candidate_idx) == 0:
        return []

    sims = cosine_sim(target, data["embeddings"][candidate_idx])
    order = np.argsort(-sims)[:top_n]
    return [
        {"product_id": int(data["pids"][candidate_idx[o]]), "name": data["names"][candidate_idx[o]],
         "category": data["categories"][candidate_idx[o]], "similarity": round(float(sims[o]), 4)}
        for o in order
    ]


def main() -> None:
    log("Loading products + existing embeddings from Postgres...")
    t0 = time.perf_counter()
    data = load_products()
    log(f"Loaded {len(data['pids'])} products with embeddings in {time.perf_counter() - t0:.1f}s "
        f"(shape={data['embeddings'].shape}).")
    pid_to_idx = {int(pid): i for i, pid in enumerate(data["pids"])}

    artifacts_dir = ROOT / "evaluation" / "artifacts"
    artifacts_dir.mkdir(exist_ok=True)

    k_results = {}
    labels_by_k = {}
    model_by_k = {}
    for k in K_VALUES:
        log(f"Fitting MiniBatchKMeans k={k}...")
        r = run_kmeans(data["embeddings"], k)
        size_stats = cluster_size_stats(r["labels"], k)
        cat_diag = category_diagnostics(r["labels"], data["categories"], k)
        k_results[k] = {
            "k": k, "fit_time_s": r["fit_time_s"], "peak_python_memory_mb": r["peak_python_memory_mb"],
            "cluster_sizes": size_stats, "category_diagnostics": cat_diag,
        }
        labels_by_k[k] = r["labels"]
        model_by_k[k] = r["model"]
        import joblib
        joblib.dump(r["model"], artifacts_dir / f"product_kmeans_{k}.joblib")
        log(f"  k={k}: fit={r['fit_time_s']}s, sizes={size_stats}, category={cat_diag}")

    log(f"Qualitative cluster inspection at k={QUALITATIVE_K}...")
    qualitative = representative_products(
        model_by_k[QUALITATIVE_K], data, labels_by_k[QUALITATIVE_K],
        QUALITATIVE_K, N_SAMPLE_CLUSTERS, N_REPRESENTATIVES,
    )

    log("Building search-result groups from real catalog queries (read-only, no API)...")
    groups = []
    for q in EVAL_QUERIES:
        g = build_search_result_group(q, data, pid_to_idx)
        if g:
            groups.append(g)
    log(f"  {len(groups)}/{len(EVAL_QUERIES)} evaluation queries resolved to real category products.")

    recommendation_examples = []
    for g in groups:
        labels = labels_by_k[QUALITATIVE_K]
        idxs = g["idxs"]
        represented = sorted(set(int(labels[i]) for i in idxs))
        rec_profile = recommend(g, data, labels, "profile")
        rec_query = recommend(g, data, labels, "query")
        rec_combined = recommend(g, data, labels, "combined")
        recommendation_examples.append({
            "query": g["query"], "category_slug": g["category_slug"],
            "original_products": [{"product_id": pid, "name": n} for pid, n in zip(g["product_ids"], g["names"])],
            "represented_cluster_ids": represented,
            "recommend_profile_only": rec_profile,
            "recommend_query_only": rec_query,
            "recommend_combined": rec_combined,
        })

    out = {
        "n_products": int(len(data["pids"])),
        "k_metrics": k_results,
        "qualitative_clusters_k": QUALITATIVE_K,
        "qualitative_clusters": qualitative,
        "recommendation_examples": recommendation_examples,
    }
    (ROOT / "evaluation" / "recommendation_cluster_results.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    log("Wrote evaluation/recommendation_cluster_results.json")
    log(json.dumps({k: v["cluster_sizes"] | v["category_diagnostics"] for k, v in k_results.items()}, indent=2))


if __name__ == "__main__":
    main()
