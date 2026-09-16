"""Sprint 1b Part A: hybrid BM25 + dense/semantic search (RRF fusion), plus
the word-level spelling-correction step (ranking.py's
correct_unmatched_terms) that runs before the vector-only fallback when
BM25 finds zero matches -- corrects a query word to a real, sufficiently
common catalog word before re-trying BM25, so a typo of something that
genuinely exists in product names doesn't fall all the way to a "closest
anyway" vector guess. Proves the actual value proposition -- typo/
near-miss tolerance BM25 alone cannot give -- through the real HTTP
endpoint, not the embedding function in isolation.

NOTE: product_embeddings holds the full 25,881-product catalog (the
overnight full build_embeddings.py run, no --sample-size, completed and
verified directly against Postgres -- SELECT COUNT(*) FROM
product_embeddings = 25881).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api.routes import app  # noqa: E402
from src.search_adapter.adapter import FilterSet, SearchAdapter  # noqa: E402
from src.search_engine.index import get_index  # noqa: E402
from src.search_engine.ranking import correct_unmatched_terms, rank  # noqa: E402

client = TestClient(app)


def test_bm25_alone_genuinely_fails_on_the_typo():
    """Establishes the baseline this feature improves on: without vector
    fusion, 'milq' (a misspelling of 'milk') tokenizes to a word that
    matches nothing -- BM25 returns zero candidates, not just a bad rank."""
    index = get_index()
    candidate_ids = set(index.doc_len.keys())
    bm25_only = rank(index, candidate_ids, "milq")
    assert bm25_only == []


def test_typo_query_finds_milk_via_hybrid_endpoint():
    """The actual value proposition, proven end-to-end through the real
    HTTP endpoint: the same query BM25 alone fails on returns real,
    genuinely milk-related products via the vector path."""
    r = client.get("/search/keyword", params={"q": "milq"})
    assert r.status_code == 200
    data = r.json()
    assert not data["zero_result"]
    assert data["total_count"] > 0
    names = [p["name_en"].lower() for p in data["products"]]
    assert any("milk" in n for n in names), names


def test_hybrid_results_still_respect_structured_filters():
    """RRF fusion must not bypass Stage 1 -- a category/price filter still
    applies to whichever path (BM25 or vector) found a candidate."""
    r = client.get("/search/keyword", params={"q": "milq under 30"})
    assert r.status_code == 200
    data = r.json()
    assert data["price_max"] == 30.0
    for p in data["products"]:
        assert float(p["price"]) <= 30


def test_bm25_partial_match_still_gets_vector_rescue_for_a_large_pool():
    """SearchAdapter's non-empty-BM25 short-circuit (added to stop
    vector_rank's no-relevance-floor results flooding a SMALL candidate
    pool -- see test_searchadapter_does_not_flood_results_with_irrelevant_
    same_brand_products in test_category_fuzzy.py) must not throw away
    real recall when the candidate pool is large: "cookies milq" has BM25
    literal matches for "cookies" (87, verified directly), but "milq" (a
    typo of "milk") is a second, independent term only vector search can
    rescue. Over the full 25,881-product catalog (no structured filter,
    so vector_rank's LIMIT VECTOR_TOP_N=100 is a real filter, not a
    no-op), fusing vector results back in must recover genuinely
    milk-related products BM25's "cookies" match alone could never find."""
    r = client.get("/search/keyword", params={"q": "cookies milq"})
    assert r.status_code == 200
    data = r.json()
    assert data["total_count"] > 87, (
        "expected more than the 87 pure-'cookies' BM25 matches once vector "
        "rescue is fused back in for a large candidate pool"
    )
    names = [p["name_en"].lower() for p in data["products"]]
    assert any("milk" in n or "milka" in n for n in names), names


def test_vector_only_fallback_suppresses_unrelated_closest_matches():
    """The vector-only fallback (BM25 found nothing, spelling correction
    found no confident fix either) used to return its "closest anyway"
    neighbours even when none were related at all. "qwzxjklpv" is pure
    nonsense: no vocabulary word scores >= SPELLING_CORRECTION_THRESHOLD
    against it (best real match found in testing: "ziplock" at 57.1,
    nowhere near the 80 floor), and its nearest embedding (0.3442) is well
    past VECTOR_FALLBACK_MAX_DISTANCE (0.31) -- so it must return nothing
    rather than confidently-wrong results at either stage."""
    index = get_index()
    assert correct_unmatched_terms(index, "qwzxjklpv") is None
    r = client.get("/search/keyword", params={"q": "qwzxjklpv"})
    assert r.status_code == 200
    data = r.json()
    assert data["total_count"] == 0
    assert data["zero_result"] is True
    assert data["products"] == []


def test_spelling_correction_rescues_the_luncheon_typo_via_bm25():
    """The actual gap this step closes: "لانشن" (typo of لانشون/luncheon
    meat) has no category to fall back on (لانشون isn't a category in
    this catalog at all -- confirmed directly against canonical_category)
    and BM25's literal search finds zero matches for the typo'd spelling.
    Before this step it fell through to the vector floor and correctly
    returned nothing (a real gap, not a bug) -- now it corrects to the
    real word "لانشون" (90 literal matches) and returns those, not a
    "closest anyway" vector guess. total_count == 90 (not just > 0)
    confirms it's going through corrected BM25, matching exactly the real
    document frequency of "لانشون" in the index, not some other count a
    vector rescue might have produced."""
    index = get_index()
    assert correct_unmatched_terms(index, "لانشن") == "لانشون"

    r = client.get("/search/keyword", params={"q": "لانشن"})
    assert r.status_code == 200
    data = r.json()
    assert data["total_count"] == 90
    for p in data["products"]:
        assert "luncheon" in p["name_en"].lower() or "لانشون" in p["name_ar"]


