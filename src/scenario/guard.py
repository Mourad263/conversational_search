"""Sprint 4 System Guard: deterministic, pre-LLM request-shape checks for
the token_abuse scenario (Sprint 4 design pass) -- never an LLM judgment
call. Two of the three approved controls live here: rapid-repeat
detection and the (non-blocking) session turn cap. The third, a
per-request length cap, is wired at the FastAPI layer in Part 3 (a
route-level Query/body length constraint, the same pattern already proven
at src/api/routes.py's `q: str = Query(..., min_length=1, max_length=500)`)
-- MAX_REQUEST_LENGTH is recorded here only so the two layers agree on one
constant; there is no separate deterministic check to implement behind a
plain length comparison.
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.scenario.session_activity import SessionActivity  # noqa: E402

REPEAT_THRESHOLD = 4  # the 4th identical request within the window blocks -- the
# 1st, 2nd, and 3rd always pass. Deliberately aligned with
# src/scenario/decision.py's MAX_RELAXATION_STEPS=3: a user exploring a
# recommendation by sending the exact same phrase ("show me more" x3) must be
# able to reach all three automatic price-relaxation steps without tripping
# this guard (Sprint 4 Part 4 fix -- REPEAT_THRESHOLD=3 would have blocked the
# 3rd genuine exploration step, which the recommendation policy explicitly
# supports). Still fully generic and deterministic -- no phrase allowlist, no
# special-casing of "show me more", no LLM judgment call.
REPEAT_WINDOW_SECONDS = 30.0  # fixed window anchored at the first occurrence of the
# current run of identical messages, not a sliding per-message recomputation --
# see check_rapid_repeat().
SESSION_TURN_CAP = 40  # non-blocking -- see has_reached_turn_cap(). Part 3 appends a
# deterministic reset-suggestion at/after this many accepted turns; the turn itself
# still proceeds normally.
MAX_REQUEST_LENGTH = 500  # enforced at the FastAPI layer in Part 3, matching the
# existing /search/keyword `q` bound.

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_for_repeat_check(message: str) -> str:
    """strip -> casefold -> collapse internal whitespace. Deliberately
    minimal -- no stemming, no fuzzy matching, no catalog parser (Sprint 4
    design pass: token_abuse detection must stay a pure, cheap system
    guard, never a probabilistic/linguistic judgment). "  Show   Me More "
    and "show me more" normalize identically."""
    return _WHITESPACE_RE.sub(" ", message.strip().casefold())


def check_rapid_repeat(activity: SessionActivity, message: str, now: float | None = None) -> bool:
    """Returns True if `message` is ALLOWED, False if it must be blocked
    as a rapid repeat. Always updates `activity`'s repeat bookkeeping
    (last_message/repeat_count/repeat_window_start) as a side effect,
    including on a call this function itself blocks -- that bookkeeping
    must advance regardless, since it is literally what is being counted.

    `now` is an injectable monotonic-clock reading (seconds) so tests
    never need to sleep; defaults to time.monotonic()."""
    if now is None:
        now = time.monotonic()

    normalized = normalize_for_repeat_check(message)
    window_expired = (now - activity.repeat_window_start) > REPEAT_WINDOW_SECONDS
    is_same_message = normalized == activity.last_message

    if not is_same_message or window_expired:
        activity.last_message = normalized
        activity.repeat_count = 1
        activity.repeat_window_start = now
        return True

    activity.repeat_count += 1
    return activity.repeat_count < REPEAT_THRESHOLD


def has_reached_turn_cap(activity: SessionActivity) -> bool:
    """Non-blocking signal only (see SESSION_TURN_CAP) -- Part 3 uses this
    to decide whether to append a reset-suggestion to an otherwise-normal
    response, never to reject the turn."""
    return activity.turn_count >= SESSION_TURN_CAP
