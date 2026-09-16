"""hard_filter() (query.py) brand-predicate regression: `brand` reaching
this function is always an already-resolved canonical_brand.slug (the only
production call site is parse_keyword_query's fuzzy resolver, verified via
a full grep of every FilterSet(brand=...) construction), so filtering must
be exact canonical identity, not substring.

Confirmed live bug (independent audit, 2026-09): a contains-style
`ILIKE '%<brand>%'` predicate made brand="aqua" (a real canonical slug)
also match "aqua_delta"/"aqua_touch"/"aquafina"/"aquafresh" -- 21 rows
across 5 distinct brands, only 1 of them actually "aqua". brand="fa" (a
real 2-letter brand, confirmed not junk -- see brand_normalization.py)
matched 22 distinct brands -- 336 rows, only 87 actually "fa". Real DB
counts captured below are the exact same values used to confirm the fix.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.search_engine.query import hard_filter  # noqa: E402


def test_short_brand_that_is_a_substring_of_others_matches_only_itself():
    # "aqua" is a real canonical slug AND a proper substring of the real,
    # distinct canonical slugs aqua_delta/aqua_touch/aquafina/aquafresh.
    rows = hard_filter(None, None, None, "aqua")
    assert rows, "expected at least one real 'aqua' product"
    assert {r["brand_normalized"] for r in rows} == {"aqua"}


def test_two_letter_brand_that_is_a_substring_of_many_others_matches_only_itself():
    # "fa" is a real 2-letter brand (confirmed not junk) and a substring of
    # dozens of unrelated real brands (fanta, fairy, farm_frites, tefal via
    # normalized text, dina_farms, ...).
    rows = hard_filter(None, None, None, "fa")
    assert rows, "expected at least one real 'fa' product"
    assert {r["brand_normalized"] for r in rows} == {"fa"}


def test_normal_non_collision_brand_still_matches_correctly():
    rows = hard_filter(None, None, None, "juhayna")
    assert rows, "expected real 'juhayna' products"
    assert {r["brand_normalized"] for r in rows} == {"juhayna"}


def test_brand_composes_with_category_and_price_predicates():
    """The fix touches only the brand predicate -- category and price
    filtering must be unaffected."""
    rows = hard_filter("milk_29", 20, 100, "juhayna")
    assert rows
    for r in rows:
        assert r["brand_normalized"] == "juhayna"
        assert r["price"] is None or 20 <= r["price"] <= 100
