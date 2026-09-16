"""One-off: apply the reviewer decisions from the chat conversation into the
two review CSVs, so the apply scripts have real reviewer_decision values to
read rather than requiring interactive CSV editing.
"""
import csv
from pathlib import Path

SPECS = Path(__file__).resolve().parents[2] / "specs" / "001-conversational-search-baseline"

cat_path = SPECS / "category_canonicalization_review.csv"
with cat_path.open(encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))
fieldnames = list(rows[0].keys())

CAT_DECISIONS = {
    # Frozen Meat / Frozen Meats -- verified identical product lists+prices -> merge
    "40304": "approve",
    "40305": "approve",
    # Home Accessories / SHOE ACCESSORIES -- verified different (tools/batteries vs shoe care) -> keep separate
    "13": "reject",
    "27951": "reject",
    # fresh pickles / Fresh spices -- verified different (pickled goods vs bulk spices) -> keep separate
    "1758": "reject",
    "3276": "reject",
    # junk rows -- confirmed genuinely junk on inspection
    "1734": "approve",
    "29277": "approve",
    "43822": "approve",
    "50991": "approve",
    "59796": "approve",
}
for r in rows:
    if r["raw_category_id"] in CAT_DECISIONS:
        r["reviewer_decision"] = CAT_DECISIONS[r["raw_category_id"]]

with cat_path.open("w", newline="", encoding="utf-8-sig") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
print(f"Updated {cat_path}")

brand_path = SPECS / "brand_canonicalization_review.csv"
with brand_path.open(encoding="utf-8-sig") as f:
    brows = list(csv.DictReader(f))
bfieldnames = list(brows[0].keys())

REJECT_BRANDS = {"Green Life", "Live Green"}
n_approved = 0
n_rejected = 0
n_junk_confirmed = 0
for r in brows:
    if r["method"] == "fuzzy_cluster":
        if r["raw_brand_value"] in REJECT_BRANDS:
            r["reviewer_decision"] = "reject"
            n_rejected += 1
        else:
            r["reviewer_decision"] = "approve"
            n_approved += 1
    elif r["method"] == "junk_excluded":
        # Confirmed via a deliberate, broad search of the real data (EN+AR
        # placeholder keywords, punctuation-only values, short values) --
        # "Please select a brand." was the only genuine hit.
        r["reviewer_decision"] = "approve"
        n_junk_confirmed += 1

with brand_path.open("w", newline="", encoding="utf-8-sig") as f:
    writer = csv.DictWriter(f, fieldnames=bfieldnames)
    writer.writeheader()
    writer.writerows(brows)
print(f"Updated {brand_path} ({n_approved} approved, {n_rejected} rejected, "
      f"{n_junk_confirmed} junk confirmed)")
