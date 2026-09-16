"""Manual-acceptance audit fix: a real conversational test found
"انا عاوز لانشن تحت 50" (typo of لانشون/luncheon, under 50 EGP) reporting
likely_out_of_catalog=True even though the generic, corpus-backed
spelling-correction pipeline (ranking.py's correct_unmatched_terms,
already built in Sprint 1b) correctly rescues لانشن -> لانشون and finds 90
real luncheon products (61.75-399.95 EGP, corpus-confirmed). Root cause:
src/scenario/orchestrator.py's _likely_out_of_catalog() checked literal
corpus-token overlap on the ORIGINAL (possibly misspelled) query_text only
-- it never consulted the same correction step SearchAdapter/rank()
already use internally, so a successfully-corrected typo with a
subsequently-empty price-filtered result set was mislabeled as a
catalog-absent concept instead of a genuine (and honestly worded)
zero-result/filter-conflict case. Fixed generically in
_likely_out_of_catalog() itself -- NOT a لانشن-specific mapping (see the
diversified matrix below, covering independent real-catalog terms).

Every case here goes through the full parse_keyword_query()/search_keyword()
pipeline (never an isolated helper, never a hand-built FilterSet standing
in for what parsing would produce) -- the project's own CRITICAL CONSTRAINT
(src/validation/validate.py), since category/brand fuzzy resolution is
itself one of the typo-tolerance layers being audited here.

Hermetic in the "no OpenAI call" sense -- real DB, real SearchIndex, real
SearchAdapter throughout (the corpus IS the ground truth being audited).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest  # noqa: E402

from src.scenario.orchestrator import _likely_out_of_catalog, handle_message  # noqa: E402
from src.scenario.session_activity import SessionActivityStore  # noqa: E402
from src.search_adapter.adapter import FilterSet, SearchResult  # noqa: E402
from src.search_engine.keyword_baseline import parse_keyword_query, search_keyword  # noqa: E402
from src.state_manager.state_manager import StateManager  # noqa: E402
from src.understanding.schema import Action, Intent  # noqa: E402

LANSHEN = "لانشن"    # لانشن -- real typo of لانشون (luncheon)
LANSHON = "لانشون"  # لانشون -- correct spelling


# --- the exact reported bug, fixed ---

def test_correctable_typo_with_price_filter_is_not_out_of_catalog():
    """The exact regression: a corpus-rescuable typo, filtered down to zero
    rows by a genuine price ceiling no real luncheon product meets, must
    report zero_result=True but likely_out_of_catalog=False -- not a
    catalog-absence claim, since the correction proves the concept exists."""
    filters = parse_keyword_query(LANSHEN + " تحت 50")  # "... under 50"
    assert filters.price_max == 50.0
    result = search_keyword(LANSHEN + " تحت 50", limit=5)
    assert result.total_count == 0
    assert result.zero_result is True
    assert _likely_out_of_catalog(filters, result) is False


def test_typo_and_correct_spelling_behave_identically_under_the_same_price_filter():
    typo_result = search_keyword(LANSHEN + " تحت 50", limit=5)
    correct_result = search_keyword(LANSHON + " تحت 50", limit=5)
    assert typo_result.total_count == correct_result.total_count == 0
    assert typo_result.zero_result == correct_result.zero_result is True


def test_correctable_typo_without_price_filter_finds_real_products():
    result = search_keyword(LANSHEN, limit=5)
    assert result.total_count > 0
    assert result.zero_result is False
    assert any("uncheon" in p["name_en"] for p in result.products)


def test_likely_out_of_catalog_helper_withholds_label_when_correction_succeeds():
    """Direct unit proof of the fix: even with zero_result=True and no
    resolved category/brand, a query whose text IS correctable via the
    existing corpus-backed correction must not be flagged."""
    zero = SearchResult(products=[], total_count=0, zero_result=True)
    assert _likely_out_of_catalog(FilterSet(query_text=LANSHEN), zero) is False


def test_likely_out_of_catalog_still_flags_genuinely_uncorrectable_nonsense():
    """The fix must not weaken the signal for real catalog-absence cases --
    a genuinely uncorrectable nonsense string is still flagged."""
    nonsense = "xyzzyplughnonsenseword"
    filters = parse_keyword_query(nonsense)
    result = search_keyword(nonsense, limit=5)
    assert result.zero_result is True
    assert _likely_out_of_catalog(filters, result) is True


# --- diversified typo-tolerance matrix (independent real-catalog terms) ---
# label, query text, whether a non-empty result is expected (None = see dedicated test below)
TYPO_CASES = [
    ("EN control: chocolate", "chocolate", True),
    ("EN deletion: choclate", "choclate", True),
    ("EN insertion: chocolatte", "chocolatte", True),
    ("EN substitution: chocolete", "chocolete", True),
    ("EN transposition: chocoalte", "chocoalte", True),
    ("EN control: shampoo", "shampoo", True),
    ("EN insertion: shampooo", "shampooo", True),
    ("EN substitution: shanpoo", "shanpoo", True),
    ("EN transposition: shmapoo", "shmapoo", True),
    ("AR control: شامبو", "شامبو", True),
    ("AR deletion: شمبو", "شمبو", True),
    ("AR insertion: شاامبو", "شاامبو", True),
    ("AR substitution: شامنو", "شامنو", True),
    ("AR transposition: شابمو", "شابمو", True),
    ("AR deletion: مشرب (drink)", "مشرب", True),
    ("historical: milq", "milq", True),
    ("historical: لانشن", LANSHEN, True),
    ("negative control: xyzzyplughnonsenseword", "xyzzyplughnonsenseword", False),
    ("negative control: qwzxjklvbnmasdfghjklz", "qwzxjklvbnmasdfghjklz", False),
]


@pytest.mark.parametrize("label,text,expect_hits", TYPO_CASES, ids=[c[0] for c in TYPO_CASES])
def test_diversified_typo_matrix(label, text, expect_hits):
    filters = parse_keyword_query(text)
    result = search_keyword(text, limit=3)
    if expect_hits is True:
        assert result.total_count > 0, f"{label}: expected real results, got zero"
        assert result.zero_result is False
    else:
        assert result.total_count == 0, f"{label}: expected zero results, got {result.total_count}"
        assert result.zero_result is True
        # a genuine negative control must never be laundered into a false rescue
        assert _likely_out_of_catalog(filters, result) is True


def test_multi_word_typo_with_brand_collision_is_a_filter_conflict_not_out_of_catalog():
    """"choclate milk" used to be a known, pre-existing competing-match
    edge case (keyword_baseline.py's own docstring at the time):
    "choclate" fuzzily matched the REAL brand "Chocodate" rather than
    the intended chocolate category, combined with category=milk_29 --
    a real, resolved category+brand combination that genuinely returned
    nothing. Sprint 6's catalog-scale fuzzy-collision audit fixed this
    specific case generically (not as a one-off): "choclate" has real
    product-corpus support (5 real products literally contain this
    misspelling) but essentially ZERO overlap with Chocodate's own real
    products (overlap_ratio far below _MIN_CANDIDATE_OVERLAP_RATIO) --
    exactly the same false-collision pattern as paste/Pasta and
    peas/Pears, just not one of the 4 originally-reported examples.
    brand is now correctly None; the query_text leftover "choclate"
    (itself a literal, uncorrected corpus token, so still a hard
    BM25 filter) combined with category=milk_29 still genuinely matches
    no real product, so this remains a real zero-result -- the point of
    this test is unchanged: that zero-result must still be classified as
    a filter conflict, never a false out-of-catalog claim."""
    text = "choclate milk"
    filters = parse_keyword_query(text)
    assert filters.category == "milk_29"
    assert filters.brand is None
    result = search_keyword(text, limit=3)
    assert result.zero_result is True
    assert _likely_out_of_catalog(filters, result) is False


# --- direct vs conversational parity ---

@pytest.mark.parametrize("text", [LANSHEN, "choclate", "milq", "xyzzyplughnonsenseword"])
def test_direct_and_conversational_search_do_not_diverge(text):
    direct = search_keyword(text, limit=5)

    sm, store = StateManager(), SessionActivityStore()

    def stub(message, history=None):
        # Sprint 6: category_hint is the semantic-role equivalent of what a
        # real LLM extracts alongside raw_query_text for a bare product
        # word (see SYSTEM_PROMPT's own "milk" example) -- validate() no
        # longer calls parse_keyword_query() on raw_query_text alone, so a
        # stub that omits category_hint is not testing what a real
        # understand() call would actually produce for this message.
        return Action(intent=Intent.SEARCH, raw_query_text=text, category_hint=text)

    def spy(filters, limit, offset):
        from src.search_adapter.adapter import SearchAdapter
        return SearchAdapter().search(filters, limit=limit, offset=offset)

    conv = handle_message("parity-session", text, state_manager=sm, activity_store=store,
                           understand_fn=stub, search_fn=spy)

    assert conv.total_count == direct.total_count
    assert conv.zero_result == direct.zero_result


def test_direct_and_conversational_parity_with_price_filter():
    direct = search_keyword(LANSHEN + " تحت 50", limit=5)

    sm, store = StateManager(), SessionActivityStore()

    def stub(message, history=None):
        return Action(intent=Intent.SEARCH, raw_query_text=LANSHEN, price_max=50.0)

    def spy(filters, limit, offset):
        from src.search_adapter.adapter import SearchAdapter
        return SearchAdapter().search(filters, limit=limit, offset=offset)

    conv = handle_message("parity-session-2", "انا عاوز " + LANSHEN + " تحت 50",
                           state_manager=sm, activity_store=store, understand_fn=stub, search_fn=spy)

    assert conv.total_count == direct.total_count == 0
    assert conv.zero_result == direct.zero_result is True
    assert conv.likely_out_of_catalog is False
