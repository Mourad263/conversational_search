"""Sprint 4 Part 3: the thin conversational orchestration path that wires
together every already-built component into one real turn pipeline:

    pre-LLM guards -> understand() -> deterministic Action normalization
    -> validate()/StateManager (or the deterministic recommendation
    policy) -> SearchAdapter -> real product rows only -> deterministic
    response wording.

Deliberately NOT a new search/state abstraction -- StateManager,
validate(), parse_keyword_query(), and SearchAdapter are used exactly as
they already exist (src/state_manager, src/validation, src/search_engine,
src/search_adapter); this module only decides WHICH of them to call, in
WHICH order, for a given turn, per the Sprint 4 design/audit passes.
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

logger = logging.getLogger(__name__)

from src.api.schemas import ProductOut, SessionMessageResponse  # noqa: E402
from src.recommendation.service import get_recommendation_service  # noqa: E402
from src.response import messages  # noqa: E402
from src.scenario.decision import (  # noqa: E402
    derive_recommendation_search,
    has_searchable_target,
    normalize_target_facet,
    repair_recommendation_price_no_op,
)
from src.scenario.guard import check_rapid_repeat, has_reached_turn_cap  # noqa: E402
from src.scenario.session_activity import SessionActivity, SessionActivityStore  # noqa: E402
from src.scenario.trace import RequestTrace  # noqa: E402
from src.search_adapter.adapter import FilterSet, SearchAdapter, SearchResult  # noqa: E402
from src.search_engine.embeddings import pop_embedding_trace, reset_embedding_trace  # noqa: E402
from src.search_engine.index import get_index  # noqa: E402
from src.search_engine.ranking import correct_unmatched_terms  # noqa: E402
from src.search_engine.tokenizer import tokenize  # noqa: E402
from src.state_manager.state_manager import StateManager  # noqa: E402
from src.understanding.llm import pop_usage_trace, reset_usage_trace, understand  # noqa: E402
from src.understanding.schema import Action, Intent  # noqa: E402
from src.validation.validate import validate  # noqa: E402

_STATE_CHANGING_INTENTS = (
    Intent.SEARCH, Intent.ADD_FILTER, Intent.MODIFY_FILTER, Intent.REMOVE_FILTER,
)


def _real_search(filters: FilterSet, limit: int, offset: int) -> SearchResult:
    return SearchAdapter().search(filters, limit=limit, offset=offset)


def _to_float(v) -> float | None:
    return float(v) if v is not None else None


def _to_product_out(p: dict) -> ProductOut:
    return ProductOut(
        id=p["id"],
        name_en=p["name_en"],
        name_ar=p["name_ar"],
        price=_to_float(p["price"]),
        special_price=_to_float(p["special_price"]),
        brand_normalized=p["brand_normalized"],
        url_key=p["url_key"],
        sku=p["sku"],
    )


def _likely_out_of_catalog(searched_filters: FilterSet, result: SearchResult) -> bool:
    """Honest, conservative signal (Sprint 4 design pass) -- NEVER
    "proven". True only when ALL of: a real search ran and found zero
    results, the searched free text is non-empty, no canonical
    category/brand was resolved (a resolved category/brand means the
    concept IS in the catalog -- this exact combination just returned
    nothing, a filter_conflict, not an absent concept), the literal query
    tokens occur nowhere in the entire corpus (checked via the EXISTING
    SearchIndex vocabulary, index.postings -- no new DB query, no new
    infrastructure), AND the SAME generic, corpus-backed spelling
    correction SearchAdapter/rank() already use internally
    (ranking.py's correct_unmatched_terms) finds no safe real-corpus
    replacement either.

    Audit fix (manual acceptance test, real query "لانشن تحت 50"): a
    correctable typo for an in-catalog term (لانشن -> لانشون, 90 real
    luncheon products, corpus-confirmed) was being labeled
    likely_out_of_catalog=True purely because the ORIGINAL misspelled
    token has zero literal overlap -- this function never consulted
    correct_unmatched_terms() before concluding that. A correction found
    by that EXISTING mechanism is itself positive catalog evidence (the
    corrected term is real, corpus-frequent vocabulary), even when the
    turn's own filters (e.g. an explicit low price ceiling) still
    legitimately return zero matching rows -- that is a filter_conflict/
    genuine zero-result case, not evidence the concept is absent. A
    severe/uncorrectable misspelling can still false-positive here --
    disclosed, not solved."""
    if not result.zero_result:
        return False
    if not searched_filters.query_text:
        return False
    if searched_filters.category is not None or searched_filters.brand is not None:
        return False
    index = get_index()
    tokens = tokenize(searched_filters.query_text, index.base_freq)
    if not tokens:
        return False
    if index.candidates_for_tokens(tokens):
        return False
    return correct_unmatched_terms(index, searched_filters.query_text) is None


def _lacks_catalog_evidence(resolved: FilterSet) -> bool:
    """Sprint 6 out-of-catalog grounding task: deterministic, PRE-search
    gate -- True only when THIS TURN's own resolution (never the
    post-merge canonical state) gives no reason to believe the requested
    concept is something this catalog sells at all. Corpus-vocabulary
    evidence only, via the SAME in-memory SearchIndex used elsewhere here
    -- no DB query, no embeddings, no vector call.

    A resolved canonical category or brand is authoritative and always
    passes: validate()'s category_hint/brand_text grounding is itself
    typo/dialect-tolerant (it is a semantic classification, not an exact
    spelling match), so this alone already covers the overwhelming
    majority of real, uncommon, Arabic, code-switched, or misspelled
    catalog products -- see resolve_category_hint/resolve_brand_text. An
    empty query_text also passes: nothing to judge.

    Only for a PURE free-text query (no category/brand resolved) does this
    look at query_text itself, and ONLY when it has 2+ tokens: it then
    requires EVERY token to have at least one REAL, LITERAL occurrence
    somewhere in the corpus (index.postings) -- deliberately requiring ALL
    tokens, not just one, and deliberately NOT crediting ranking.py's
    fuzzy spelling-corrector here. Real regression measured directly:
    "كوتش عربية" (car tires) -- "كوتش" occurs in zero real products, but
    "عربية" (a generic "Arabic"/"car" modifier) coincidentally occurs in 3
    unrelated ones (e.g. Arabic coffee), which was already enough for the
    OLD any-token evidence check (index.candidates_for_tokens) to treat
    the whole phrase as grounded, and enough for ranking.py's own
    corrector to "fix" كوتش into the real but unrelated word سكوتش (Scotch
    tape) -- a disclosed, accepted false-positive class in that corrector
    (ranking.py's own docstring), fine for downstream RECALL but not
    trustworthy as catalog-membership EVIDENCE. Requiring every token to
    have genuine, uncorrected corpus presence is what actually rejects
    this case, while still passing any real multi-word product whose
    every word appears somewhere in the corpus.

    A SINGLE-token query is deliberately exempt from this stricter rule
    and always passes (returns False here) -- found live, via the
    project's own existing regression suite
    (tests/integration/test_typo_tolerance_audit.py's direct-vs-
    conversational parity tests): a lone token with zero literal corpus
    presence is exactly the shape of a genuine, single-word typo this
    catalog's OWN calibrated typo/vector-rescue machinery (ranking.py's
    correct_unmatched_terms, vector_search.py's distance-gated fallback --
    e.g. "milq"->milk, "لانشن"->لانشون/luncheon, both real, extensively
    measured rescues) is specifically built to recover; this gate must
    not pre-empt that with a cruder, unweighted rule. The 2+-token
    requirement is what actually distinguishes the two cases: a whole
    CONCEPT (multiple words) with one completely-absent word is a much
    stronger absence signal than one isolated word standing alone."""
    if resolved.category is not None or resolved.brand is not None:
        return False
    if not resolved.query_text:
        return False
    index = get_index()
    tokens = tokenize(resolved.query_text, index.base_freq)
    if len(tokens) < 2:
        return False
    return not all(t in index.postings for t in tokens)


def _response(
    session_id: str,
    message: str | None,
    intent: str,
    state: FilterSet,
    *,
    user_message: str,
    products: list[dict] | None = None,
    total_count: int = 0,
    zero_result: bool = False,
    likely_out_of_catalog: bool = False,
    blocked: bool = False,
    effective_price_min: float | None = None,
    effective_price_max: float | None = None,
    recommendations: list[dict] | None = None,
    recommendation_request: bool = False,
    needs_clarification: bool = False,
    assistant_message_override: str | None = None,
) -> SessionMessageResponse:
    recommendations = recommendations or []
    assistant_message = assistant_message_override if assistant_message_override is not None else (
        messages.build_assistant_message(
            user_message=user_message, intent=intent, recommendation_request=recommendation_request,
            recommendations_count=len(recommendations), zero_result=zero_result,
            likely_out_of_catalog=likely_out_of_catalog, blocked=blocked,
            needs_clarification=needs_clarification,
        )
    )
    return SessionMessageResponse(
        session_id=session_id,
        message=message,
        intent=intent,
        resolved_category=state.category,
        resolved_brand=state.brand,
        price_min=state.price_min,
        price_max=state.price_max,
        effective_price_min=effective_price_min,
        effective_price_max=effective_price_max,
        products=[_to_product_out(p) for p in (products or [])],
        total_count=total_count,
        zero_result=zero_result,
        likely_out_of_catalog=likely_out_of_catalog,
        blocked=blocked,
        recommendations=[_to_product_out(p) for p in recommendations],
        assistant_message=assistant_message,
    )


def _build_recommendations(
    action: Action, filters: FilterSet, search_fn: Callable[[FilterSet, int, int], SearchResult], limit: int,
    trace: RequestTrace | None = None,
) -> list[dict]:
    """Read-only: never calls StateManager.apply(), never mutates `filters`.
    Always derived from a REAL search under `filters` exactly as given --
    for the NO_OP/exploration path, callers must pass the CANONICAL state,
    never a temporary relaxed price band, so a recommendation can never
    quietly reflect a loosened constraint. [] whenever recommendation_request
    is false, there is no searchable target, or the real search behind it
    returns nothing -- never a fallback to an unfiltered/looser result.
    `trace` (Sprint 6 observability task) is purely observational -- when
    given, its recommendation_calls is incremented only at the exact line
    RecommendationService.recommend() actually runs; search_calls is left to
    `search_fn` itself (orchestrator passes an already-counting wrapper)."""
    if not action.recommendation_request or not has_searchable_target(filters):
        return []
    base_result = search_fn(filters, limit, 0)
    if not base_result.products:
        return []
    shown_ids = [p["id"] for p in base_result.products]
    if trace is not None:
        trace.recommendation_calls += 1
    return get_recommendation_service().recommend(filters.query_text, shown_ids, filters, limit=limit)


def _search_message_parts(
    action: Action, searched_filters: FilterSet, result: SearchResult, activity: SessionActivity,
    *, relaxation_note: bool = False,
) -> tuple[list[str], bool]:
    parts: list[str] = []
    if action.customer_service_tone:
        parts.append(messages.customer_service_acknowledgment())
    if relaxation_note:
        parts.append(messages.recommendation_band_note())
    if searched_filters.unresolved_exclusion:
        parts.append(messages.unresolved_exclusion_note(searched_filters.unresolved_exclusion))
    likely_ooc = _likely_out_of_catalog(searched_filters, result)
    if result.zero_result:
        parts.append(messages.zero_result(likely_ooc))
    if has_reached_turn_cap(activity):
        parts.append(messages.turn_cap_suggestion())
    return parts, likely_ooc


def _out_of_catalog_message_parts(action: Action, resolved: FilterSet, activity: SessionActivity) -> list[str]:
    """Sprint 6 out-of-catalog grounding task: wording for a request the
    PRE-search gate (_lacks_catalog_evidence) already rejected. Built
    directly, NOT via _search_message_parts -- that helper's own
    likely_out_of_catalog recomputation uses the older, looser ANY-token+
    spelling-correction heuristic (calibrated for post-hoc wording on a
    genuine zero-result SEARCH), which can disagree with this gate's
    stricter ALL-tokens rule on the exact cases the gate exists to catch
    (e.g. "كوتش عربية" -- see _lacks_catalog_evidence's docstring). The
    gate's decision is authoritative here; it is never re-derived."""
    parts: list[str] = []
    if action.customer_service_tone:
        parts.append(messages.customer_service_acknowledgment())
    if resolved.unresolved_exclusion:
        parts.append(messages.unresolved_exclusion_note(resolved.unresolved_exclusion))
    parts.append(messages.zero_result(True))
    if has_reached_turn_cap(activity):
        parts.append(messages.turn_cap_suggestion())
    return parts


def handle_message(
    session_id: str,
    message: str,
    *,
    state_manager: StateManager,
    activity_store: SessionActivityStore,
    understand_fn: Callable[..., Action] = understand,
    search_fn: Callable[[FilterSet, int, int], SearchResult] = _real_search,
    now: float | None = None,
    limit: int = 20,
    offset: int = 0,
) -> SessionMessageResponse:
    """Public entry point -- unchanged behavior/signature. Sprint 6
    observability task: owns exactly one RequestTrace per call, timing and
    logging it in `finally` so every return path in _handle_message_inner
    (including an unreachable-branch exception) still emits it. Tracing
    never influences the response -- see src/scenario/trace.py."""
    trace = RequestTrace(session_id=session_id)
    start = time.monotonic()
    reset_usage_trace()
    reset_embedding_trace()
    try:
        return _handle_message_inner(
            session_id, message, state_manager=state_manager, activity_store=activity_store,
            understand_fn=understand_fn, search_fn=search_fn, now=now, limit=limit, offset=offset,
            trace=trace,
        )
    finally:
        trace.total_latency_ms = round((time.monotonic() - start) * 1000, 2)
        usage = pop_usage_trace()
        if usage is not None:
            trace.llm_input_tokens = usage.get("input_tokens")
            trace.llm_output_tokens = usage.get("output_tokens")
            trace.llm_total_tokens = usage.get("total_tokens")
        trace.embedding_calls = pop_embedding_trace()
        logger.info("request_trace %s", trace.to_log_dict())


def _handle_message_inner(
    session_id: str,
    message: str,
    *,
    state_manager: StateManager,
    activity_store: SessionActivityStore,
    trace: RequestTrace,
    understand_fn: Callable[..., Action] = understand,
    search_fn: Callable[[FilterSet, int, int], SearchResult] = _real_search,
    now: float | None = None,
    limit: int = 20,
    offset: int = 0,
) -> SessionMessageResponse:
    """One conversational turn, exactly per the Sprint 4 Part 3 pipeline
    order. `message` is assumed already length-validated by the FastAPI
    request schema (SessionMessageRequest, max_length=500) -- that check
    happens before this function is ever called, so an oversized request
    never reaches understand(). `understand_fn`/`search_fn`/`now` are
    injectable purely for testing (no real OpenAI/DB calls needed in
    orchestration-logic tests); the real route always uses the defaults."""
    now = time.monotonic() if now is None else now

    def _counted_search(filters: FilterSet, limit_: int, offset_: int) -> SearchResult:
        # Sprint 6 observability task: the ONE place search_fn is actually
        # invoked from here on -- counts real execution only, never presence
        # in the pipeline (see _build_recommendations, which receives this
        # same wrapper instead of the raw search_fn).
        trace.search_calls += 1
        return search_fn(filters, limit_, offset_)

    # A1: lazy session-expiration check (Sprint 6 lifecycle task) -- no
    # background worker, just a check on this real access. SessionActivity
    # is the single last-activity clock for the whole session; when it says
    # this session id has been idle past SESSION_TTL_SECONDS, StateManager's
    # independent shopping FilterSet is dropped here (its own store has no
    # activity clock of its own) BEFORE activity_store.get() below lazily
    # wipes its own half -- an expired session must lose BOTH.
    if activity_store.is_expired(session_id, now):
        state_manager.clear(session_id)
    activity = activity_store.get(session_id, now=now)

    # A2: rapid-repeat guard. Blocked: no understand(), no history append,
    # no accepted turn_count increment, no StateManager mutation.
    if not check_rapid_repeat(activity, message, now=now):
        trace.route = "blocked"
        state = state_manager.get_state(session_id)
        return _response(session_id, messages.rapid_repeat_blocked(), "blocked", state,
                          user_message=message, blocked=True)

    # B: Understanding -- the ONLY history owner passed in is activity.history.
    trace.llm_calls = 1  # an attempted call counts even if it raises below --
    # real token usage (if any) is popped by the outer handle_message() wrapper.
    try:
        action = understand_fn(message, history=activity.history)
    except Exception as exc:
        # Provider errors (rate limits, quota, auth, schema/parse failures)
        # must stay observable server-side even though the user only ever
        # sees the generic fallback -- log type/status/message only, never
        # the request body or any credential.
        status = getattr(exc, "status_code", None)
        logger.warning("understand() failed: %s (status=%s): %s", type(exc).__name__, status, exc)
        trace.route = "error"
        state = state_manager.get_state(session_id)
        return _response(session_id, messages.understanding_failed(), "error", state, user_message=message)

    # C: deterministic Action normalization -- ONLY the two approved Part 2 helpers.
    action = normalize_target_facet(action)
    current_state = state_manager.get_state(session_id)
    action = repair_recommendation_price_no_op(action, current_state)

    # C2: memory recall (Sprint 6) -- deterministic, read-only, zero extra LLM
    # calls, checked before OFF_TOPIC/NO_OP so a genuine "what did I say
    # before?" question never gets the generic off-topic refocus just because
    # it names no product. Reads `activity.turns`/StateManager BEFORE this
    # turn is appended/counted below -- the current recall question itself
    # must never become the recalled message.
    if action.memory_recall is not None:
        prior_turns = activity.turns
        answer = messages.memory_recall_answer(
            message, action.memory_recall,
            previous_message=prior_turns[-1].message if prior_turns else None,
            first_message=prior_turns[0].message if prior_turns else None,
            category=current_state.category, brand=current_state.brand,
            price_min=current_state.price_min, price_max=current_state.price_max,
        )
        activity_store.append_history(session_id, message, action.intent.value)
        activity_store.increment_turn_count(session_id)
        trace.route = "memory_recall"
        return _response(
            session_id, None, action.intent.value, current_state,
            user_message=message, assistant_message_override=answer,
        )

    # D: OFF_TOPIC
    if action.intent == Intent.OFF_TOPIC:
        activity_store.increment_turn_count(session_id)
        trace.route = "off_topic"
        state = state_manager.get_state(session_id)
        return _response(
            session_id, messages.off_topic_refocus(action.customer_service_tone),
            action.intent.value, state, user_message=message,
        )

    # E: NO_OP / pure recommendation-exploration -- StateManager.apply() is
    # never called for this intent (state_manager.py raises ValueError for
    # it -- it is not one of its five handled intents by design).
    if action.intent == Intent.NO_OP:
        outcome = derive_recommendation_search(current_state, activity)
        activity_store.append_history(session_id, message, action.intent.value)
        activity_store.increment_turn_count(session_id)
        state = state_manager.get_state(session_id)  # unchanged canonical state
        trace.route = "recommendation"

        if outcome.needs_clarification:
            return _response(
                session_id, messages.recommendation_needs_clarification(), action.intent.value, state,
                user_message=message, recommendation_request=action.recommendation_request,
                needs_clarification=True,
            )

        # Sprint 6 recommendation task: ALWAYS derived from the CANONICAL
        # active state (current_state), never the temporary relaxed price
        # band below -- a recommendation must never quietly reflect a
        # loosened constraint just because the exploration policy widened
        # one for `products`. The two mechanisms are independent by design
        # (see src/recommendation/service.py's module docstring).
        recommendations = _build_recommendations(action, current_state, _counted_search, limit, trace)

        if outcome.effective_filters is None:
            # relaxation_exhausted -- no further automatic band, no SearchAdapter call
            return _response(
                session_id, messages.recommendation_relaxation_exhausted(), action.intent.value, state,
                user_message=message, recommendations=recommendations,
                recommendation_request=action.recommendation_request,
            )

        result = _counted_search(outcome.effective_filters, limit, offset)
        parts, likely_ooc = _search_message_parts(
            action, outcome.effective_filters, result, activity,
            relaxation_note=outcome.relaxation_applied,
        )
        return _response(
            session_id, " ".join(parts) or None, action.intent.value, state,
            user_message=message,
            products=result.products, total_count=result.total_count,
            zero_result=result.zero_result, likely_out_of_catalog=likely_ooc,
            effective_price_min=outcome.effective_filters.price_min,
            effective_price_max=outcome.effective_filters.price_max,
            recommendations=recommendations,
            recommendation_request=action.recommendation_request,
        )

    # G: RESET special case -- clears the CANONICAL shopping state (via the
    # normal apply() path, same as any other intent) and this session's
    # exploration bookkeeping, but Sprint 6 lifecycle task: deliberately does
    # NOT wipe conversation memory (history/turns) -- a "start over" on the
    # active search is not the same event as the session ending. It IS a
    # real accepted turn like any other, so it appends/counts normally
    # (full session teardown, including memory, is handled separately -- see
    # A1's expiration check and SessionActivityStore.reset()).
    if action.intent == Intent.RESET:
        trace.route = "reset"
        resolved = validate(action)
        trace.validation_calls += 1

        # Sprint 6 out-of-catalog grounding task: same pre-search gate as
        # the F branch below -- a "start over, and get me <unsupported
        # concept>" must still start over, just never populate the fresh
        # state with the unsupported concept (price bounds, if any, are
        # unrelated to catalog membership and are kept).
        if _lacks_catalog_evidence(resolved):
            trace.route = "out_of_catalog"
            state_manager.apply(
                session_id, action,
                FilterSet(price_min=resolved.price_min, price_max=resolved.price_max),
            )
            activity_store.append_history(session_id, message, action.intent.value)
            activity_store.increment_turn_count(session_id)
            activity_store.reset_relaxation_step(session_id)
            new_state = state_manager.get_state(session_id)
            parts = _out_of_catalog_message_parts(action, resolved, activity_store.get(session_id))
            return _response(
                session_id, " ".join(parts) or None, action.intent.value, new_state,
                user_message=message, zero_result=True, likely_out_of_catalog=True,
            )

        state_manager.apply(session_id, action, resolved)
        activity_store.append_history(session_id, message, action.intent.value)
        activity_store.increment_turn_count(session_id)
        activity_store.reset_relaxation_step(session_id)  # the search itself was
        # just cleared -- any prior automatic price-relaxation band no longer applies
        new_state = state_manager.get_state(session_id)
        result = _counted_search(new_state, limit, offset)
        parts, likely_ooc = _search_message_parts(action, new_state, result, activity_store.get(session_id))
        return _response(
            session_id, " ".join(parts) or None, action.intent.value, new_state,
            user_message=message,
            products=result.products, total_count=result.total_count,
            zero_result=result.zero_result, likely_out_of_catalog=likely_ooc,
        )

    # F: normal state-changing intents (SEARCH/ADD_FILTER/MODIFY_FILTER/
    # REMOVE_FILTER) -- the EXISTING deterministic validate()/StateManager
    # merge semantics, never duplicated here. An explicit exception, not a
    # bare `assert` -- `python -O` strips asserts silently (confirmed
    # project-wide in the Sprint 0-3 ingestion fail-safe pass), and this
    # exhaustiveness check over schema.py's Intent enum must actually fire.
    if action.intent not in _STATE_CHANGING_INTENTS:
        raise ValueError(f"unhandled effective intent reached orchestration: {action.intent!r}")
    resolved = validate(action)
    trace.validation_calls += 1

    # Sprint 6 out-of-catalog grounding task: deterministic pre-search gate
    # -- checked against THIS TURN's own resolution, before StateManager
    # ever merges it, so a prior turn's already-active category can never
    # paper over a brand-new unsupported concept, and an unsupported
    # request never overwrites/merges into the active search at all.
    # Skips SearchAdapter, vector fallback, and RecommendationService
    # entirely -- see _lacks_catalog_evidence().
    if _lacks_catalog_evidence(resolved):
        trace.route = "out_of_catalog"
        activity_store.append_history(session_id, message, action.intent.value)
        activity_store.increment_turn_count(session_id)
        state = state_manager.get_state(session_id)  # unchanged canonical state
        parts = _out_of_catalog_message_parts(action, resolved, activity)
        return _response(
            session_id, " ".join(parts) or None, action.intent.value, state,
            user_message=message, zero_result=True, likely_out_of_catalog=True,
        )

    trace.route = "shopping_search"
    state_manager.apply(session_id, action, resolved)
    activity_store.append_history(session_id, message, action.intent.value)
    activity_store.increment_turn_count(session_id)
    activity_store.reset_relaxation_step(session_id)  # real state change -> any prior
    # automatic exploration band no longer applies

    new_state = state_manager.get_state(session_id)
    result = _counted_search(new_state, limit, offset)
    parts, likely_ooc = _search_message_parts(action, new_state, result, activity)

    # Sprint 6 recommendation task: reuses the search that JUST ran under
    # new_state -- no second SearchAdapter call needed here, unlike the
    # NO_OP path above. [] whenever recommendation_request is false.
    recommendations: list[dict] = []
    if action.recommendation_request and result.products:
        shown_ids = [p["id"] for p in result.products]
        trace.recommendation_calls += 1
        recommendations = get_recommendation_service().recommend(
            new_state.query_text, shown_ids, new_state, limit=limit,
        )

    return _response(
        session_id, " ".join(parts) or None, action.intent.value, new_state,
        user_message=message,
        products=result.products, total_count=result.total_count,
        zero_result=result.zero_result, likely_out_of_catalog=likely_ooc,
        recommendations=recommendations,
        recommendation_request=action.recommendation_request,
    )


_state_manager: StateManager | None = None
_activity_store: SessionActivityStore | None = None


def get_state_manager() -> StateManager:
    global _state_manager
    if _state_manager is None:
        _state_manager = StateManager()
    return _state_manager


def get_activity_store() -> SessionActivityStore:
    global _activity_store
    if _activity_store is None:
        _activity_store = SessionActivityStore()
    return _activity_store
