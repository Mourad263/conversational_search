"""Sprint 0: category canonicalization, generate step (research.md §5).

Reads `category` from Postgres, produces
category_canonicalization_review.csv. Writes NOTHING to the database --
category_canonicalization_apply.py is the only script that does that, and
only after a human fills in `reviewer_decision`.
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import psycopg  # noqa: E402
from rapidfuzz import fuzz  # noqa: E402

from src.ingestion.text_normalize import normalize_category_name  # noqa: E402
from src.models.config import settings  # noqa: E402

JUNK_RE = re.compile(r"^test\d*$")
FUZZY_CUTOFF = 85
OUTPUT_PATH = Path(__file__).resolve().parents[2] / "specs" / "001-conversational-search-baseline" / "category_canonicalization_review.csv"


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def fetch_categories() -> list[dict]:
    url = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT c.id, c.name_en, c.name_ar, c.parent_category_id,
                   COUNT(pc.product_id) AS linked_product_count
            FROM category c
            LEFT JOIN product_category pc ON pc.category_id = c.id
            GROUP BY c.id, c.name_en, c.name_ar, c.parent_category_id
            ORDER BY c.id
        """)
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def complete_linkage_cluster(ids: list[int], score: dict[tuple[int, int], float], cutoff: float) -> list[list[int]]:
    """Agglomerative clustering with COMPLETE linkage: two clusters may only
    merge if every cross-pair between them scores >= cutoff. This is
    deliberately not union-find/single-linkage -- single-linkage lets one
    weak pairwise match chain unrelated items together transitively (e.g.
    'Cleaning' ~ 'Cleaning Supplies' ~ ... ~ 'Milk' ~ 'Coffee'), which is
    exactly the failure mode research.md §5 flags as unacceptable for
    category grouping.
    """
    def pair_score(a: int, b: int) -> float:
        return score.get((a, b)) if a < b else score.get((b, a))

    clusters: list[list[int]] = [[i] for i in ids]
    while True:
        best_pair = None
        best_score = -1.0
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                cross_scores = [pair_score(a, b) for a in clusters[i] for b in clusters[j]]
                min_cross = min(cross_scores)
                if min_cross >= cutoff and min_cross > best_score:
                    best_score = min_cross
                    best_pair = (i, j)
        if best_pair is None:
            break
        i, j = best_pair
        clusters[i] = clusters[i] + clusters[j]
        del clusters[j]
    return clusters


