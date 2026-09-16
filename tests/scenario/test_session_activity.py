"""Sprint 4 Part 2: SessionActivityStore unit tests. Hermetic -- no LLM,
no DB. Pins the intended integration contract (which turn types get
appended to history / counted as turns) even though the actual per-turn
decision logic belongs to Part 3's conversational route, not built yet --
these tests call the store's real methods in the same pattern that
orchestration will."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.scenario.session_activity import SessionActivity, SessionActivityStore  # noqa: E402
from src.understanding.llm import HISTORY_WINDOW  # noqa: E402


def test_unseen_session_starts_completely_empty():
    store = SessionActivityStore()
    activity = store.get("never-seen-before")
    assert activity == SessionActivity()
    assert activity.history == []
    assert activity.last_message is None
    assert activity.repeat_count == 0
    assert activity.repeat_window_start == 0.0
    assert activity.turn_count == 0
    assert activity.relaxation_step == 0


def test_sessions_are_isolated_from_each_other():
    store = SessionActivityStore()
    store.append_history("session-a", "milk")
    store.increment_turn_count("session-a")

    assert store.get("session-b").history == []
    assert store.get("session-b").turn_count == 0
    assert store.get("session-a").history == ["milk"]
    assert store.get("session-a").turn_count == 1


def test_history_append_bounded_to_history_window():
    store = SessionActivityStore()
    session = "s1"
    for i in range(HISTORY_WINDOW + 3):
        store.append_history(session, f"turn {i}")

    history = store.get(session).history
    assert len(history) == HISTORY_WINDOW
    # oldest -> newest, only the last HISTORY_WINDOW entries survive
    assert history == [f"turn {i}" for i in range(3, HISTORY_WINDOW + 3)]


def test_off_topic_turn_is_not_appended():
    """Simulates the documented orchestration contract: an OFF_TOPIC turn
    never calls append_history at all."""
    store = SessionActivityStore()
    session = "s1"
    store.append_history(session, "I need milk")
    # off_topic turn: orchestration does NOT call append_history for it
    assert store.get(session).history == ["I need milk"]


def test_blocked_turn_is_not_appended():
    """A rapid-repeat/oversized request never reaches append_history --
    simulated the same way: simply never calling it for that turn."""
    store = SessionActivityStore()
    session = "s1"
    store.append_history(session, "milk")
    # blocked turn: never calls append_history
    assert store.get(session).history == ["milk"]


def test_failed_turn_can_remain_uncommitted():
    """An LLM/API failure or a validation/apply failure leaves the store
    exactly as it was before the failed attempt -- no partial state."""
    store = SessionActivityStore()
    session = "s1"
    store.append_history(session, "milk")
    before = list(store.get(session).history)
    # failed turn: never calls append_history for its own message
    assert store.get(session).history == before


def test_full_runtime_reset_clears_every_field():
    store = SessionActivityStore()
    session = "s1"
    store.append_history(session, "milk")
    store.increment_turn_count(session)
    activity = store.get(session)
    activity.last_message = "milk"
    activity.repeat_count = 2
    activity.repeat_window_start = 123.0
    activity.relaxation_step = 2

    store.reset(session)

    assert store.get(session) == SessionActivity()


def test_reset_isolation_does_not_affect_other_sessions():
    store = SessionActivityStore()
    store.append_history("session-a", "milk")
    store.append_history("session-b", "detergent")

    store.reset("session-a")

    assert store.get("session-a") == SessionActivity()
    assert store.get("session-b").history == ["detergent"]


def test_reset_relaxation_step_only_touches_that_one_field():
    store = SessionActivityStore()
    session = "s1"
    store.append_history(session, "lotion")
    store.increment_turn_count(session)
    store.get(session).relaxation_step = 2

    store.reset_relaxation_step(session)

    activity = store.get(session)
    assert activity.relaxation_step == 0
    assert activity.history == ["lotion"]
    assert activity.turn_count == 1
