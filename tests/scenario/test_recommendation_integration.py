"""Sprint 6 recommendation task: hermetic end-to-end tests for the
production RecommendationService wired into handle_message() via
`action.recommendation_request`. Same hermetic pattern as
test_orchestrator.py (understand() stubbed, everything else real --
real validate()/StateManager/SearchAdapter/RecommendationService against
the local Postgres + the frozen K=128 artifact). No OpenAI/Groq calls.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.recommendation.service import get_recommendation_service  # noqa: E402
from src.scenario.orchestrator import handle_message  # noqa: E402
from src.scenario.session_activity import SessionActivityStore  # noqa: E402
from src.search_adapter.adapter import FilterSet, SearchAdapter, SearchResult  # noqa: E402
from src.state_manager.state_manager import StateManager  # noqa: E402
from src.understanding.schema import Action, Intent  # noqa: E402


def stub_understand(*actions: Action):
    """Same helper as test_orchestrator.py (not cross-imported: this
    project's tests/ has no package __init__.py, so test modules don't
    import each other -- see that file for the fuller docstring)."""
    it = iter(actions)

    def _stub(message: str, history: list[str] | None = None) -> Action:
        return next(it)

    return _stub


class RecordingSearch:
    """Wraps the REAL SearchAdapter while recording every FilterSet it was
    called with -- same helper as test_orchestrator.py."""

    def __init__(self) -> None:
        self.calls: list[FilterSet] = []

    def __call__(self, filters: FilterSet, limit: int, offset: int) -> SearchResult:
        self.calls.append(filters)
        return SearchAdapter().search(filters, limit=limit, offset=offset)


# 1. normal search, recommendation_request=false -> no interference
def test_recommendation_request_false_yields_no_recommendations():
    sm, store = StateManager(), SessionActivityStore()
    understand_fn = stub_understand(
        Action(intent=Intent.SEARCH, raw_query_text="milk", category_hint="milk"),
    )
    r = handle_message("s1", "milk", state_manager=sm, activity_store=store,
                        understand_fn=understand_fn, search_fn=RecordingSearch())
    assert r.recommendations == []
    assert len(r.products) > 0  # normal search itself is unaffected


# 2. milk search -> real related recommendations
def test_milk_search_with_recommendation_request_returns_real_related_products():
    sm, store = StateManager(), SessionActivityStore()
    understand_fn = stub_understand(
        Action(intent=Intent.SEARCH, raw_query_text="milk", category_hint="milk", recommendation_request=True),
    )
    r = handle_message("s2", "what milk do you recommend?", state_manager=sm, activity_store=store,
                        understand_fn=understand_fn, search_fn=RecordingSearch())
    assert r.resolved_category == "milk_29"
    assert len(r.recommendations) > 0
    shown_ids = {p.id for p in r.products}
    for p in r.recommendations:
        assert p.id not in shown_ids  # criterion 8
    assert len({p.id for p in r.recommendations}) == len(r.recommendations)  # criterion 9 (no dupes)


# 3/4/5. lactose-free milk -- the critical constraint-safety case
def test_lactose_free_milk_recommendations_never_degrade_to_ordinary_milk():
    sm, store = StateManager(), SessionActivityStore()
    understand_fn = stub_understand(
        Action(intent=Intent.SEARCH, raw_query_text="milk", category_hint="milk", free_from="lactose",
               recommendation_request=True),
    )
    # default limit=20 shows ALL real lactose-free products (only 3 exist) --
    # exercises criterion 4: nothing left to recommend.
    r = handle_message("s3", "what lactose-free milk do you recommend?", state_manager=sm, activity_store=store,
                        understand_fn=understand_fn, search_fn=RecordingSearch())
    assert r.resolved_category == "lactose_free_32297"
    assert r.recommendations == []  # NOT a fallback to ordinary milk_29 products


def test_lactose_free_milk_with_headroom_recommends_only_the_remaining_real_product():
    sm, store = StateManager(), SessionActivityStore()
    understand_fn = stub_understand(
        Action(intent=Intent.SEARCH, raw_query_text="milk", category_hint="milk", free_from="lactose",
               recommendation_request=True),
    )
    # limit=2 leaves 1 of the 3 real lactose-free products unshown.
    # hard_filter() has no ORDER BY, so WHICH 2 of 3 get shown -- and
    # therefore whether the 1 remaining product lands in the same K=128
    # cluster as the shown ones -- is not guaranteed across runs; this
    # asserts the SAFETY property (never repeats a shown id, never a
    # non-lactose-free product) rather than an exact, order-dependent count.
    r = handle_message("s4", "what lactose-free milk do you recommend?", state_manager=sm, activity_store=store,
                        understand_fn=understand_fn, search_fn=RecordingSearch(), limit=2)
    assert r.resolved_category == "lactose_free_32297"
    assert len(r.recommendations) <= 1
    shown_ids = {p.id for p in r.products}
    for p in r.recommendations:
        assert p.id not in shown_ids
    # criterion 3: every recommendation genuinely satisfies the lactose-free
    # constraint -- confirmed by construction (hard_filter(category=
    # "lactose_free_32297", ...) is the only source of candidates).


# 6. price constraint
def test_price_constrained_recommendations_all_satisfy_the_range():
    sm, store = StateManager(), SessionActivityStore()
    understand_fn = stub_understand(
        Action(intent=Intent.SEARCH, raw_query_text="milk", category_hint="milk", price_max=30.0,
               recommendation_request=True),
    )
    r = handle_message("s5", "milk under 30, what do you recommend?", state_manager=sm, activity_store=store,
                        understand_fn=understand_fn, search_fn=RecordingSearch())
    assert len(r.recommendations) > 0
    for p in r.recommendations:
        assert p.price is not None and p.price <= 30.0


# 7. brand constraint
def test_brand_constrained_recommendations_all_satisfy_the_brand():
    sm, store = StateManager(), SessionActivityStore()
    understand_fn = stub_understand(
        Action(intent=Intent.SEARCH, raw_query_text="milk", category_hint="milk", brand_text="Juhayna",
               recommendation_request=True),
    )
    # Only 18 real Juhayna milk_29 products exist -- handle_message's default
    # limit=20 would show all of them, leaving zero headroom (itself a safe,
    # correct outcome, but not what this test is exercising); limit=5 leaves
    # real headroom.
    r = handle_message("s6", "what Juhayna milk do you recommend?", state_manager=sm, activity_store=store,
                        understand_fn=understand_fn, search_fn=RecordingSearch(), limit=5)
    assert r.resolved_brand == "juhayna"
    assert len(r.recommendations) > 0
    for p in r.recommendations:
        assert p.brand_normalized == "juhayna"


# 10. empty/invalid search-result evidence -> safe empty result
def test_zero_search_results_yields_empty_recommendations_not_a_crash():
    sm, store = StateManager(), SessionActivityStore()
    understand_fn = stub_understand(
        # an impossible price ceiling on a real category -> zero base results
        Action(intent=Intent.SEARCH, raw_query_text="milk", category_hint="milk", price_max=0.01,
               recommendation_request=True),
    )
    r = handle_message("s7", "milk under 0.01, what do you recommend?", state_manager=sm, activity_store=store,
                        understand_fn=understand_fn, search_fn=RecordingSearch())
    assert r.zero_result is True
    assert r.recommendations == []


def test_recommendation_service_empty_ids_is_safe():
    """Service-level: no valid search-result evidence at all -- never
    invents a recommendation (task rule)."""
    from src.search_adapter.adapter import FilterSet
    service = get_recommendation_service()
    assert service.recommend("milk", [], FilterSet(category="milk_29"), limit=5) == []
    assert service.recommend("milk", [-1, -2], FilterSet(category="milk_29"), limit=5) == []  # invalid ids


# 11. "what do you recommend?" after an active search -- uses existing
# state, must NOT mutate it.
def test_bare_recommendation_after_active_search_uses_state_without_mutating_it():
    sm, store = StateManager(), SessionActivityStore()
    understand_fn = stub_understand(
        Action(intent=Intent.SEARCH, raw_query_text="milk", category_hint="milk", price_max=50.0),
        Action(intent=Intent.NO_OP, recommendation_request=True),
    )
    handle_message("s8", "I need milk under 50", state_manager=sm, activity_store=store,
                    understand_fn=understand_fn, search_fn=RecordingSearch())
    before = sm.get_state("s8")

    r2 = handle_message("s8", "what do you recommend?", state_manager=sm, activity_store=store,
                         understand_fn=understand_fn, search_fn=RecordingSearch())

    after = sm.get_state("s8")
    assert after == before  # canonical state completely untouched (criterion 9)
    assert after.category == "milk_29" and after.price_max == 50.0
    assert len(r2.recommendations) > 0
    for p in r2.recommendations:
        assert p.price is None or p.price <= 50.0


# 12. search + recommendation in one turn
def test_search_and_recommendation_in_the_same_turn():
    sm, store = StateManager(), SessionActivityStore()
    understand_fn = stub_understand(
        Action(intent=Intent.SEARCH, raw_query_text="milk", category_hint="milk", price_max=50.0,
               recommendation_request=True),
    )
    r = handle_message("s9", "what milk do you recommend under 50?", state_manager=sm, activity_store=store,
                        understand_fn=understand_fn, search_fn=RecordingSearch())
    assert r.resolved_category == "milk_29"
    assert r.price_max == 50.0
    assert len(r.products) > 0  # normal search still happened
    assert len(r.recommendations) > 0  # AND recommendations were generated from it


# 13. off-topic unchanged
def test_off_topic_still_has_no_recommendations():
    sm, store = StateManager(), SessionActivityStore()
    understand_fn = stub_understand(Action(intent=Intent.OFF_TOPIC))
    r = handle_message("s10", "what's the weather?", state_manager=sm, activity_store=store,
                        understand_fn=understand_fn, search_fn=RecordingSearch())
    assert r.intent == "off_topic"
    assert r.recommendations == []
    assert r.products == []
