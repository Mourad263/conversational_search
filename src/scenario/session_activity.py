"""Sprint 4 runtime/conversational metadata -- session_id -> SessionActivity.

Deliberately separate from src/state_manager/state_manager.py's
StateManager, which remains the sole authoritative owner of canonical user
search state (FilterSet: category/brand/query_text/price_min/price_max).
Nothing here duplicates those fields. This store only tracks what the
future conversational route (Part 3) needs from src/scenario/guard.py
(rapid-repeat/turn-cap bookkeeping) and src/scenario/decision.py
(recommendation-relaxation bookkeeping): the bounded raw-text history
understand() uses for its continuity judgment (src/understanding/llm.py's
HISTORY_WINDOW), plus a cumulative turn counter and a relaxation-step
counter that are pure runtime metadata, never part of the user's stated
search criteria.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.understanding.llm import HISTORY_WINDOW  # noqa: E402

SESSION_TTL_SECONDS = 45 * 60  # lazy inactivity TTL (Sprint 6 lifecycle task) -- no
# background worker: checked only on the next real access (SessionActivityStore.get()/
# is_expired()), against monotonic seconds (the same clock src/scenario/guard.py's
# rapid-repeat window already uses, threaded through via handle_message's own `now`).
# Within the requested 30-60 minute range; a plain module constant, not configurable,
# since this project has no config surface for it yet.


@dataclass
class TurnRecord:
    """One accepted conversational turn, kept for session-scoped memory
    (Sprint 6) -- deliberately NOT the LLM-context history, which stays
    hard-bounded to HISTORY_WINDOW. Only what's needed to answer "what did
    I say before"/"what was my first search": the raw text and the intent
    it resolved to. No product/brand/price copy here -- a "what did I
    mention" answer reads that from StateManager's own canonical,
    already-merged FilterSet instead of duplicating it (see
    src/response/messages.py's memory_recall_answer())."""

    message: str
    intent: str | None = None


@dataclass
class SessionActivity:
    history: list[str] = field(default_factory=list)  # raw user turns, oldest-first,
    # bounded to HISTORY_WINDOW -- see SessionActivityStore.append_history(). Deliberately
    # NOT the canonical FilterSet fields (category/brand/query_text/price_min/price_max);
    # those live only in StateManager.
    turns: list[TurnRecord] = field(default_factory=list)  # the SAME accepted turns as
    # `history`, appended at the same point (append_history), but deliberately UNBOUNDED --
    # session-scoped conversational memory (Sprint 6), distinct from the small window sent
    # to the LLM. Still session-scoped only: cleared by reset(), never persisted across
    # sessions, never sent to understand().
    last_message: str | None = None  # normalized text of the most recent request, for
    # src/scenario/guard.py's rapid-repeat check
    repeat_count: int = 0
    repeat_window_start: float = 0.0  # monotonic seconds
    turn_count: int = 0  # cumulative accepted conversational turns
    relaxation_step: int = 0  # src/scenario/decision.py's recommendation price-relaxation
    # step counter -- never the user's stated price
    last_active: float | None = None  # monotonic seconds of the last real access --
    # Sprint 6 lifecycle task's lazy-TTL clock (see SESSION_TTL_SECONDS); stamped only
    # by SessionActivityStore.get(session_id, now=...). None means "never stamped yet"
    # (a session touched only via bare get(session_id), e.g. some tests) -- deliberately
    # NOT 0.0: monotonic clocks are an arbitrary, often-large epoch (process/system
    # uptime), so treating an un-stamped session as "last active at time zero" would
    # make it look ancient -- and therefore already expired -- the instant a real `now`
    # is ever passed in, which is wrong for a session nothing has actually timed out.


class SessionActivityStore:
    """In-memory per-session store, same persistence posture as
    StateManager (a handful of concurrent conversations at this project's
    scale, no external persistence layer needed)."""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionActivity] = {}

    def get(self, session_id: str, now: float | None = None) -> SessionActivity:
        """An unseen session id starts with a completely empty/zeroed
        SessionActivity, created (and thereafter retained) on first
        access.

        Sprint 6 lifecycle task: when `now` is given and this session has
        been idle past SESSION_TTL_SECONDS, it is lazily reset first (same
        full wipe as reset()) before being returned -- an expired session
        must look exactly like a fresh one, memory included. `now` also
        stamps this access as the new last-activity time, refreshing the
        TTL. `now=None` (the default) skips both the expiry check and the
        stamp -- existing callers/tests that don't care about TTL are
        unaffected."""
        if now is not None and self.is_expired(session_id, now):
            self.reset(session_id)
        activity = self._sessions.setdefault(session_id, SessionActivity())
        if now is not None:
            activity.last_active = now
        return activity

    def is_expired(self, session_id: str, now: float) -> bool:
        """Peek-only (no mutation) -- lets a caller that owns OTHER
        per-session state tied to this same lifecycle (StateManager's
        shopping FilterSet) clear its own half before this store's next
        get() lazily wipes its own. False for a session never seen at all
        (nothing to expire)."""
        activity = self._sessions.get(session_id)
        if activity is None or activity.last_active is None:
            return False
        return (now - activity.last_active) > SESSION_TTL_SECONDS

    def append_history(self, session_id: str, message: str, intent: str | None = None) -> None:
        """Append one raw CURRENT user message to this session's
        continuity history, bounded to the last HISTORY_WINDOW entries --
        and, Sprint 6, to the same session's unbounded `turns` memory log
        (same call, same acceptance conditions, no separate call site to
        keep in sync).

        Callers (Part 3 orchestration) must only call this for a turn
        that: was not blocked by the System Guard, was successfully
        understood by the LLM, and resolved to an intent other than
        OFF_TOPIC. A NO_OP turn -- including a successful
        recommendation/exploration turn, and a memory-recall turn -- DOES
        get appended: it is real on-topic conversational content relevant
        to future continuity judgments (Sprint 4 design pass) and to
        future memory recall alike. `intent` is optional purely for
        pre-Sprint-6 callers/tests; omitting it just leaves that one
        TurnRecord's intent unset."""
        activity = self.get(session_id)
        activity.history.append(message)
        if len(activity.history) > HISTORY_WINDOW:
            del activity.history[: len(activity.history) - HISTORY_WINDOW]
        activity.turns.append(TurnRecord(message=message, intent=intent))

    def increment_turn_count(self, session_id: str) -> int:
        """Counts a successfully understood/accepted conversational turn
        (including OFF_TOPIC, which is accepted but not stored in
        continuity history). Callers must not call this for an oversized,
        rapid-repeat-blocked, or LLM/API-failed request."""
        activity = self.get(session_id)
        activity.turn_count += 1
        return activity.turn_count

    def reset_relaxation_step(self, session_id: str) -> None:
        """Any real canonical state-changing turn (search/add_filter/
        modify_filter/remove_filter) resets automatic price relaxation --
        the search criteria changed, so any previously widened budget no
        longer applies. Touches only relaxation_step -- see reset() for
        the full RESET-intent wipe."""
        self.get(session_id).relaxation_step = 0

    def reset(self, session_id: str) -> None:
        """Full runtime reset: history, turns (conversational memory),
        repeat bookkeeping, turn_count, relaxation_step, and last_active
        are all cleared together -- the next message in this session must
        behave exactly like a fresh, unseen session.

        Sprint 6 lifecycle task: a normal shopping "start over" (RESET
        intent) deliberately does NOT call this anymore -- it only clears
        StateManager's canonical FilterSet and this store's
        relaxation_step (see orchestrator.py's RESET branch), preserving
        conversation memory. This full wipe now fires only for genuine
        session expiration (get()/is_expired(), SESSION_TTL_SECONDS) --
        the one case where BOTH shopping state and conversational memory
        must actually disappear -- plus direct test use."""
        self._sessions[session_id] = SessionActivity()
