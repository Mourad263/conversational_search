"""Sprint 0 rebuild-safety fixes (independent audit, 2026-09) to
brand_normalization_apply.py, unit-tested as pure functions -- no CSV, no
DB, no rebuild needed.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest  # noqa: E402

from src.ingestion.brand_normalization_apply import (  # noqa: E402
    resolve_backfill_slug,
    resolve_review_gate,
)


# --- resolve_review_gate: the generator/apply review-gate contract ---

@pytest.mark.parametrize("needs_review,reviewer_decision,expected", [
    (False, "", "apply"),                 # singleton/exact_normalized, and a
    (False, "approve", "apply"),          # fuzzy_cluster >= AUTO_ACCEPT_CUTOFF --
    (False, "reject", "apply"),           # needs_review=False always applies,
    (False, "anything", "apply"),         # regardless of any recorded decision
    (True, "approve", "apply"),
    (True, "reject", "reject"),
    (True, "", "pending"),                # no decision recorded yet
    (True, "pending", "pending"),         # any other non-approve/reject value
])
def test_resolve_review_gate(needs_review, reviewer_decision, expected):
    assert resolve_review_gate(needs_review, reviewer_decision) == expected


def test_real_current_junk_row_still_resolves_to_apply():
    """The one real junk_excluded row in the checked-in CSV
    ("Please select a brand.") has needs_review=True and
    reviewer_decision="approve" -- under the corrected rules it must
    still resolve to "apply" (excluded, unchanged from before this fix)."""
    assert resolve_review_gate(needs_review=True, reviewer_decision="approve") == "apply"


# --- resolve_backfill_slug: resolution-based EN->AR fallback ---

MAPPING = {"Juhayna": "juhayna", "جهينه": "juhayna", "Galaxy": "galaxy"}


def test_mapped_english_wins_even_when_arabic_also_resolves():
    assert resolve_backfill_slug("Juhayna", "جهينه", MAPPING) == "juhayna"


def test_unmapped_english_falls_back_to_mapped_arabic():
    """The exact bug this fixes: presence-based `brand_en or brand_ar`
    would have stopped at the non-empty (but unresolved) English value
    and never tried Arabic at all."""
    assert resolve_backfill_slug("SomeUnmappedBrand", "جهينه", MAPPING) == "juhayna"


def test_neither_mapped_stays_unresolved():
    assert resolve_backfill_slug("SomeUnmappedBrand", "غير معروف", MAPPING) is None


def test_only_english_present_and_mapped():
    assert resolve_backfill_slug("Galaxy", None, MAPPING) == "galaxy"


def test_only_arabic_present_and_mapped():
    assert resolve_backfill_slug(None, "جهينه", MAPPING) == "juhayna"


def test_both_absent_stays_unresolved():
    assert resolve_backfill_slug(None, None, MAPPING) is None
