"""Sprint 4 Part 2/4: rapid-repeat guard + turn-cap unit tests. Hermetic --
injected `now` timestamps throughout, never a real sleep.

REPEAT_THRESHOLD=4 (Part 4 fix): the 1st, 2nd, AND 3rd identical request
within the window all pass -- only the 4th blocks. Deliberately aligned
with src/scenario/decision.py's MAX_RELAXATION_STEPS=3, so a user
exploring a recommendation by sending the exact same phrase ("show me
more" x3) can reach all three automatic price-relaxation steps without
this guard ever firing early."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.scenario.guard import (  # noqa: E402
    REPEAT_THRESHOLD,
    REPEAT_WINDOW_SECONDS,
    SESSION_TURN_CAP,
    check_rapid_repeat,
    has_reached_turn_cap,
    normalize_for_repeat_check,
)
from src.scenario.session_activity import SessionActivity  # noqa: E402


def test_constants():
    assert REPEAT_THRESHOLD == 4
    assert REPEAT_WINDOW_SECONDS == 30.0
    assert SESSION_TURN_CAP == 40


def test_normalize_strips_casefolds_and_collapses_whitespace():
    assert normalize_for_repeat_check("  Show   Me More ") == "show me more"


def test_first_second_and_third_identical_request_all_pass():
    activity = SessionActivity()
    assert check_rapid_repeat(activity, "show me more", now=0.0) is True
    assert check_rapid_repeat(activity, "show me more", now=1.0) is True
    assert check_rapid_repeat(activity, "show me more", now=2.0) is True


def test_fourth_identical_request_within_window_is_blocked():
    activity = SessionActivity()
    assert check_rapid_repeat(activity, "show me more", now=0.0) is True
    assert check_rapid_repeat(activity, "show me more", now=1.0) is True
    assert check_rapid_repeat(activity, "show me more", now=2.0) is True
    assert check_rapid_repeat(activity, "show me more", now=3.0) is False


def test_sequence_resets_after_window_expires():
    activity = SessionActivity()
    assert check_rapid_repeat(activity, "show me more", now=0.0) is True
    assert check_rapid_repeat(activity, "show me more", now=1.0) is True
    assert check_rapid_repeat(activity, "show me more", now=2.0) is True
    # would be the 4th within the window and blocked, but the window has expired
    assert check_rapid_repeat(activity, "show me more", now=31.0) is True
    # fresh sequence: 2nd/3rd occurrences after the reset still pass
    assert check_rapid_repeat(activity, "show me more", now=31.5) is True
    assert check_rapid_repeat(activity, "show me more", now=32.0) is True
    assert check_rapid_repeat(activity, "show me more", now=32.5) is False


def test_different_message_resets_the_sequence():
    activity = SessionActivity()
    assert check_rapid_repeat(activity, "show me more", now=0.0) is True
    assert check_rapid_repeat(activity, "show me more", now=1.0) is True
    assert check_rapid_repeat(activity, "show me more", now=1.5) is True
    # a different message resets the count, even though the window hasn't expired
    assert check_rapid_repeat(activity, "anything else?", now=2.0) is True
    assert check_rapid_repeat(activity, "anything else?", now=2.5) is True
    assert check_rapid_repeat(activity, "anything else?", now=3.0) is True
    assert check_rapid_repeat(activity, "anything else?", now=3.5) is False


def test_whitespace_and_case_variants_count_as_the_same_repeat():
    activity = SessionActivity()
    assert check_rapid_repeat(activity, "Show Me More", now=0.0) is True
    assert check_rapid_repeat(activity, "  show   me more  ", now=1.0) is True
    assert check_rapid_repeat(activity, "SHOW ME MORE", now=2.0) is True
    assert check_rapid_repeat(activity, "show me more", now=3.0) is False


def test_blocked_repeat_still_updates_bookkeeping():
    activity = SessionActivity()
    check_rapid_repeat(activity, "show me more", now=0.0)
    check_rapid_repeat(activity, "show me more", now=1.0)
    check_rapid_repeat(activity, "show me more", now=2.0)
    check_rapid_repeat(activity, "show me more", now=3.0)  # blocked
    assert activity.repeat_count == 4
    assert activity.last_message == "show me more"


def test_has_reached_turn_cap():
    activity = SessionActivity()
    activity.turn_count = SESSION_TURN_CAP - 1
    assert has_reached_turn_cap(activity) is False
    activity.turn_count = SESSION_TURN_CAP
    assert has_reached_turn_cap(activity) is True
    activity.turn_count = SESSION_TURN_CAP + 5
    assert has_reached_turn_cap(activity) is True
