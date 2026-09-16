"""Sprint 3 end-to-end: Understanding (with conversation history) ->
Validation -> State Manager, run for real against the live LLM.

One realistic 8-turn conversation exercising all 5 intents plus a
GENUINELY implicit topic switch (turn 6: "Now I need detergent" -- no
"forget"/"never mind"/"start over" or any other discard wording at all,
just a plain statement of a different, unrelated product while a cheese
search is active). This must still be read as a new search that discards
the prior category/price state purely from the semantic topic change
(dairy -> cleaning products) plus conversation history, per research.md's
Sprint 3 design -- not from any explicit instruction to discard. Every
turn's full resolved state is asserted, not just the final one, so the
whole evolution is locked in.

Same live-API caveat as test_llm.py: not hermetic, not free, requires
OPENAI_API_KEY.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest  # noqa: E402

from src.models.config import settings  # noqa: E402
from src.search_adapter.adapter import FilterSet  # noqa: E402
from src.state_manager.state_manager import StateManager  # noqa: E402
from src.understanding.llm import understand  # noqa: E402
from src.validation.validate import validate  # noqa: E402

pytestmark = pytest.mark.skipif(
    not settings.openai_api_key,
    reason="OPENAI_API_KEY not configured -- Sprint 3 e2e test needs a real API call",
)

# (sentence, expected full state AFTER this turn is applied).
TURNS: list[tuple[str, FilterSet]] = [
    ("I am looking for milk under 50 pounds",
     FilterSet(category="milk_29", price_max=50.0)),
    ("also from Juhayna",
     FilterSet(category="milk_29", price_max=50.0, brand="juhayna")),
    ("actually make it under 30 instead",
     FilterSet(category="milk_29", price_max=30.0, brand="juhayna")),
    ("شيل فلتر البراند",
     FilterSet(category="milk_29", price_max=30.0)),
    # "خليها جبنة بدل اللبن" ("make it cheese instead of milk") -- same dairy
    # errand, read as modify_filter on the category, not a topic switch.
    ("خليها جبنة بدل اللبن",
     FilterSet(category="cheese", price_max=30.0)),
    # Genuinely implicit topic switch: no discard/reset wording anywhere in
    # this sentence -- an unrelated department (detergent, not dairy) stated
    # plainly must still be read as search from topic change alone, wiping
    # the active cheese/price state.
    ("Now I need detergent",
     FilterSet(category="detergents_19")),
    ("keep it under 100 pounds",
     FilterSet(category="detergents_19", price_max=100.0)),
    ("ابدأ من جديد",
     FilterSet()),
]


def test_full_multi_turn_conversation_end_to_end():
    mgr = StateManager()
    session_id = "e2e-test-conversation"
    history: list[str] = []

    for turn_index, (sentence, expected_state) in enumerate(TURNS, start=1):
        action = understand(sentence, history=history)
        resolved = validate(action)
        state = mgr.apply(session_id, action, resolved)

        assert state == expected_state, (
            f"turn {turn_index} ({sentence!r}): expected {expected_state}, got {state}"
        )
        history.append(sentence)
