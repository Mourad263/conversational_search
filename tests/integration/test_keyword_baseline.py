"""System A (FR-014, tasks.md T048): the naive keyword-search baseline.
Real corpus, real Postgres -- not mocked."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.search_engine.keyword_baseline import parse_keyword_query, search_keyword  # noqa: E402


def test_price_phrase_extraction():
    # NOTE: the real catalog has a canonical "Chocolate" category, so this
    # naive baseline correctly resolves "chocolate" to a category filter,
    # not leftover free text -- asserted against the actual category list,
    # not assumed.
    fs = parse_keyword_query("chocolate under 30")
    assert fs.price_max == 30.0
    assert fs.price_min is None
    assert fs.category == "chocolate_2"
    assert fs.query_text is None


def test_between_range():
    fs = parse_keyword_query("chicken between 50 and 200")
    assert fs.price_min == 50.0
    assert fs.price_max == 200.0


def test_category_matches_english_or_arabic_not_both():
    """Regression: an earlier version unioned EN+AR name tokens into one
    set, which required the query to contain BOTH languages' words at
    once -- so no plain-English or plain-Arabic query could ever match."""
    assert parse_keyword_query("meat under 100").category == "meat"
    assert parse_keyword_query("اللحوم").category == "meat"


def test_matched_category_not_double_counted_as_text_term():
    """Regression: an earlier version left the matched category name in
    the leftover free text, which then became a REQUIRED BM25 text-match
    term on top of the category filter -- 'meat under 100' found zero
    results because no meat product's title literally contains 'meat'."""
    result = search_keyword("meat under 100", limit=10)
    assert not result.zero_result
    assert result.total_count == 2
    for p in result.products:
        assert float(p["price"]) <= 100


def test_price_word_does_not_false_match_rice_category():
    """Regression check: naive substring matching without word boundaries
    would match the 'Rice' category inside the word 'price'."""
    fs = parse_keyword_query("price 100")
    assert fs.category is None


def test_search_keyword_end_to_end_zero_result():
    # category + an unmeetable price ceiling -> Stage 1 (hard filters)
    # alone is already empty, so this is zero regardless of Stage 2
    # (BM25/vector) behavior -- unlike a zero-result driven by a brand
    # name in free text, which no longer hard-filters at all now that
    # free-text brand inference has been removed.
    result = search_keyword("chocolate under 0.01", limit=5)
    assert result.zero_result
    assert result.products == []
