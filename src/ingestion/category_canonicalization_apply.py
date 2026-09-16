"""Sprint 0: category canonicalization, apply step (research.md §5, step 6).

Reads the human-reviewed category_canonicalization_review.csv and writes
canonical_category rows + category.canonical_category_id/is_junk. This is
the only script that writes canonicalization results to Postgres.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import psycopg  # noqa: E402

from src.models.config import settings  # noqa: E402

CSV_PATH = Path(__file__).resolve().parents[2] / "specs" / "001-conversational-search-baseline" / "category_canonicalization_review.csv"


def resolve_review_gate(needs_review: bool, reviewer_decision: str) -> str:
    """The generator/apply review-gate contract, made explicit and uniform
    across every method (junk_excluded, fuzzy_candidate -- singleton_unique/
    exact_auto_merge never set needs_review=True at all, so they never
    reach this function). Identical contract to
    brand_normalization_apply.resolve_review_gate -- duplicated rather
    than imported since each apply script is deliberately self-contained
    (each is "the only script that writes X canonicalization results").

    - needs_review=False: the generator's own automatic decision is used
      as-is -- no reviewer_decision required.
    - needs_review=True and reviewer_decision=="approve": apply the
      proposed mapping.
    - needs_review=True and reviewer_decision=="reject": do NOT apply the
      proposed mapping (caller falls back to a standalone entry).
    - needs_review=True and no decision recorded: "pending" -- caller
      must abort the whole apply run before any database mutation, not
      warn and continue (a real, confirmed gap this replaces).
    """
    if not needs_review:
        return "apply"
    if reviewer_decision == "approve":
        return "apply"
    if reviewer_decision == "reject":
        return "reject"
    return "pending"


def main() -> None:
    with CSV_PATH.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    # group_id -> list of rows, for exact_auto_merge and approved fuzzy_candidate
    groups: dict[str, list[dict]] = {}
    for r in rows:
        if r["group_id"]:
            groups.setdefault(r["group_id"], []).append(r)

    # (slug, display_en, display_ar) -> [raw_category_id, ...]
    canonical_assignments: dict[tuple[str, str, str], list[int]] = {}
    junk_ids: list[int] = []
    skipped_pending: list[int] = []

    for r in rows:
        cid = int(r["raw_category_id"])
        method = r["method"]

        if method == "junk_excluded":
            # needs_review is always True for this method (generator) --
            # requires an explicit reviewer_decision same as fuzzy_candidate.
            decision = resolve_review_gate(r["needs_review"] == "True", r["reviewer_decision"])
            if decision == "pending":
                skipped_pending.append(cid)
            elif decision == "reject":
                # Reviewer determined this ISN'T actually junk -- retain it
                # as a normal standalone canonical category (same fallback
                # pattern as a rejected fuzzy_candidate below), since a
                # junk_excluded row has no proposed_canonical_slug to fall
                # back on.
                key = (f"{r['normalized_name_en']}_{cid}", r["raw_name_en"], r["raw_name_ar"])
                canonical_assignments.setdefault(key, []).append(cid)
            else:  # "apply" -- confirmed junk.
                junk_ids.append(cid)
            continue

        if method == "singleton_unique":
            # cid suffix guarantees slug uniqueness even if two distinct raw
            # names happen to slugify identically (e.g. differing only in
            # punctuation the slug regex collapses).
            key = (f"{r['proposed_canonical_slug']}_{cid}", r["raw_name_en"], r["raw_name_ar"])
            canonical_assignments.setdefault(key, []).append(cid)
            continue

        if method == "exact_auto_merge":
            # No review required -- always applied.
            key = (r["proposed_canonical_slug"], r["proposed_canonical_display_en"],
                   r["proposed_canonical_display_ar"])
            canonical_assignments.setdefault(key, []).append(cid)
            continue

        if method == "fuzzy_candidate":
            needs_review = r["needs_review"] == "True"
            if not needs_review:
                # No current row exercises this path (see brand's
                # equivalent fix), but the gate must not require "approve"
                # regardless of needs_review.
                key = (r["proposed_canonical_slug"], r["proposed_canonical_display_en"],
                       r["proposed_canonical_display_ar"])
                canonical_assignments.setdefault(key, []).append(cid)
                continue
            group = groups[r["group_id"]]
            decisions = {g["reviewer_decision"] for g in group}
            if decisions == {"approve"}:
                key = (r["proposed_canonical_slug"], r["proposed_canonical_display_en"],
                       r["proposed_canonical_display_ar"])
                canonical_assignments.setdefault(key, []).append(cid)
            elif decisions == {"reject"} or "reject" in decisions:
                # Rejected: each member becomes its own singleton canonical category.
                key = (f"{r['normalized_name_en']}_{cid}", r["raw_name_en"], r["raw_name_ar"])
                canonical_assignments.setdefault(key, []).append(cid)
            else:
                skipped_pending.append(cid)
            continue

    if skipped_pending:
        # Fail-safe, not warn-and-continue: abort before the DB is even
        # opened, let alone mutated -- a real, confirmed gap this
        # replaces (the old warning printed here but the script still
        # proceeded straight into a destructive rewrite).
        raise RuntimeError(
            f"{len(skipped_pending)} categories have no reviewer_decision yet "
            f"(aborting before any database mutation): {skipped_pending}"
        )

    url = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute("UPDATE category SET canonical_category_id = NULL, is_junk = FALSE")

        if junk_ids:
            cur.execute("UPDATE category SET is_junk = TRUE WHERE id = ANY(%s)", (junk_ids,))

        n_canonical = 0
        for (slug, display_en, display_ar), cat_ids in canonical_assignments.items():
            cur.execute(
                """INSERT INTO canonical_category (slug, display_name_en, display_name_ar)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (slug) DO UPDATE SET display_name_en = EXCLUDED.display_name_en,
                                                     display_name_ar = EXCLUDED.display_name_ar
                   RETURNING id""",
                (slug, display_en, display_ar),
            )
            canonical_id = cur.fetchone()[0]
            cur.execute(
                "UPDATE category SET canonical_category_id = %s WHERE id = ANY(%s)",
                (canonical_id, cat_ids),
            )
            n_canonical += 1

        conn.commit()

    print(f"Applied: {n_canonical} canonical_category rows created/updated, "
          f"{len(junk_ids)} categories marked junk, "
          f"{sum(len(v) for v in canonical_assignments.values())} categories assigned a canonical value.")


if __name__ == "__main__":
    main()