def test_spelling_correction_rescues_a_multiword_query_with_only_one_typo():
    """Sprint 6 Finding D: correct_unmatched_terms used to only ever run
    when the WHOLE query had zero literal BM25 matches -- a multi-word
    query where ONE word already matches literally and ANOTHER is
    misspelled never reached correction at all, because the one matching
    word alone made bm25_ids non-empty. "greek yogourt": "greek" already
    matches literally (85 docs, confirmed directly), "yogourt" has zero
    literal matches and corrects to "yogurt" (confirmed directly via
    correct_unmatched_terms). Goes straight through SearchAdapter with a
    hand-built FilterSet -- not /search/keyword's parse_keyword_query,
    which would fuzzy-resolve "greek yogourt" to a real CATEGORY first and
    consume the free-text query entirely before it ever reaches this
    fix's code path (exactly the layer split this project's architecture
    keeps deliberately separate: category identity is validate()'s job,
    typo-tolerant free-text ranking is the adapter's)."""
    index = get_index()
    assert "greek" in index.postings
    assert "yogourt" not in index.postings
    assert correct_unmatched_terms(index, "greek yogourt") == "greek yogurt"

    typo_result = SearchAdapter().search(FilterSet(query_text="greek yogourt"), limit=5)
    correctly_spelled_result = SearchAdapter().search(FilterSet(query_text="greek yogurt"), limit=5)
    single_word_only_result = SearchAdapter().search(FilterSet(query_text="greek"), limit=5)
    # The typo'd query must match exactly as well as the correctly-spelled
    # one (the correction engaged), not fall back to matching only the one
    # word that happened to already be spelled right.
    assert typo_result.total_count == correctly_spelled_result.total_count
    assert typo_result.total_count > single_word_only_result.total_count


def test_spelling_correction_does_not_correct_milq_to_the_wrong_fragment():
    """Calibration lock-in: "milq" (typo of "milk") must NOT get corrected
    at all, let alone to the wrong thing. Confirmed directly: "milq" scores
    85.7 against "mil" (a real but unrelated 3-letter fragment, only 2
    products) -- HIGHER than 75.0 against "milk" itself (648 products) --
    so a bare score threshold would pick the wrong target.
    SPELLING_CORRECTION_MIN_TARGET_DOCS=3 blocks "mil" (2 docs, below
    the floor) while "milk" never even reaches the floor check (75.0 is
    already below SPELLING_CORRECTION_THRESHOLD). Net effect: no
    confident correction either way, and "milq" correctly falls through
    to the (already-tested) vector floor instead."""
    index = get_index()
    assert correct_unmatched_terms(index, "milq") is None


def test_spelling_correction_leaves_an_already_matching_word_alone():
    """Requirement: correction must never touch a word that already has
    real literal matches. "cookies olivee" mixes one already-matching word
    ("cookies", tokenizes to "cookie" -- the tokenizer's own corpus-aware
    plural disambiguation, unrelated to correction; used to be "cooky"
    before the "-ies" ambiguity fix, research.md) with one that needs
    correction ("olivee"). The already-matching word's normalized token
    must come back unchanged -- not replaced by some other fuzzy match --
    while the unmatched word is corrected."""
    index = get_index()
    corrected = correct_unmatched_terms(index, "cookies olivee")
    assert corrected is not None
    words = corrected.split()
    assert "cookie" in words  # "cookies" normalized, untouched by correction
    assert "olive" in words  # the actual correction


@pytest.mark.parametrize("query,expected_word_in_results", [
    ("tomatto", "tomato"),
    ("bananna", "banana"),
    ("ketchupp", "ketchup"),
    ("tunna", "tuna"),
    ("حليبب", "حليب"),
    ("جبنن", "جبن"),
])
def test_spelling_correction_generalizes_to_other_real_typos(query, expected_word_in_results):
    """Broader generalization check (research.md): confirms the correction
    step works for real typos beyond the single لانشن case, across both
    English and Arabic, without being individually special-cased."""
    r = client.get("/search/keyword", params={"q": query})
    assert r.status_code == 200
    data = r.json()
    assert data["total_count"] > 0, f"{query!r} found no results after correction"
    names_ar = [p["name_ar"] for p in data["products"]]
    names_en = [p["name_en"].lower() for p in data["products"]]
    assert any(expected_word_in_results in n for n in names_ar + names_en), (
        query, expected_word_in_results, names_en[:5]
    )


def test_vector_only_fallback_still_rescues_a_genuine_typo():
    """The other direction, and the reason this path exists at all: the
    distance gate must NOT cost the genuine rescues. "milq" (best distance
    0.2976, under the 0.31 floor) must still return its full real result
    set, not a truncated one -- the gate is all-or-nothing on the nearest
    match, deliberately NOT a per-result filter, because milq's own real
    results run from 0.2976 out past 0.34."""
    r = client.get("/search/keyword", params={"q": "milq"})
    assert r.status_code == 200
    data = r.json()
    assert data["total_count"] == 40
    names = [p["name_en"].lower() for p in data["products"]]
    assert any("milk" in n or "milka" in n for n in names), names
