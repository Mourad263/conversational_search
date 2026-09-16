"""Sprint 0: brand canonicalization, generate step (research.md §6).

Reads product.brand_raw_en/brand_raw_ar from Postgres, produces
brand_canonicalization_review.csv. Writes NOTHING to the database --
brand_normalization_apply.py is the only script that does that.
"""

from __future__ import annotations

import csv
import hashlib
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import psycopg  # noqa: E402
from rapidfuzz import fuzz  # noqa: E402

from src.ingestion.category_canonicalization import complete_linkage_cluster  # noqa: E402
from src.ingestion.text_normalize import is_arabic, normalize_arabic, normalize_latin  # noqa: E402
from src.models.config import settings  # noqa: E402

EXACT_CUTOFF = 100
FUZZY_CUTOFF = 90
AUTO_ACCEPT_CUTOFF = 97
OUTPUT_PATH = Path(__file__).resolve().parents[2] / "specs" / "001-conversational-search-baseline" / "brand_canonicalization_review.csv"

# Placeholder/junk brand values -- mirrors category's `^test\d*$` junk rule
# (research.md §5), but brand junk isn't a single clean pattern the way
# "test1"/"test2" is, so this is a denylist of word-bounded phrases rather
# than one regex. Found via a deliberate, broad search of the real data
# (EN+AR placeholder keywords, punctuation-only values, very short values)
# before writing this list -- not guessed. Confirmed hit: "Please select a
# brand." (15 products). Confirmed NOT junk despite short length: LG, Fa,
# V8 and similar 2-letter brand codes -- real brands, left alone.
_JUNK_BRAND_EN_RE = re.compile(
    r"\b(select|please|none|null|undefined|test|tbd|default|sample|"
    r"placeholder|choose|unbranded|misc|n/?a|not specified|not applicable)\b",
    re.IGNORECASE,
)
_JUNK_BRAND_AR_RE = re.compile(r"(اختر|يرجى|غير محدد|بدون)")


def is_junk_brand(raw_value: str) -> bool:
    return bool(_JUNK_BRAND_EN_RE.search(raw_value) or _JUNK_BRAND_AR_RE.search(raw_value))


def slugify(text: str) -> str:
    """Internal DB key (also what ends up in product.brand_normalized, so
    it should be readable, not just unique) -- ASCII slugify() strips
    Arabic entirely, which would collapse every Arabic brand's slug down
    to the same empty-fallback string and silently merge hundreds of
    distinct brands via the apply step's ON CONFLICT upsert. Fall back to
    the normalized Arabic text itself (readable, and distinct per brand)
    for anything that slugifies to empty -- a hash was tried here before
    and found to be a real, user-facing readability bug (research.md):
    canonical values like "brand_ef2ef07c4e" for a real brand.
    """
    ascii_slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    if ascii_slug:
        return ascii_slug
    return normalize_arabic(text) if is_arabic(text) else \
        "brand_" + hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def fetch_brand_values() -> dict[str, int]:
    """raw brand string -> number of products it appears on (either language column)."""
    url = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
    counts: dict[str, int] = defaultdict(int)
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute("SELECT brand_raw_en, brand_raw_ar FROM product")
        for brand_en, brand_ar in cur.fetchall():
            if brand_en:
                counts[brand_en] += 1
            if brand_ar:
                counts[brand_ar] += 1
    return counts


