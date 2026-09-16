"""Sprint 1 smoke tests: run the real hybrid engine against the real loaded
corpus (not mocks -- Postgres must be up and data loaded, per quickstart.md).
Covers the four cases requested: a normal keyword match, an Arabic query, a
category+price combo, and a case that must return zero results.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.search_adapter.adapter import FilterSet, SearchAdapter  # noqa: E402

adapter = SearchAdapter()


def test_keyword_match_chocolate():
    result = adapter.search(FilterSet(query_text="chocolate"), limit=10)
    assert not result.zero_result
    assert result.total_count > 0
    names = [p["name_en"].lower() for p in result.products]
    assert any("chocol" in n for n in names), names


def test_arabic_query():
    result = adapter.search(FilterSet(query_text="شوكولاتة"), limit=10)
    assert not result.zero_result
    assert result.total_count > 0


def test_category_and_price_combo():
    result = adapter.search(FilterSet(category="meat", price_max=100), limit=50)
    assert not result.zero_result
    assert result.total_count > 0
    for p in result.products:
        assert float(p["price"]) <= 100


def test_zero_result_when_price_too_low():
    result = adapter.search(FilterSet(category="meat", price_max=0.01), limit=10)
    assert result.zero_result
    assert result.total_count == 0
    assert result.products == []


def test_category_expands_to_all_raw_duplicates():
    """FR-019: a category filter must match products under ANY of the raw
    records that canonicalize to it (e.g. all 5 'Meat' category rows)."""
    result = adapter.search(FilterSet(category="meat"), limit=1000)
    assert result.total_count > 0


def test_filter_only_query_sorts_by_price_ascending():
    """Found via live testing: a category/price filter with no text query
    has no BM25 score to rank by, and originally came back in arbitrary
    (Python set iteration) order. Default: price ascending, nulls last."""
    result = adapter.search(FilterSet(category="meat"), limit=10)
    prices = [float(p["price"]) for p in result.products if p["price"] is not None]
    assert prices == sorted(prices)


def test_brand_filter():
    result = adapter.search(FilterSet(brand="Munchi"), limit=20)
    assert not result.zero_result
    assert result.total_count > 0
    for p in result.products:
        assert p["brand_normalized"] == "munchi"


def test_mixed_english_arabic_query():
    """spec.md's explicit edge case: a message mixing English and Arabic
    (e.g. an Arabic sentence with an English brand name) must still
    extract usable results, not fail outright."""
    result = adapter.search(FilterSet(query_text="عايز شوكولاتة Munchi"), limit=5)
    assert not result.zero_result
    assert result.total_count > 0
    # top results should be pulled toward the doubly-relevant (Arabic
    # "chocolate" + English "Munchi") products, not just any chocolate
    assert any(p["brand_normalized"] == "munchi" for p in result.products)


def test_pagination_pages_do_not_overlap_and_total_is_stable():
    page1 = adapter.search(FilterSet(query_text="chocolate"), limit=5, offset=0)
    page2 = adapter.search(FilterSet(query_text="chocolate"), limit=5, offset=5)
    ids1 = {p["id"] for p in page1.products}
    ids2 = {p["id"] for p in page2.products}
    assert ids1.isdisjoint(ids2)
    assert page1.total_count == page2.total_count
    assert len(page1.products) == 5
    assert len(page2.products) == 5


def test_zero_result_flag_never_fabricates_results():
    """A nonsense brand + an implausible price ceiling together should
    genuinely return nothing -- FR-012, not a loosened/substituted result."""
    result = adapter.search(
        FilterSet(brand="zzz_not_a_real_brand_zzz", price_max=1), limit=10
    )
    assert result.zero_result
    assert result.products == []


if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    print("=== normal keyword match: 'chocolate' ===")
    r = adapter.search(FilterSet(query_text="chocolate"), limit=5)
    for p in r.products:
        print(f"  {p['name_en']!r:60} {p['price']}")
    print(f"  total_count={r.total_count} zero_result={r.zero_result}\n")

    print("=== Arabic query: 'شوكولاتة' ===")
    r = adapter.search(FilterSet(query_text="شوكولاتة"), limit=5)
    for p in r.products:
        print(f"  {p['name_en']!r:60} {p['price']}")
    print(f"  total_count={r.total_count} zero_result={r.zero_result}\n")

    print("=== category+price combo: category=meat, price_max=100 ===")
    r = adapter.search(FilterSet(category="meat", price_max=100), limit=5)
    for p in r.products:
        print(f"  {p['name_en']!r:60} {p['price']}")
    print(f"  total_count={r.total_count} zero_result={r.zero_result}\n")

    print("=== zero-result case: category=meat, price_max=0.01 ===")
    r = adapter.search(FilterSet(category="meat", price_max=0.01), limit=5)
    print(f"  total_count={r.total_count} zero_result={r.zero_result} products={r.products}\n")
