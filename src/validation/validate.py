"""Validation stage (Sprint 2, tasks.md T026; rewritten in the Sprint 6
semantic-role refactor): grounds an Understanding-layer Action's SEMANTIC ROLES
against real catalog ground truth (244 categories, 974 brands).

The division of labour is now explicit:

    the LLM says what each span MEANS  (brand_text / category_hint /
                                        free_from / raw_query_text)
    this module says what actually EXISTS (canonical slugs, or None)

It no longer calls parse_keyword_query(). That function answers a
different question -- "given an arbitrary sentence with no role
information, guess which words are a brand and which are a category" --
and answering it from character similarity alone is what produced the
whole family of false-hijack bugs (peas -> the real brand Pears, paste ->
the real category Pasta, "extra virgin olive oil" -> the real brand
Extra). With roles supplied by the understanding layer there is nothing
left to guess here, only to look up.

Nothing the LLM produces is trusted as catalog truth: every canonical
slug returned below comes from matching against the live catalog, and a
hint that cannot be grounded resolves to None (leaving the search to
product text + BM25) rather than inventing a category or brand.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.search_adapter.adapter import FilterSet  # noqa: E402
from src.search_engine.keyword_baseline import (  # noqa: E402
    _normalize_for_fuzzy,
    resolve_brand_text,
    resolve_category_hint,
    resolve_free_from,
)
from src.understanding.schema import Action  # noqa: E402


def validate(action: Action) -> FilterSet:
    """Resolve an Action's semantic roles into a real FilterSet.

    A free-from exclusion takes precedence over a plain category hint when
    both are present and the exclusion actually grounds: "chocolate
    without sugar" must land on the real Sugar Free category, not on the
    positive Chocolate one. If the exclusion does NOT ground (no such
    "X Free" category exists in this catalog), the category hint is used
    normally and the exclusion survives as free text, so the request is
    never silently inverted into its opposite.

    query_text is dropped when the grounded category already says exactly
    the same thing as the product concept ("milk" -> category milk_29,
    query_text None): keeping it would add a redundant literal-text
    requirement on top of the category filter and can only lose real
    products. When the concept says MORE than the category does ("extra
    virgin olive oil" vs the category "Oil"), it is kept -- that extra
    wording is the whole reason the right products rank first.
    """
    category = resolve_free_from(action.free_from)
    category_from_hint = category is None
    # An exclusion that names a real free-from category is fully handled
    # above. One that does NOT (no matching "X Free" category exists) must
    # not be silently discarded (Finding B) -- there is no general NOT-
    # filter mechanism to enforce it with, so it is surfaced as an explicit,
    # unenforced signal instead of pretending it was applied.
    unresolved_exclusion = action.free_from if (action.free_from and category is None) else None
    if category_from_hint:
        category = resolve_category_hint(action.category_hint)

    brand = resolve_brand_text(action.brand_text)

    query_text = (action.raw_query_text or "").strip() or None
    # Only drop query_text when it duplicates the category the HINT itself
    # grounded to ("milk" -> category milk_29, hint "milk"). When category
    # instead came from a free_from exclusion, the hint never described
    # this category at all -- query_text is the only place the actual
    # product concept ("chocolate") survives, and dropping it would leave
    # a content-free "sugar-free anything" search.
    if query_text and category_from_hint and category is not None and action.category_hint:
        if _normalize_for_fuzzy(query_text) == _normalize_for_fuzzy(action.category_hint):
            query_text = None

    return FilterSet(
        category=category,
        brand=brand,
        price_min=action.price_min,
        price_max=action.price_max,
        query_text=query_text,
        unresolved_exclusion=unresolved_exclusion,
    )
