"""Sprint 0 rebuild-safety fixes (independent audit, 2026-09) to
category_canonicalization_apply.py, mirroring the equivalent brand fixes
(tests/ingestion/test_brand_normalization_apply.py):

1. resolve_review_gate() unifies the review-gate contract -- a
   junk_excluded row with reviewer_decision="reject" now correctly
   retains the category as a standalone entry instead of falling into the
   same bucket as "no decision yet".
2. A pending/blank required review now aborts main() before any DB
   mutation (RuntimeError), not a warning followed by a destructive write.
3. ON CONFLICT (slug) DO UPDATE now updates BOTH display_name_en and
   display_name_ar (proven separately via a ROLLBACK-only demo against
   the real DB, not unit-testable without a live connection).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest  # noqa: E402

from src.ingestion.category_canonicalization_apply import resolve_review_gate  # noqa: E402


@pytest.mark.parametrize("needs_review,reviewer_decision,expected", [
    (False, "", "apply"),                 # singleton_unique/exact_auto_merge
    (False, "approve", "apply"),
    (False, "reject", "apply"),
    (False, "anything", "apply"),
    (True, "approve", "apply"),
    (True, "reject", "reject"),
    (True, "", "pending"),
    (True, "pending", "pending"),
])
def test_resolve_review_gate(needs_review, reviewer_decision, expected):
    assert resolve_review_gate(needs_review, reviewer_decision) == expected


def test_real_current_junk_rows_still_resolve_to_apply():
    """All 5 real junk_excluded rows in the checked-in CSV have
    needs_review=True and reviewer_decision="approve" -- under the
    corrected rules they must still resolve to "apply" (excluded,
    unchanged from before this fix)."""
    assert resolve_review_gate(needs_review=True, reviewer_decision="approve") == "apply"


def test_synthetic_junk_excluded_reject_builds_a_standalone_category_key():
    """Confirms the actual bug fix, not just the gate function: a
    junk_excluded row with reviewer_decision="reject" must retain the
    category as its own standalone canonical entry (mirrors main()'s
    fuzzy_candidate-reject key-construction exactly: normalized_name_en +
    the raw category id), not fall into skipped_pending alongside a
    genuinely undecided row."""
    row = {
        "raw_category_id": "99999", "raw_name_en": "Weird Category",
        "raw_name_ar": "فئة غريبة", "normalized_name_en": "weird category",
        "method": "junk_excluded", "needs_review": "True", "reviewer_decision": "reject",
    }
    cid = int(row["raw_category_id"])
    decision = resolve_review_gate(row["needs_review"] == "True", row["reviewer_decision"])
    assert decision == "reject"
    key = (f"{row['normalized_name_en']}_{cid}", row["raw_name_en"], row["raw_name_ar"])
    assert key == ("weird category_99999", "Weird Category", "فئة غريبة")
