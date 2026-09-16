"""Sprint 1b Part B: brand resolved purely from free-text q, the same way
category/price already are -- there is no dedicated brand= query param,
only the resolved_brand output field. Detection is fuzzy/typo-tolerant
(rapidfuzz edit-distance ratio against Sprint 0's canonicalized brand
list, keyword_baseline._find_fuzzy_brand) rather than exact substring
matching, since a real misspelled brand mention ("glaxy", "munshi") is
common and a hard substring match would miss it entirely."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient  # noqa: E402

from src.api.routes import app  # noqa: E402
from src.search_engine.keyword_baseline import parse_keyword_query  # noqa: E402

client = TestClient(app)


def test_no_brand_query_param_on_the_endpoint():
    # OpenAPI schema must not advertise a brand= param at all -- q, limit,
    # offset only.
    schema = client.get("/openapi.json").json()
    params = schema["paths"]["/search/keyword"]["get"]["parameters"]
    assert [p["name"] for p in params] == ["q", "limit", "offset"]


def test_unknown_brand_query_param_is_silently_ignored():
    # FastAPI ignores query params that aren't declared on the route --
    # confirms the endpoint doesn't secretly still read one.
    r = client.get("/search/keyword", params={"q": "chocolate", "brand": "Galaxy"})
    assert r.status_code == 200
    assert r.json()["resolved_brand"] is None


def test_fuzzy_typo_english_brand_resolved_from_free_text():
    fs = parse_keyword_query("glaxy chocolate")
    assert fs.brand == "galaxy"


def test_fuzzy_typo_arabic_brand_resolved_from_free_text():
    # 'جهينه' and its English spelling 'Juhayna' are the same real brand
    # (684 EN/AR raw pairs like this were found to co-occur on real
    # products) and now share one canonical_brand row, slug='juhayna' --
    # not the old "brand_ef2ef07c4e" hash-fallback slug, and not a second,
    # disconnected canonical entry either (both were real bugs, fixed in
    # brand_normalization.py/brand_normalization_apply.py).
    # "لبن" (generic word for milk) now also resolves to the real "Milk"
    # category via its singular-form alias (research.md Class B fix) --
    # it used to stay unresolved leftover text; both are correct captures
    # of intent, but the category resolution is the more useful one.
    fs = parse_keyword_query("جوهينه لبن")
    assert fs.brand == "juhayna"
    assert fs.category == "milk_29"


def test_no_match_leaves_resolved_brand_null_not_a_fabricated_value():
    fs = parse_keyword_query("random household item xyz123")
    assert fs.brand is None


def test_fuzzy_brand_end_to_end_through_the_real_http_endpoint():
    r = client.get("/search/keyword", params={"q": "munshi wafers"})
    assert r.status_code == 200
    data = r.json()
    assert data["resolved_brand"] == "munchi"
    assert data["total_count"] > 0
    for p in data["products"]:
        assert p["brand_normalized"] == "munchi"


def test_brand_composes_with_category_and_price_from_q():
    r = client.get("/search/keyword", params={"q": "spinnies meat under 500"})
    data = r.json()
    assert data["resolved_brand"] == "spinneys"
    assert data["resolved_category"] == "meat"
    assert data["price_max"] == 500.0


def test_galaxy_glass_glassy_are_three_distinct_canonical_brands():
    # Real live data-quality bug (independent audit, 2026-09): a Sprint-0
    # reviewer approved two bad fuzzy clusters -- "جلاكسي" (Galaxy's
    # Arabic) merged with "جلاسى" (Glassy's Arabic), and "Glass" (2 real
    # glassware-mug products) merged with "Glassy" (9 real window/glass-
    # cleaner products) -- which the (correctly-functioning) cross-script
    # EN/AR merge step then transitively chained into ONE canonical brand
    # covering all three. Fixed at the source of truth: the checked-in
    # brand_canonicalization_review.csv now has "Glass" and "جلاسى"
    # reviewer_decision="reject" (2 cells changed, not regenerated),
    # re-applied via the real brand_normalization_apply.py. Root cause
    # was NOT a script-validation gap in the cross-script merge code
    # itself (confirmed: every union it performed was genuinely EN<->AR,
    # matching real column content) -- purely two bad review decisions.
    galaxy = parse_keyword_query("Galaxy")
    glass = parse_keyword_query("Glass")
    glassy = parse_keyword_query("Glassy")

    assert galaxy.brand == "galaxy"
    assert glass.brand not in (None, "galaxy")
    assert glassy.brand not in (None, "galaxy")
    assert glass.brand != glassy.brand  # Glass and Glassy are also distinct from each other


def test_galaxy_brand_filter_contains_only_chocolate_no_glass_or_glassy_products():
    r = client.get("/search/keyword", params={"q": "Galaxy"})
    assert r.status_code == 200
    data = r.json()
    assert data["resolved_brand"] == "galaxy"
    assert data["total_count"] == 43
    for p in data["products"]:
        assert p["brand_normalized"] == "galaxy"
        name = p["name_en"].lower()
        assert "window cleaner" not in name and "glass plus cleaner" not in name and "star mug" not in name


def test_glass_and_glassy_resolve_to_their_own_distinct_brands_via_http():
    r_glass = client.get("/search/keyword", params={"q": "Glass"})
    r_glassy = client.get("/search/keyword", params={"q": "Glassy"})
    glass_data, glassy_data = r_glass.json(), r_glassy.json()

    assert glass_data["resolved_brand"] not in (None, "galaxy")
    assert glassy_data["resolved_brand"] not in (None, "galaxy")
    assert glass_data["resolved_brand"] != glassy_data["resolved_brand"]
    assert glass_data["total_count"] == 2
    assert glassy_data["total_count"] == 9
    for p in glass_data["products"]:
        assert p["brand_normalized"] != "galaxy"
    for p in glassy_data["products"]:
        assert p["brand_normalized"] != "galaxy"
