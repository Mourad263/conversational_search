# Phase 1 Data Model: Conversational Search Baseline

Derived from spec.md's Key Entities, corrected against the real schema in
`data/spinneys_database.sql`. This is the target PostgreSQL shape the Sprint 0 load produces
— not a mirror of the source MySQL tables.

## Product

| Field | Type | Notes |
|---|---|---|
| `id` | int, PK | From `catalog_product.id` |
| `sku` | text, unique | From `catalog_product.sku` |
| `name_en` | text | From `catalog_productname` (language='English'); present for 100% of products |
| `name_ar` | text | From `catalog_productname` (language='Arabic'); present for 100% of products |
| `url_key` | text, nullable | Secondary/fallback text-search signal only; descriptive for 74.5% of products |
| `price` | numeric | From `catalog_product.default_price` — **not** the per-source-code `catalog_productprice` table (out of scope, inventory-adjacent) |
| `special_price` | numeric, nullable | From `catalog_product.default_special_price` |
| `brand_raw_en` | text, nullable | Extracted from the English-language `catalog_productattributes` row's JSON field `product_brand_id` (an inconsistently-named but real free-text brand string) |
| `brand_raw_ar` | text, nullable | Same, from the Arabic-language attributes row. Kept as two separate columns rather than merged — which script a brand value is written in is not reliably predicted by the attributes row's declared language (either script has been observed under either row); non-empty in at least one of the two raw columns for 95.9% of products (24,820 / 25,881) — corrected from a stale "97.2%" figure, verified directly against the live table |
| `brand_normalized` | text, nullable | Looked up via `BrandAlias` after Sprint 0 canonicalization (research.md §6); the field name is kept for compatibility with the SearchAdapter contract's `Product.brand_normalized`. Resolved for ~67% of products (17,315 / 25,881) — lower than raw presence above because ~30% of raw-brand-bearing products (7,505) carry only the literal placeholder "Please select a brand." in both language columns, excluded as junk rather than treated as a real brand (research.md §6) |
| `image_url` | text, nullable | From `catalog_product.image` |

**Validation rules**: `price` MUST be present and non-negative to be filterable by price
(FR-001). A product with no linked category is still a valid, searchable Product (research.md
§4) — it simply cannot match a category filter.

## Category

Refined from a flat `canonical_value` text field (as originally drafted here) into a proper
relational shape — a `canonical_category` enum table plus a FK from the raw records, so the
canonicalization mapping itself is queryable/auditable, not just a derived string.

| Field | Type | Notes |
|---|---|---|
| `id` | int, PK | From `catalog_category.id` (preserved, not resequenced) |
| `parent_category_id` | int, nullable, FK -> Category.id | From `catalog_category.parent_category_id`. **Correction**: this column is `NULL` for all 272 rows in the actual dump (verified directly) — there is no usable hierarchy signal in this dataset despite the column's presence; kept in the schema for forward compatibility only, not relied on by canonicalization (research.md §5) |
| `name_en` | text | From `catalog_categoryname` (language='English') |
| `name_ar` | text | From `catalog_categoryname` (language='Arabic') |
| `canonical_category_id` | int, nullable, FK -> CanonicalCategory.id | Sprint 0 canonicalization output (research.md §5); `NULL` for junk/non-product records |
| `is_junk` | boolean | Explicit flag for junk ("test" variant) records, set independently of the FK being null, so "junk" and "not yet canonicalized" are never ambiguous |

## CanonicalCategory

| Field | Type | Notes |
|---|---|---|
| `id` | int, PK | |
| `slug` | text, unique | Stable machine key, e.g. `meat` — this is the enum value Validation and Filter.value check against |
| `display_name_en` / `display_name_ar` | text | From the chosen representative raw record |

**Validation rules**: Every category record used as a filter target MUST resolve to a
`CanonicalCategory` via `canonical_category_id`; category records identified as junk ("test"
variants) MUST NOT appear in the canonical enum exposed to Validation (`is_junk = TRUE`,
`canonical_category_id = NULL`).