def main() -> None:
    categories = fetch_categories()
    for c in categories:
        c["normalized_name_en"] = normalize_category_name(c["name_en"])

    rows: dict[int, dict] = {c["id"]: {**c, "method": None, "group_id": None,
                                        "confidence": None, "needs_review": False,
                                        "notes": ""} for c in categories}

    # Step 2: junk exclusion
    junk_ids = {c["id"] for c in categories if JUNK_RE.match(c["normalized_name_en"])}
    for cid in junk_ids:
        rows[cid]["method"] = "junk_excluded"
        rows[cid]["needs_review"] = True

    remaining = [c for c in categories if c["id"] not in junk_ids]

    # Step 3: exact-duplicate auto-merge
    by_norm: dict[str, list[dict]] = {}
    for c in remaining:
        by_norm.setdefault(c["normalized_name_en"], []).append(c)

    exact_merged_ids: set[int] = set()
    group_counter = 0
    for norm, group in by_norm.items():
        if len(group) > 1:
            group_counter += 1
            rep = max(group, key=lambda c: (c["linked_product_count"], -c["id"]))
            for c in group:
                rows[c["id"]]["method"] = "exact_auto_merge"
                rows[c["id"]]["group_id"] = f"g{group_counter}"
                rows[c["id"]]["confidence"] = 100.0
                rows[c["id"]]["proposed_canonical_slug"] = slugify(rep["name_en"])
                rows[c["id"]]["proposed_canonical_display_en"] = rep["name_en"]
                rows[c["id"]]["proposed_canonical_display_ar"] = rep["name_ar"]
                exact_merged_ids.add(c["id"])

    # Step 4: fuzzy near-duplicate detection over remaining singletons only
    singletons = [c for c in remaining if c["id"] not in exact_merged_ids]
    by_id = {c["id"]: c for c in singletons}
    parent_signal_available = any(c["parent_category_id"] is not None for c in singletons)

    # token_sort_ratio only -- WRatio was tried and rejected: its partial-ratio
    # component scores unrelated categories that merely share a common word
    # (e.g. "Beauty & Personal Care" / "Pet Care", "Dog Food" / "Sea Food
    # Deals") as high as 85+, which flooded the review CSV with false
    # positives and buried the real near-duplicates in noise.
    pair_scores: dict[tuple[int, int], float] = {}
    for i, a in enumerate(singletons):
        for b in singletons[i + 1:]:
            score = fuzz.token_sort_ratio(a["normalized_name_en"], b["normalized_name_en"])
            key = (a["id"], b["id"]) if a["id"] < b["id"] else (b["id"], a["id"])
            pair_scores[key] = score

    clusters = complete_linkage_cluster([c["id"] for c in singletons], pair_scores, FUZZY_CUTOFF)
    fuzzy_groups: dict[int, list[dict]] = {
        cluster[0]: [by_id[cid] for cid in cluster] for cluster in clusters
    }

    for root, group in fuzzy_groups.items():
        if len(group) > 1:
            group_counter += 1
            rep = max(group, key=lambda c: (c["linked_product_count"], -c["id"]))
            min_conf = min(
                fuzz.token_sort_ratio(m["normalized_name_en"], rep["normalized_name_en"])
                for m in group
            )
            for c in group:
                rows[c["id"]]["method"] = "fuzzy_candidate"
                rows[c["id"]]["group_id"] = f"g{group_counter}"
                rows[c["id"]]["confidence"] = round(min_conf, 1)
                rows[c["id"]]["proposed_canonical_slug"] = slugify(rep["name_en"])
                rows[c["id"]]["proposed_canonical_display_en"] = rep["name_en"]
                rows[c["id"]]["proposed_canonical_display_ar"] = rep["name_ar"]
                rows[c["id"]]["needs_review"] = True
        else:
            c = group[0]
            rows[c["id"]]["method"] = "singleton_unique"
            rows[c["id"]]["confidence"] = 100.0
            rows[c["id"]]["proposed_canonical_slug"] = slugify(c["name_en"])
            rows[c["id"]]["proposed_canonical_display_en"] = c["name_en"]
            rows[c["id"]]["proposed_canonical_display_ar"] = c["name_ar"]

    if not parent_signal_available:
        for c in singletons:
            rows[c["id"]]["notes"] = "no parent-category signal available (parent_category_id NULL for all rows)"

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "raw_category_id", "raw_name_en", "raw_name_ar", "parent_category_id",
        "linked_product_count", "normalized_name_en", "method", "group_id",
        "proposed_canonical_slug", "proposed_canonical_display_en",
        "proposed_canonical_display_ar", "confidence", "needs_review",
        "reviewer_decision", "notes",
    ]
    with OUTPUT_PATH.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for c in sorted(categories, key=lambda c: c["id"]):
            r = rows[c["id"]]
            writer.writerow({
                "raw_category_id": c["id"],
                "raw_name_en": c["name_en"],
                "raw_name_ar": c["name_ar"],
                "parent_category_id": c["parent_category_id"] or "",
                "linked_product_count": c["linked_product_count"],
                "normalized_name_en": c["normalized_name_en"],
                "method": r["method"],
                "group_id": r.get("group_id") or "",
                "proposed_canonical_slug": r.get("proposed_canonical_slug") or "",
                "proposed_canonical_display_en": r.get("proposed_canonical_display_en") or "",
                "proposed_canonical_display_ar": r.get("proposed_canonical_display_ar") or "",
                "confidence": r.get("confidence") or "",
                "needs_review": r["needs_review"],
                "reviewer_decision": "",
                "notes": r.get("notes", ""),
            })

    method_counts: dict[str, int] = {}
    for r in rows.values():
        method_counts[r["method"]] = method_counts.get(r["method"], 0) + 1

    print(f"Wrote {OUTPUT_PATH}")
    print(f"Total raw categories: {len(categories)}")
    for method, count in sorted(method_counts.items()):
        print(f"  {method}: {count}")
    n_review = sum(1 for r in rows.values() if r["needs_review"])
    print(f"Rows needing human review: {n_review}")


if __name__ == "__main__":
    main()
