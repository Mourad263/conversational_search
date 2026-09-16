"""Sprint 0: brand canonicalization, apply step (research.md §6, step 8).

Reads the (partially) human-reviewed brand_canonicalization_review.csv and
writes canonical_brand/brand_alias rows, then back-fills
product.brand_normalized. This is the only script that writes brand
canonicalization results to Postgres.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import psycopg  # noqa: E402

from src.models.config import settings  # noqa: E402

CSV_PATH = Path(__file__).resolve().parents[2] / "specs" / "001-conversational-search-baseline" / "brand_canonicalization_review.csv"


def resolve_review_gate(needs_review: bool, reviewer_decision: str) -> str:
    """The generator/apply review-gate contract, made explicit and uniform
    across every method (junk_excluded, fuzzy_cluster -- singleton/
    exact_normalized never set needs_review=True at all, so they never
    reach this function).

    - needs_review=False: the generator's own automatic decision is used
      as-is -- no reviewer_decision required (fixes a real, confirmed
      latent bug: a fuzzy_cluster row at/above AUTO_ACCEPT_CUTOFF used to
      still require an explicit "approve" despite needs_review=False).
    - needs_review=True and reviewer_decision=="approve": apply the
      proposed mapping.
    - needs_review=True and reviewer_decision=="reject": do NOT apply the
      proposed mapping (caller falls back to a standalone entry).
    - needs_review=True and no decision recorded: "pending" -- caller
      must abort the whole apply run before any database mutation, not
      warn and continue (a real, confirmed gap this replaces: the apply
      script used to print a warning and proceed straight into a
      destructive TRUNCATE + rewrite anyway).
    """
    if not needs_review:
        return "apply"
    if reviewer_decision == "approve":
        return "apply"
    if reviewer_decision == "reject":
        return "reject"
    return "pending"


def resolve_backfill_slug(
    brand_en: str | None, brand_ar: str | None, raw_to_canonical_slug: dict[str, str]
) -> str | None:
    """Resolution-based EN->AR fallback for product.brand_normalized:
    prefer the English raw value, but only when it actually RESOLVES to a
    canonical brand -- not merely when it's non-empty. Falls back to the
    Arabic raw value (if it resolves) when English doesn't. Fixes a real,
    confirmed latent bug: the old `brand_en or brand_ar` fell back on
    presence alone, so a product with an unmapped English value and a
    perfectly resolvable Arabic value never even tried the Arabic one
    (confirmed: 0 products in the current dataset actually hit this case
    -- every unresolved-English product's Arabic value is the identical
    junk placeholder, "Please select a brand." -- so this is a latent
    correctness fix, not a change to today's resolved products)."""
    if brand_en and brand_en in raw_to_canonical_slug:
        return raw_to_canonical_slug[brand_en]
    if brand_ar and brand_ar in raw_to_canonical_slug:
        return raw_to_canonical_slug[brand_ar]
    return None


def main() -> None:
    with CSV_PATH.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    clusters: dict[str, list[dict]] = {}
    for r in rows:
        if r["cluster_id"]:
            clusters.setdefault(r["cluster_id"], []).append(r)

    # (slug, display, method, confidence) -> [(raw_value, normalized_value, script), ...]
    canonical_assignments: dict[tuple[str, str, str, str], list[tuple[str, str, str]]] = {}
    skipped_pending: list[str] = []

    junk_count = 0
    for r in rows:
        raw = r["raw_brand_value"]
        method = r["method"]

        if method == "junk_excluded":
            # needs_review is always True for this method (generator) --
            # requires an explicit reviewer_decision same as fuzzy_cluster.
            decision = resolve_review_gate(r["needs_review"] == "True", r["reviewer_decision"])
            if decision == "pending":
                skipped_pending.append(raw)
            elif decision == "reject":
                # Reviewer determined this ISN'T actually junk -- stand
                # alone as its own canonical entry (same fallback pattern
                # as a rejected fuzzy_cluster proposal below), since a
                # junk_excluded row has no proposed_canonical_slug to fall
                # back on.
                key = (f"{r['normalized_value']}_{r['script']}_singleton", raw,
                       "exact_normalized", "")
                canonical_assignments.setdefault(key, []).append((raw, r["normalized_value"], r["script"]))
            else:  # "apply" -- confirmed junk. Never gets a canonical_brand
                # -- products carrying only a junk raw value end up with
                # brand_normalized = NULL (see the reset below), i.e. "no
                # brand recorded," not a fabricated bucket.
                junk_count += 1
            continue

        if method == "singleton":
            key = (r["proposed_canonical_slug"], r["proposed_canonical_display"],
                   "exact_normalized", "")
            canonical_assignments.setdefault(key, []).append((raw, r["normalized_value"], r["script"]))
            continue

        if method == "exact_normalized":
            key = (r["proposed_canonical_slug"], r["proposed_canonical_display"],
                   "exact_normalized", "")
            canonical_assignments.setdefault(key, []).append((raw, r["normalized_value"], r["script"]))
            continue

        if method == "fuzzy_cluster":
            needs_review = r["needs_review"] == "True"
            if not needs_review:
                # AUTO_ACCEPT_CUTOFF-eligible -- the generator already
                # decided this doesn't need a human reviewer_decision at
                # all (no current row exercises this path, but the gate
                # must not require "approve" regardless of needs_review).
                key = (r["proposed_canonical_slug"], r["proposed_canonical_display"],
                       "fuzzy_cluster", r["cluster_min_confidence"])
                canonical_assignments.setdefault(key, []).append((raw, r["normalized_value"], r["script"]))
                continue
            group = clusters[r["cluster_id"]]
            decisions = {g["reviewer_decision"] for g in group}
            if decisions == {"approve"}:
                key = (r["proposed_canonical_slug"], r["proposed_canonical_display"],
                       "fuzzy_cluster", r["cluster_min_confidence"])
                canonical_assignments.setdefault(key, []).append((raw, r["normalized_value"], r["script"]))
            elif "reject" in decisions:
                key = (f"{r['normalized_value']}_{r['script']}_singleton", raw,
                       "exact_normalized", "")
                canonical_assignments.setdefault(key, []).append((raw, r["normalized_value"], r["script"]))
            else:
                skipped_pending.append(raw)
            continue

    if skipped_pending:
        # Fail-safe, not warn-and-continue: abort before the DB is even
        # opened, let alone TRUNCATEd -- a real, confirmed gap this
        # replaces (the old warning printed here but the script still
        # proceeded straight into a destructive rewrite).
        raise RuntimeError(
            f"{len(skipped_pending)} brand values need a reviewer_decision before this can "
            f"run (aborting before any database mutation): {skipped_pending}"
        )

    url = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        # Cross-script merge: brand_normalization.py clusters English and
        # Arabic raw brand values SEPARATELY (fuzzy string matching can't
        # compare across scripts), so the same real brand's EN and AR
        # spellings land in two different canonical_assignments keys by
        # default -- e.g. 'Juhayna' and 'جهينه' were two unrelated
        # canonical_brand rows. A product carrying BOTH an EN and an AR raw
        # value is real ground truth that they're the same brand. Found via
        # a real bug: brand_normalized was always backfilled from a
        # product's English raw value when both existed (see below), so the
        # Arabic-only canonical entry was invisibly orphaned -- 0 real
        # products ever carried its slug, breaking Arabic brand search even
        # once the slug itself was made readable. Merge before inserting.
        raw_to_key: dict[tuple[str, str, str, str], tuple[str, str, str, str]] = {}
        for key, members in canonical_assignments.items():
            for raw, _normalized, _script in members:
                raw_to_key[raw] = key

        cur.execute(
            "SELECT DISTINCT brand_raw_en, brand_raw_ar FROM product "
            "WHERE brand_raw_en IS NOT NULL AND brand_raw_en != '' "
            "AND brand_raw_ar IS NOT NULL AND brand_raw_ar != ''"
        )
        parent: dict[tuple, tuple] = {}

        def find(k: tuple) -> tuple:
            while parent.get(k, k) != k:
                k = parent[k]
            return k

        def union(a: tuple, b: tuple) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        for en, ar in cur.fetchall():
            key_en, key_ar = raw_to_key.get(en), raw_to_key.get(ar)
            if key_en and key_ar and key_en != key_ar:
                union(key_en, key_ar)

        groups: dict[tuple, list[tuple]] = {}
        for key in canonical_assignments:
            groups.setdefault(find(key), []).append(key)

        n_cross_script_merges = 0
        merged_assignments: dict[tuple, list] = {}
        for root, group_keys in groups.items():
            members = [m for k in group_keys for m in canonical_assignments[k]]
            if len(group_keys) > 1:
                n_cross_script_merges += len(group_keys) - 1
                # Keep the Latin-script key's (slug, display) as the
                # surviving canonical identity -- matches the existing
                # "prefer English" convention used for the product
                # backfill below -- else fall back to the union-find root.
                latin_keys = [k for k in group_keys if canonical_assignments[k][0][2] == "latin"]
                primary = latin_keys[0] if latin_keys else root
            else:
                primary = group_keys[0]
            merged_assignments[primary] = members
        canonical_assignments = merged_assignments
        if n_cross_script_merges:
            print(f"Cross-script brand merges (same real brand, EN+AR raw values "
                  f"co-occur on real products): {n_cross_script_merges}")

        cur.execute("TRUNCATE brand_alias, canonical_brand RESTART IDENTITY CASCADE")

        raw_to_canonical_slug: dict[str, str] = {}
        n_assignments_processed = 0
        for (slug, display, method, confidence), members in canonical_assignments.items():
            cur.execute(
                """INSERT INTO canonical_brand (slug, display_name, method, confidence)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (slug) DO UPDATE SET display_name = EXCLUDED.display_name
                   RETURNING id""",
                (slug, display, method, float(confidence) if confidence else None),
            )
            canonical_id = cur.fetchone()[0]
            n_assignments_processed += 1
            for raw, normalized, script in members:
                cur.execute(
                    """INSERT INTO brand_alias (raw_value, normalized_value, script, canonical_brand_id)
                       VALUES (%s, %s, %s, %s)
                       ON CONFLICT (raw_value) DO UPDATE SET canonical_brand_id = EXCLUDED.canonical_brand_id""",
                    (raw, normalized, script, canonical_id),
                )
                raw_to_canonical_slug[raw] = slug

        # Reset first -- without this, a product whose only brand value is
        # now junk-excluded (or otherwise absent from this run's mapping)
        # would keep whatever stale brand_normalized a PREVIOUS run wrote,
        # silently surviving a canonicalization change meant to remove it.
        cur.execute("UPDATE product SET brand_normalized = NULL")

        # Back-fill product.brand_normalized: prefer the English brand value,
        # fall back to Arabic (research.md §6 -- script isn't reliably
        # predicted by the attributes row's declared language, but for a
        # single display value we need to pick one consistently).
        cur.execute("SELECT id, brand_raw_en, brand_raw_ar FROM product")
        updates = [
            (slug, pid)
            for pid, brand_en, brand_ar in cur.fetchall()
            if (slug := resolve_backfill_slug(brand_en, brand_ar, raw_to_canonical_slug)) is not None
        ]
        cur.executemany("UPDATE product SET brand_normalized = %s WHERE id = %s", updates)

        # Two DIFFERENT canonical_assignments keys can slugify to the same
        # string (e.g. "M.Design"/"M-Design" both -> "m_design") and
        # collapse into one row via ON CONFLICT -- n_assignments_processed
        # counts loop iterations, not distinct rows, so it previously
        # overstated the real canonical_brand count (confirmed live: a
        # real apply run printed "976 ... created" while the table held
        # 974). Query the actual row count instead of assuming they match.
        cur.execute("SELECT COUNT(*) FROM canonical_brand")
        n_canonical_brand_rows = cur.fetchone()[0]

        conn.commit()

    print(f"Applied: {n_canonical_brand_rows} canonical_brand rows now in the database "
          f"({n_assignments_processed} slug assignments processed), "
          f"{sum(len(v) for v in canonical_assignments.values())} raw brand values aliased, "
          f"{junk_count} raw brand values excluded as junk, "
          f"{len(updates)} products back-filled with brand_normalized.")


if __name__ == "__main__":
    main()
