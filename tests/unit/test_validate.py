"""Sprint 6 regression coverage for validate.py Findings B and C.
Deterministic -- real DB/catalog, no LLM call."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.search_engine.keyword_baseline import resolve_category_hint  # noqa: E402
from src.understanding.schema import Action, Intent  # noqa: E402
from src.validation.validate import validate  # noqa: E402


def test_ungrounded_free_from_is_surfaced_not_silently_dropped():
    """Finding B: an exclusion with no matching real "X Free" category
    must not silently vanish, and must NOT become a positive BM25 term
    (that would search FOR the excluded thing)."""
    action = Action(intent=Intent.SEARCH, raw_query_text="milk", category_hint="milk",
                     free_from="vanilla flavoring xyz123")
    filters = validate(action)
    assert filters.category == "milk_29"
    assert filters.unresolved_exclusion == "vanilla flavoring xyz123"
    assert filters.query_text is None or "vanilla" not in filters.query_text.lower()


def test_grounded_free_from_has_no_unresolved_exclusion():
    action = Action(intent=Intent.SEARCH, raw_query_text="chocolate",
                     category_hint="chocolate", free_from="sugar")
    filters = validate(action)
    assert filters.category == "sugar_free_1736"
    assert filters.unresolved_exclusion is None


def test_category_hint_grounding_does_not_depend_on_the_legacy_blocklist():
    """Finding C: "tomato paste" scores 80.0 against the real category
    "Pasta" (a legacy _CATEGORY_FUZZY_BLOCKLIST-style collision) -- must
    still fail to ground via the generic corpus-overlap check ALONE, with
    no query-specific blocklist entry involved."""
    assert resolve_category_hint("tomato paste") is None
    assert resolve_category_hint("olive oil") == "oil_5685"
    assert resolve_category_hint("milk") == "milk_29"