## CanonicalBrand / BrandAlias

Mirrors the CanonicalCategory pattern (research.md §6), sized for ~1,700 raw brand strings
rather than 272 — auto-accepted high-confidence clusters plus a smaller human-reviewed band,
not a fully manual enum like category.

| Entity | Field | Type | Notes |
|---|---|---|---|
| CanonicalBrand | `id` | int, PK | |
| | `slug` | text, unique | |
| | `display_name` | text | Most-frequent raw spelling in the cluster |
| | `method` | enum: `exact_normalized` \| `fuzzy_cluster` | |
| | `confidence` | numeric, nullable | Cluster's minimum pairwise rapidfuzz score; null for exact merges |
| BrandAlias | `raw_value` | text, PK | A distinct raw brand string observed in the source |
| | `normalized_value` | text | Post-normalization, pre-fuzzy |
| | `script` | enum: `latin` \| `arabic` | Fuzzy clustering never crosses this boundary (research.md §6) |
| | `canonical_brand_id` | int, FK -> CanonicalBrand.id | |

## ProductCategory (link)

| Field | Type | Notes |
|---|---|---|
| `product_id` | int, FK -> Product.id | |
| `category_id` | int, FK -> Category.id | Many-to-many; a product may link to 0–14 categories (avg 2.4 for linked products; 19.1% link to none) |

## SearchSession

| Field | Type | Notes |
|---|---|---|
| `id` | uuid, PK | |
| `created_at` / `updated_at` | timestamp | |
| `active_filters` | jsonb | The current Filter set (see below) |
| `last_result_set` | jsonb | Product IDs from the most recent search, for implicit reference resolution ("cheaper ones") |
| `last_intent` | text | For FR-013 traceability |
| `languages_used` | text[] | Tracks EN/AR/mixed usage within the session |

**State transitions**: add / modify / remove / reset, applied only by the deterministic State
Manager (never directly by the LLM). A topic switch (e.g. chocolate -> cleaning products) is
treated as an implicit reset of `active_filters` (plan.md §4).

## Filter

| Field | Type | Notes |
|---|---|---|
| `attribute` | enum: `category` \| `price_min` \| `price_max` \| `brand` | Only these four are supported filter attributes for this catalog (color/size are not — see spec.md Key Entities) |
| `comparison` | enum: `eq` \| `lte` \| `gte` \| `contains` | `contains` is used for the brand best-effort text match |
| `value` | text | For `category`, MUST validate against `Category.canonical_value`; for `brand`, matched against `Product.brand_normalized` |

## EvaluationQuery / EvaluationTask

| Field | Type | Notes |
|---|---|---|
| `id` | text, PK | Versioned identifier |
| `language` | enum: `en` \| `ar` | |
| `turns` | jsonb | One turn (single-turn query) or an ordered list (multi-turn task) |
| `expected_filters` | jsonb | Ground truth for SC-002/SC-004 scoring |
| `is_ambiguous` | boolean | Ground truth for SC-005 scoring |

## EvaluationResult

| Field | Type | Notes |
|---|---|---|
| `query_id` | FK -> EvaluationQuery.id | |
| `system` | enum: `conversational` \| `keyword_baseline` | |
| `success` | boolean | Per the Sprint 6 rubric (LLM-as-judge, offline/batch — see plan.md Sprint 6 open item) |
| `zero_result` | boolean | |
| `follow_up_success` | boolean, nullable | Only applicable to multi-turn tasks; for the keyword baseline this is recorded as a measured failure (no context carried), not skipped (spec.md User Story 5, Acceptance Scenario 2) |
| `conversion` | boolean, nullable | Only populated where real transaction/interaction data exists (FR-017); otherwise left null and reported as an unmeasured hypothesis, never a fabricated number |
