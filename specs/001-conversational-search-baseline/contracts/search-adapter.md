# Contract: Search Adapter Interface

Originally drafted in Sprint 0 as method signatures only, no implementation, as the intended
boundary between a future conversational layer (State Manager) and the Search Engine (Sprint
1). **Audited and corrected on 2026-09-09**: the Sprint 1 implementation is `search()` only.
`validate_filter_value()` (below) was built speculatively ahead of any real caller — neither
`keyword_baseline.py` nor the HTTP endpoint ever called it — and has been removed from
`src/search_adapter/adapter.py`. It's kept here, clearly marked deferred, as a record of the
original intent, not as a spec for code that exists.

## Implemented today (Sprint 1)

```python
class SearchAdapter:
    def search(self, filters: FilterSet, limit: int = 20, offset: int = 0) -> SearchResult:
        """Convert a FilterSet into a Search Engine request and return matching
        products. MUST NOT loosen or drop any filter silently (FR-012) -- zero
        matches is a valid, correctly-reported SearchResult."""
```

```python
@dataclass
class FilterSet:
    category: str | None = None       # a canonical_category.slug, or None
    price_min: float | None = None
    price_max: float | None = None
    brand: str | None = None          # a canonical_brand.slug, resolved upstream by
                                       # parse_keyword_query's fuzzy resolver -- matched via
                                       # Product.brand_normalized, exact identity
                                       # (case-insensitive), not substring. Corrected
                                       # 2026-09: a contains-style ILIKE predicate let a short
                                       # canonical slug wrongly match unrelated brands sharing
                                       # its substring (e.g. "aqua" also matching
                                       # "aqua_delta"/"aquafina").
    query_text: str | None = None     # free-text search terms (added during Sprint 1 --
                                       # the original draft omitted this, but System A, the
                                       # keyword baseline, fundamentally needs free-text
                                       # search, which structured filters alone can't
                                       # express). Drives Stage 2 BM25 ranking (research.md
                                       # §2); has no effect on Stage 1 filtering.

    def __post_init__(self):
        """Raises InvalidFilterError if price_min > price_max -- direct
        structured construction only; the keyword baseline's own
        'between X and Y' text-parsing path auto-normalizes an inverted
        phrase before ever reaching this. Added 2026-09-09 in response to
        adversarial boundary testing, not speculative -- it guards
        FilterSet's own invariant for whichever caller constructs one
        today, not a future one."""

@dataclass
class SearchResult:
    products: list[Product]       # corpus Products only (FR-011) -- never synthesized
    total_count: int
    zero_result: bool             # explicit, not inferred from an empty list downstream
```

**Consumers today**: `src/search_engine/keyword_baseline.py` (System A) is the only real
caller, via `search_keyword()`. `src/api/routes.py` exposes it over HTTP.

## Deferred — not implemented, do not assume it exists

```python
    def validate_filter_value(self, attribute: str, value: str) -> ValidationOutcome:
        """Originally drafted intent: check a single proposed filter value
        against known Postgres values ahead of applying it (category: exact
        match against the canonical enum; brand: best-effort normalized
        match, never a hard reject -- FR-020; price: numeric validity)."""

@dataclass
class ValidationOutcome:
    accepted: bool
    resolved_value: str | None    # canonical form when accepted
    reason: str | None            # e.g. "not in catalog"
```

**Why removed rather than left as unused code**: an explicit audit (2026-09-09) found this
method and its two supporting query-layer functions (`resolve_category_slug`,
`resolve_brand`, formerly in `src/search_engine/query.py`) had zero real callers — only a
test written specifically to exercise them. They existed because the *original* draft of
this contract designed them for a Validation step that hasn't been built (Sprint 3's State
Manager). Sprint 1's actual FR-020 compliance (never hard-reject, never fabricate on a
missing brand) is fully proven by `search()` alone — a separate pre-check call isn't needed
for that. **When Sprint 3 actually needs filter validation**, design it from the State
Manager's real requirements at that point, not from this guess — this record exists so the
original reasoning isn't lost, not so it gets rebuilt unquestioned.
