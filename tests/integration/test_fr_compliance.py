"""Direct spec.md FR -> test mapping for Sprint 1's scope. FR-012 and
FR-014 already have dedicated coverage elsewhere (test_search_engine.py's
zero-result tests; test_keyword_baseline.py / test_api.py for FR-014) --
not duplicated here.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import psycopg  # noqa: E402

from src.models.config import settings  # noqa: E402
from src.search_adapter.adapter import FilterSet, SearchAdapter  # noqa: E402

adapter = SearchAdapter()


def test_fr001_multiple_simultaneous_requirements():
    """FR-001's natural-language UNDERSTANDING is Sprint 2 -- not testable
    here. What IS testable now: the underlying multi-filter mechanism it
    depends on actually combines category+price+brand correctly in one
    call, not just one at a time."""
    result = adapter.search(
        FilterSet(category="chocolate_2", price_max=50, brand="galaxy"), limit=20
    )
    assert result.total_count > 0
    for p in result.products:
        assert float(p["price"]) <= 50
        assert p["brand_normalized"] == "galaxy"


def test_fr011_every_result_independently_verifiable_in_db():
    """No fabrication: every returned product must actually exist in
    Postgres with matching data, checked via a fresh, separate connection
    -- not just trusting the same code path that produced the result."""
    result = adapter.search(FilterSet(query_text="chocolate"), limit=10)
    url = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        for p in result.products:
            cur.execute("SELECT name_en, sku FROM product WHERE id = %s", (p["id"],))
            row = cur.fetchone()
            assert row is not None, f"product id {p['id']} does not exist in Postgres"
            assert row[0] == p["name_en"]
            assert row[1] == p["sku"]


def test_fr019_category_filter_unifies_all_raw_duplicate_records():
    """The 5 raw 'Meat' category records must all contribute to one
    canonical 'meat' filter -- cross-checked against an independent SQL
    count over all 5 raw ids, not just asserted nonzero."""
    url = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT COUNT(DISTINCT pc.product_id)
            FROM product_category pc JOIN category c ON c.id = pc.category_id
            WHERE c.canonical_category_id = (
                SELECT id FROM canonical_category WHERE slug = 'meat'
            )
        """)
        expected = cur.fetchone()[0]

    result = adapter.search(FilterSet(category="meat"), limit=1000)
    assert result.total_count == expected
    assert expected > 0  # sanity: the cross-check itself must be non-trivial


def test_fr020_brand_not_in_catalog_is_not_hard_rejected():
    """A brand with no catalog match must not error, crash, or be treated
    as an invalid request -- it's accepted as a best-effort filter that
    legitimately finds nothing. (This previously also asserted against
    SearchAdapter.validate_filter_value()'s ValidationOutcome.reason --
    removed along with that method, which had no real caller: neither
    keyword_baseline.py nor the API route ever called it. It was built
    speculatively per the original contract doc, ahead of the Sprint 3
    Validation step that doesn't exist yet. FR-020 is fully proven by
    search() itself, below -- no separate validation call needed today.)"""
    result = adapter.search(FilterSet(brand="TotallyMadeUpBrandXYZ123"), limit=5)
    assert result.zero_result
    assert result.products == []


def test_placeholder_brand_value_excluded_not_fabricated_as_a_real_brand():
    """'Please select a brand.' is a literal unfilled dropdown default in
    the source data (verified: 7,505 products -- ~30% of all
    brand-bearing products, not the 15 initially and wrongly reported from
    a filtered slice). It must never surface as if it were a real
    canonical brand (FR-011-adjacent: don't fabricate a brand entity out
    of a data-entry placeholder)."""
    url = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM canonical_brand WHERE display_name ILIKE %s",
            ("%select a brand%",),
        )
        assert cur.fetchone()[0] == 0

        cur.execute("""
            SELECT COUNT(*) FROM product
            WHERE brand_normalized IS NULL
              AND (brand_raw_en = 'Please select a brand.' OR brand_raw_ar = 'Please select a brand.')
        """)
        excluded_count = cur.fetchone()[0]
        assert excluded_count == 7505

    result = adapter.search(FilterSet(brand="please_select_a_brand"), limit=5)
    assert result.zero_result