def main() -> None:
    raw_counts = fetch_brand_values()
    print(f"Distinct raw brand strings: {len(raw_counts)}")

    entries = []
    for raw, count in raw_counts.items():
        script = "arabic" if is_arabic(raw) else "latin"
        normalized = normalize_arabic(raw) if script == "arabic" else normalize_latin(raw)
        entries.append({"raw_value": raw, "script": script, "normalized_value": normalized,
                         "product_count": count})

    by_script: dict[str, list[dict]] = defaultdict(list)
    for e in entries:
        by_script[e["script"]].append(e)
    print(f"  latin: {len(by_script['latin'])}  arabic: {len(by_script['arabic'])}")

    rows: dict[str, dict] = {e["raw_value"]: {**e, "method": None, "cluster_id": None,
                                               "confidence": None, "needs_review": False,
                                               "notes": ""} for e in entries}

    junk_values = {e["raw_value"] for e in entries if is_junk_brand(e["raw_value"])}
    for raw in junk_values:
        rows[raw]["method"] = "junk_excluded"
        rows[raw]["needs_review"] = True
    print(f"  junk-excluded: {len(junk_values)} ({sorted(junk_values)})")

    by_script: dict[str, list[dict]] = {
        script: [e for e in script_entries if e["raw_value"] not in junk_values]
        for script, script_entries in by_script.items()
    }

    cluster_counter = 0
    for script, script_entries in by_script.items():
        # Step 4: exact-normalized auto-merge
        by_norm: dict[str, list[dict]] = defaultdict(list)
        for e in script_entries:
            by_norm[e["normalized_value"]].append(e)

        exact_merged: set[str] = set()
        for norm, group in by_norm.items():
            if len(group) > 1:
                cluster_counter += 1
                rep = max(group, key=lambda e: e["product_count"])
                for e in group:
                    rows[e["raw_value"]]["method"] = "exact_normalized"
                    rows[e["raw_value"]]["cluster_id"] = f"c{cluster_counter}"
                    rows[e["raw_value"]]["confidence"] = 100.0
                    rows[e["raw_value"]]["proposed_canonical_slug"] = slugify(rep["raw_value"])
                    rows[e["raw_value"]]["proposed_canonical_display"] = rep["raw_value"]
                    exact_merged.add(e["raw_value"])

        # Step 5: fuzzy clustering over remaining distinct normalized strings, within script
        remaining = [e for e in script_entries if e["raw_value"] not in exact_merged]
        # dedupe by normalized_value for the fuzzy pass (exact dupes already handled)
        seen_norms: dict[str, dict] = {}
        for e in remaining:
            seen_norms.setdefault(e["normalized_value"], e)
        uniq = list(seen_norms.values())

        pair_scores: dict[tuple[str, str], float] = {}
        for i, a in enumerate(uniq):
            for b in uniq[i + 1:]:
                score = fuzz.token_sort_ratio(a["normalized_value"], b["normalized_value"])
                key = tuple(sorted((a["normalized_value"], b["normalized_value"])))
                pair_scores[key] = score

        def pscore(a: str, b: str) -> float:
            return pair_scores[tuple(sorted((a, b)))]

        clusters = complete_linkage_cluster(
            list(range(len(uniq))),
            {tuple(sorted((i, j))): pscore(uniq[i]["normalized_value"], uniq[j]["normalized_value"])
             for i in range(len(uniq)) for j in range(i + 1, len(uniq))},
            FUZZY_CUTOFF,
        )

        for cluster_idx in clusters:
            cluster_entries_norm = [uniq[i] for i in cluster_idx]
            # expand back to all raw values sharing these normalized forms
            cluster_raw: list[dict] = []
            for ce in cluster_entries_norm:
                cluster_raw.extend(by_norm[ce["normalized_value"]])
            if len(cluster_entries_norm) == 1:
                e = cluster_entries_norm[0]
                for raw_e in by_norm[e["normalized_value"]]:
                    if raw_e["raw_value"] in exact_merged:
                        continue
                    rows[raw_e["raw_value"]]["method"] = "singleton"
                    rows[raw_e["raw_value"]]["confidence"] = 100.0
                    rows[raw_e["raw_value"]]["proposed_canonical_slug"] = slugify(raw_e["raw_value"])
                    rows[raw_e["raw_value"]]["proposed_canonical_display"] = raw_e["raw_value"]
                continue

            cluster_counter += 1
            rep = max(cluster_raw, key=lambda e: e["product_count"])
            min_conf = min(
                pscore(a["normalized_value"], b["normalized_value"])
                for idx_a, a in enumerate(cluster_entries_norm)
                for b in cluster_entries_norm[idx_a + 1:]
            )
            for raw_e in cluster_raw:
                if raw_e["raw_value"] in exact_merged:
                    continue
                rows[raw_e["raw_value"]]["method"] = "fuzzy_cluster"
                rows[raw_e["raw_value"]]["cluster_id"] = f"c{cluster_counter}"
                rows[raw_e["raw_value"]]["confidence"] = round(min_conf, 1)
                rows[raw_e["raw_value"]]["proposed_canonical_slug"] = slugify(rep["raw_value"])
                rows[raw_e["raw_value"]]["proposed_canonical_display"] = rep["raw_value"]
                # Step 6: differentiated review gate
                rows[raw_e["raw_value"]]["needs_review"] = min_conf < AUTO_ACCEPT_CUTOFF

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "raw_brand_value", "script", "product_count", "normalized_value", "method",
        "cluster_id", "proposed_canonical_slug", "proposed_canonical_display",
        "cluster_min_confidence", "needs_review", "reviewer_decision", "notes",
    ]
    with OUTPUT_PATH.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for raw_value, r in sorted(rows.items(), key=lambda kv: (-kv[1]["product_count"], kv[0])):
            writer.writerow({
                "raw_brand_value": raw_value,
                "script": r["script"],
                "product_count": r["product_count"],
                "normalized_value": r["normalized_value"],
                "method": r["method"],
                "cluster_id": r.get("cluster_id") or "",
                "proposed_canonical_slug": r.get("proposed_canonical_slug") or "",
                "proposed_canonical_display": r.get("proposed_canonical_display") or "",
                "cluster_min_confidence": r.get("confidence") or "",
                "needs_review": r["needs_review"],
                "reviewer_decision": "",
                "notes": r.get("notes", ""),
            })

    method_counts: dict[str, int] = defaultdict(int)
    for r in rows.values():
        method_counts[r["method"]] += 1
    n_review = sum(1 for r in rows.values() if r["needs_review"])

    print(f"Wrote {OUTPUT_PATH}")
    print(f"Total distinct raw brand strings: {len(rows)}")
    for method, count in sorted(method_counts.items()):
        print(f"  {method}: {count}")
    print(f"Rows needing human review (90-{AUTO_ACCEPT_CUTOFF - 0.1} confidence band): {n_review}")


if __name__ == "__main__":
    main()
