# Phase 0 Research: Conversational Search Baseline

## 1. LLM provider

**Decision**: OpenAI (confirmed). Specific model choice within OpenAI's lineup is
deferred to Sprint 2 kickoff, not locked in here or in tasks.md.

**Rationale**: The plan's own architecture (Section 2, "one LLM doing two distinct jobs")
does not depend on a specific model — it only requires reliable schema-constrained JSON
output (OpenAI's structured outputs / JSON mode) and reasonable EN/AR quality. The real
model-selection criteria (EN/AR quality, structured-output reliability, cost per turn) are
exactly what Sprint 2's isolated utterance-set test is designed to surface, so that narrower
choice belongs there, evidence-backed, once API access is available — not guessed now.

**Alternatives considered**: Locking a specific OpenAI model now — rejected, no evidence yet
to choose between them; that choice belongs to Sprint 2's test, not this document. Using two
different models for the two jobs — explicitly deferred per the plan ("a second LLM is
something to add later only if evaluation shows a specific failure mode a single model can't
fix").

## 2. Search engine retrieval/ranking approach (Sprint 1)

**Decision**: **Hybrid** (confirmed by the user after reviewing the tradeoff below). Stage 1
— Postgres does cheap structured filtering only, no ranking: category (expanded through the
canonical-category mapping to every equivalent raw record, FR-019), price range, and an exact
match (case-insensitive) on the canonicalized `brand_normalized` column. **Corrected 2026-09**:
this stage originally used a `pg_trgm`-indexed `ILIKE` pass for a "best-effort" brand match,
but since `brand` reaching this stage is always an already-resolved `canonical_brand.slug`
(the fuzzy/best-effort matching happens earlier, in `parse_keyword_query`'s resolver -- see
§6), a substring match here only risked collisions between distinct real brands sharing a
substring (confirmed live: "aqua" wrongly matching "aqua_delta"/"aquafina"/"aquafresh"). No
`LIMIT`/`OFFSET` at this
stage — pagination before ranking would silently drop products that rank lower but still
match every stated filter, the same failure mode FR-012 prohibits for filter-loosening.
Stage 2 — a hand-rolled Python BM25 ranker, built over an in-memory token index of
`catalog_productname` (EN + AR, `url_key` as a fallback signal), scores only the Stage-1
candidate set, with exact-SKU/`url_key` boosting, then the final `[offset:limit]` slice is
applied after sorting.

**Rationale**: The instructor's explicit first ask is a from-scratch engine, not a wrapped
one — so the graded, novel part (tokenization, EN/AR handling, relevance ranking) stays
hand-rolled Python, not delegated to Postgres's `tsvector`/`ts_rank`. But category and price
are exact structured constraints, not fuzzy-ranked signals, and Postgres already does
indexed range/equality filtering correctly and cheaply at this corpus size (25,881 rows) —
reimplementing that in Python would be reinventing infrastructure for no benefit, and would
make combining "hard filter" with "ranked text match" more error-prone, not less. Corpus-wide
BM25 statistics (IDF, average doc length) are computed once over the full 25,881-product
corpus, not recomputed per-query over the filtered subset — recomputing them per query would
make relevance scores shift turn to turn in ways that actively work against multi-turn
refinement (FR-002/FR-003).

**Alternatives considered** (the full three-way tradeoff, as presented to and decided by the
user): **Pure hand-rolled** (a complete in-Python inverted index, Postgres used only as raw
storage, no `pg_trgm`/FTS at all) — most unambiguously "from scratch," but reimplements
filtering infrastructure Postgres already provides well, for no accuracy benefit. **Postgres
native FTS** (`tsvector`/`tsquery` + GIN index + `ts_rank`, `pg_trgm` for fuzzy tolerance) —
fastest to build, one SQL query does filter+rank together, but Postgres ships no Arabic
stemming configuration (Arabic would fall back to the `simple` config, no morphological
matching), and it sits closer to "wrapping an existing search engine" than the instructor's
ask intends. Pure substring/exact match only — rejected earlier and still rejected, too weak
a baseline to be a meaningful System A.

**Tokenization, concretely**: classify each token by Unicode block before normalizing
(Arabic-range → Arabic path, else → Latin path), so a mixed-script query (spec.md's explicit
edge case, e.g. "استرا شوكولاتة Munchi") doesn't have one script's normalizer mangling the
other's tokens. Latin path: NFKC, lowercase, strip punctuation, light plural-suffix trim (not
a full stemmer, to stay inspectable per Constitution Principle IV). Arabic path: NFKC, strip
diacritics/harakat and tatweel, normalize alef variants (`أ إ آ ٱ` → `ا`) and `ى` → `ي`; taa
marbuta (`ة` vs `ه`) is deliberately left un-normalized — flagged as an open linguistic call,
not silently resolved, since collapsing it can change which real word is meant. Stopword
removal is skipped for MVP (product names are short; revisit only if evaluation shows it
matters) — also flagged as open, not silently decided.

**Open implementation note**: the in-memory BM25 index is a single-process, prototype-scale
choice — simplest and most debuggable at 25,881 products (Principle IV), but would need a
shared/rebuildable index strategy before any multi-worker production deployment (see plan.md
§6 production-readiness notes, which already flag the analogous in-memory-session-state
issue).

**Gap found via live testing, fixed**: a filter-only query (category and/or price, no free
text) has no BM25 score to sort by, and the original implementation returned Stage-1
candidates in whatever order Python's `set` iteration happened to produce — not price, not
name, nothing a shopper would recognize as an order. Fixed: when `query_text` is empty,
results sort by price ascending (nulls last) instead. This is a reasonable, low-risk default
for a shopping search engine, not a deep design question, so it was resolved directly rather
than escalated — flagged here for visibility since it was a genuine, previously-unnoticed gap,
not a pre-existing decision.

## 3. Brand normalization approach (Sprint 0)

**Decision** (widened from the original "exact-normalized only" call, per explicit
instruction to use `rapidfuzz`): (1) extract the `product_brand_id` string value per product
from `catalog_productattributes` JSON, keeping the English-attributes-row and
Arabic-attributes-row values as separate columns (`brand_raw_en`/`brand_raw_ar`) rather than
merged — a script (Arabic vs. Latin) is not reliably predicted by which language row it came
from, spot-checks show either script appearing under either row; (2) normalize per script
(Latin: NFKC/lowercase/trim/strip punctuation; Arabic: NFKC + diacritic/tatweel/alef-variant
normalization, same rules as the search tokenizer in §2); (3) auto-merge exact-normalized
matches (cheap, ~zero false-merge risk); (4) run `rapidfuzz` fuzzy clustering *within each
script bucket only* (never comparing an Arabic string to a Latin one — they can't legitimately
match under edit-distance similarity) using `token_sort_ratio` with a 90 cutoff, union-find
over qualifying pairs; (5) auto-accept clusters at similarity ≥97 without review; flag only
the 90–96.9 band for a human spot-check, rather than reviewing all ~1,700 raw strings the way
every category near-duplicate is reviewed.

**Rationale**: At ~1,700 distinct raw strings (vs. 272 category records), full manual review
of every merge is disproportionate and would contradict the original effort/value rationale
below — but leaving near-duplicate spellings ("Nescafe" / "nescafé" / "Nescafe ") entirely
unmerged, as the earlier decision did, throws away matching quality rapidfuzz can recover
cheaply. The differentiated review policy (auto-accept high-confidence clusters, review only
the narrower uncertain band) is safe specifically *because* brand is already committed
(FR-020, Key Entities) to best-effort/normalized-text matching, not a validated enum — an
imperfect brand cluster degrades match quality, it does not produce a false "not in catalog"
rejection the way a bad category merge would, so it does not need category's full-review
gate to stay safe.

**Alternatives considered**: Full manual canonicalization like category (review every raw
string) — rejected, wrong effort/value tradeoff at this cardinality. No fuzzy clustering at
all, exact-normalized only (the original decision) — superseded by explicit instruction;
would leave easily-recoverable spelling variants unmerged for no real safety benefit given
brand's non-enum status. Fuzzy-matching across scripts (Arabic ↔ Latin brand spellings of the
same real brand) — out of scope here; that is a transliteration-matching problem, not an
edit-distance one, and remains the Sprint 5 Arabic research spike already in plan.md.

## 4. Uncategorized products (19.1%, 4,955 products with zero category links)

**Decision**: Keep them in the searchable corpus, reachable by name/brand/price search and
SKU, but excluded from any category-filtered query (since they have no category to match
against). Not excluded from the corpus entirely.

**Rationale**: FR-011 requires the system to return only corpus products and never invent
results — it says nothing about narrowing the corpus itself. Excluding ~5,000 real products
outright would silently shrink the corpus both systems are evaluated against, which cuts
against Principle III (baseline-relative evaluation on the same corpus) more than it helps;
letting a category-filtered query simply not match them (correctly, since they have no
category) is the behavior FR-012 already requires for genuine zero/partial matches.

**Alternatives considered**: Excluding uncategorized products from the corpus — rejected,
shrinks the corpus asymmetrically from what the raw catalog actually contains. Auto-assigning
a synthetic category — rejected outright, this is exactly the kind of fabrication FR-011/012
prohibit.

## 5. Category canonicalization algorithm (concrete steps, Sprint 0)

Produces a reviewable `category_canonicalization_review.csv` before anything is written to
Postgres — no step below writes to the database; a separate apply step consumes the
human-reviewed CSV.

1. **Normalize** `name_en` per category record: NFKC, strip, collapse whitespace, lowercase
   (keep `&` as a meaningful token, e.g. "Meat & Poultry" ≠ "Meat").
2. **Junk exclusion** (deterministic keyword rule, not fuzzy): `^test\d*$` on the normalized
   name → `is_junk = TRUE`, excluded from the canonical enum entirely, no merge target. This
   rule alone must isolate exactly the 5 known junk records (`Test`, `Test1`, `test2`,
   `test`, `TEST`).
3. **Exact-duplicate auto-merge**: group remaining records by normalized name; any group of
   size >1 auto-merges (no human gate) — this rule alone must produce "Meat" ×5, "Grocery"
   ×3, and the other 16 known exact-duplicate groups. Canonical representative = group member
   with the most linked products (tie-break: lowest id).
4. **Fuzzy near-duplicate detection** (`rapidfuzz`, human-gated, never auto-merged): for the
   remaining singletons, compute pairwise `token_sort_ratio` (full pair matrix, trivial at
   this size — no blocking needed). **Empirically corrected during Sprint 0 execution**:
   `max(token_sort_ratio, WRatio)` was tried first and rejected — `WRatio`'s partial-ratio
   component scores unrelated categories that merely share one common word (e.g. "Beauty &
   Personal Care" / "Pet Care", "Dog Food" / "Sea Food Deals") as high as 85+, flooding the
   review output with false positives; `token_sort_ratio` alone at an **85 cutoff** (raised
   from an initial 80, same reason) produces a small, mostly-correct candidate set — every
   candidate is still routed to human review regardless, so the threshold is set to favor
   recall (catching true near-duplicates) over precision, since a false positive only costs
   a reviewer one extra glance while a missed true duplicate silently ships as incomplete
   category coverage. Groups
   form via **complete-linkage** clustering (a pair of clusters may only merge if *every*
   cross-pair between them clears the cutoff) — not single-linkage/union-find, which was
   also tried first and rejected: it let one weak pairwise match chain unrelated categories
   together transitively (a first implementation attempt produced one 152-category group
   spanning "Milk" through "Electronics" through "Cleaning Supplies" via a chain of
   individually-plausible-looking but ultimately unrelated links).
   **Correction**: `parent_category_id` was assumed to be a usable grouping signal, but is
   `NULL` for all 272 rows in the actual dump (verified) — the algorithm must detect this at
   runtime and proceed with "no parent signal available," not silently assume one exists.
   Every fuzzy group is written to the CSV for review, never auto-merged — e.g. "Meats" ~
   "Meat" is very likely the same real category, but "Canned Meat" / "Frozen Meat" are
   plausibly legitimate, narrower sub-categories rather than typos, and only a human can tell
   the two apart.
5. **Review CSV columns**: `raw_category_id`, `raw_name_en`/`ar`, `linked_product_count`,
   `normalized_name_en`, `method` (`exact_auto_merge` \| `fuzzy_candidate` \|
   `singleton_unique` \| `junk_excluded`), `group_id`, `proposed_canonical_slug`/`display_en`,
   `confidence`, `needs_review` (TRUE for every `fuzzy_candidate` *and* every
   `junk_excluded` row, so the junk rule itself gets a human sanity-check too), `reviewer_decision`
   (blank, for the user to fill in), `notes`.
6. **Apply**: a separate script reads the reviewed CSV and writes `canonical_category` rows
   only for approved groups, then sets each `category.canonical_category_id`/`is_junk`.

## 6. Brand canonicalization algorithm (concrete steps, Sprint 0)

Mirrors the category process structurally (generate reviewable CSV → separate apply step),
with the differentiated review policy from §3.

1. **Extract** `product_brand_id` value per product per language row from
   `catalog_productattributes` JSON; missing = null/false/empty/whitespace-only.
2. **Script-classify** each distinct raw string (Arabic-block characters present → `arabic`,
   else → `latin`) — the primary reason for this split is correctness (an Arabic string and
   a Latin string can never legitimately fuzzy-match), not performance; a full
   ~1,700×1,700 `rapidfuzz.process.cdist` is well under a second regardless.
3. **Normalize** per script (same rules as §2's tokenizer); taa marbuta (`ة`/`ه`) is
   deliberately left un-normalized, same open call as §2.
4. **Exact-normalized auto-merge** within each script bucket (cheap, ~zero risk).
5. **Fuzzy cluster** remaining distinct strings within each script bucket only:
   `rapidfuzz.fuzz.token_sort_ratio`, cutoff 90, **complete-linkage** clustering (reusing
   `category_canonicalization.complete_linkage_cluster`, not union-find — same
   weak-middle-link risk as §5, avoided the same way). Canonical representative = highest
   linked-product-count raw string in the cluster. Empirically: 0 exact-normalized
   duplicates existed in the real data (no case/whitespace-only variants), and every
   observed fuzzy cluster scored 90.0–94.7 — none cleared the 97 auto-accept bar, so in
   practice every candidate landed in the reviewed band this run; the differentiated
   auto-accept tier still exists for future data with higher-confidence duplicates.
6. **Differentiated review gate** (see §3's rationale): auto-accept clusters ≥97 similarity;
   flag only the 90–96.9 band for human review — not every row, unlike category.
7. **Review CSV columns**: `raw_brand_value`, `script`, `product_count`, `normalized_value`,
   `method`, `cluster_id`, `proposed_canonical_slug`/`display`, `cluster_min_confidence`,
   `needs_review`, `reviewer_decision`, `notes`.
8. **Apply**: separate script reads the (partially) reviewed CSV, writes
   `canonical_brand`/`brand_alias`, back-fills `product.brand_normalized`.

**Bug found and fixed during Sprint 0 execution**: the apply step's internal `slug` key
(a DB primary key only, never shown to users) was generated by stripping all non-ASCII
characters from the brand text. Since Arabic brand strings contain no ASCII characters at
all, every one of them slugified to the same empty-string fallback, and the apply script's
`ON CONFLICT (slug)` upsert silently merged all ~670 distinct Arabic brands into a single
`canonical_brand` row on first run (canonical brand count came out as 984 instead of the
expected ~1,659). Fixed by falling back to a short stable hash of the raw text when the
ASCII slug is empty, instead of a shared placeholder string, and re-run. Verified post-fix:
1,656 canonical brands total, 674 of them distinct among Arabic-script aliases (was 1,
pre-fix) — this is exactly the kind of silent-merge failure FR-011/FR-019's "don't
silently lose/merge real catalog entities" spirit exists to catch, so it's recorded here
rather than quietly patched over.

**Second fix, later in Sprint 0 — this is the CURRENT behavior, the hash fallback above is
not**: the hash fallback, while collision-safe, was itself a real readability problem —
`canonical_brand.slug` values like `brand_ef2ef07c4e` for a real, recognizable brand, with
no connection to the actual brand name. `brand_normalization.slugify()` now falls back to
the normalized Arabic text itself (readable, and still distinct per brand) whenever the
ASCII slug is empty; a hash is used only as the very last resort, for a value that's neither
ASCII-sluggable nor recognized as Arabic script at all. Separately,
`brand_normalization_apply.py` also merges an English and an Arabic canonical entry into ONE
`canonical_brand` row whenever their raw values co-occur on the same real product (e.g.
"Juhayna" + "جهينه"), preferring the Latin-script slug as the surviving identity — found via
a real bug: `product.brand_normalized` was always back-filled from a product's English raw
value when both existed, so a distinct Arabic-only canonical entry for the exact same real
brand was invisibly orphaned (0 real products ever carried its slug), even after the slug
itself became readable. The 1,656/674 counts above are from the superseded hash-fallback
run, not today's table — the live `canonical_brand` row count as of this writing is 972 (the
cross-script merge above is the main reason it's lower than the hash-era 1,656: many
EN/AR pairs that used to be two separate rows are now correctly one).

## 8. Keyword-search baseline entry point (FR-014, T048 — pulled forward into Sprint 1)

**Decision**: `src/search_engine/keyword_baseline.py` does naive literal/regex parsing of a
plain typed string into a `FilterSet`, then calls the same `SearchAdapter.search()` every
other system uses. Price: English-only regex phrases (`under`/`below`/`less than`/`over`/
`above`/`more than`/`between X and Y`/`X-Y`) — deliberately NOT extended to Arabic price
phrases ("تحت ٣٠ جنيه"), since parsing a preposition's meaning is query *understanding*, and
a traditional keyword box wouldn't have it in either language; this keeps the baseline
comparably naive across languages rather than accidentally-smarter in English. Category/brand:
literal phrase matching (word-boundary regex) against `canonical_category`/`brand_alias`
names in both English and Arabic — matching a literal known name is still "keyword-style,"
not language understanding, so both languages are supported for that part.

**Two real bugs found and fixed while building this**, both via live testing, not static
review: (1) category matching originally unioned a category's English and Arabic name tokens
into one required set, so a query needed *both* languages' words simultaneously to match —
no plain English or plain Arabic query could ever match at all. (2) a matched category/brand
phrase was left inside the leftover free text passed to Stage 2, making it an *additionally*
required BM25 text-match term on top of the structured filter — "meat under 100" returned
zero results, because no meat-category product's title happens to literally contain the word
"meat." Both are covered by regression tests (`tests/integration/test_keyword_baseline.py`)
so they can't silently regress.

**Alternatives considered**: Building this later, as scheduled (Sprint 6, T048 under the
evaluation phase) — rejected once a live status check showed Sprint 1 had no way to search
with a plain string at all, only a pre-built `FilterSet`, which doesn't actually satisfy
FR-014 on its own. Reusing an NLU/LLM step for the baseline's own parsing — rejected, that
would defeat the entire point of having a baseline to compare the conversational system
against.

## 9. FastAPI HTTP layer (Sprint 1, pulled forward)

**Decision**: `src/api/routes.py` exposes `GET /search/keyword` (query params `q`, `limit`,
`offset`) and `GET /health`, backed by Pydantic request/response models in
`src/api/schemas.py` — the third of the three Pydantic usage sites named in plan.md (the
Understanding LLM's Action schema and the SearchState session model are Sprint 2+). Verified
both via FastAPI's `TestClient` (in-process) and as an actually-running `uvicorn` process hit
with real `curl` requests over the network — the in-process check alone wouldn't rule out a
real deployment/networking problem.

**Rationale**: The user explicitly asked for a real endpoint rather than a throwaway CLI,
since FastAPI is needed for Sprint 2 regardless (the conversational `POST /session/{id}/message`
endpoint, tasks.md T030) — building the keyword-search route now establishes the app/routing
pattern Sprint 2 extends, rather than building it twice.

## 11. Adversarial verification pass (post-Sprint-1, before Sprint 2)

A systematic pass found and fixed one more real bug, and named (without fixing, as
non-blocking) two further rough edges:

- **Fixed**: `src/api/schemas.py` defined `KeywordSearchQuery` (length/range-constrained
  Pydantic model for `q`/`limit`/`offset`) but `routes.py` never actually used it — the
  route took a bare `q: str` with no length limit and clamped `limit`/`offset` manually in
  Python instead of validating them. An empty or 5,000-character query was silently
  accepted rather than rejected. Fixed via FastAPI's `Query(..., min_length=1,
  max_length=500)` etc., directly in the route signature; the unused model was removed
  rather than left as misleading dead code. Covered by
  `tests/integration/test_api_boundaries.py`.
- **Fixed (follow-up)**: `price_min > price_max` on direct structured `FilterSet`
  construction now raises `InvalidFilterError` immediately (`FilterSet.__post_init__`),
  surfaced as HTTP 422 via a FastAPI exception handler — same pattern as the other boundary
  validations, not an auto-normalized silent empty result. Deliberately scoped to direct
  construction only: the keyword baseline's "between X and Y" text-parsing path still
  auto-normalizes an inverted phrase *before* constructing a `FilterSet`, so a naturally
  ambiguous typed phrase and a genuinely malformed structured parameter are treated
  differently, on purpose.
- **Fixed (follow-up), and a real number correction**: `"Please select a brand."` (a
  literal unfilled dropdown default from the source data) was canonicalizing as if it were
  a real brand. A deliberate, broad search (EN+AR placeholder keywords, punctuation-only
  values, short values like "LG"/"Fa"/"V8" — confirmed those ARE real brands, left alone)
  found exactly one genuine junk value. Excluded via a denylist rule mirroring category's
  junk step (§5) — `brand_normalization.py` now marks it `junk_excluded` before clustering,
  and the apply script resets `product.brand_normalized` to `NULL` before re-backfilling
  (fixing a latent staleness bug: without the reset, a value excluded in one run would keep
  whatever a *previous* run had written). **Impact was initially misreported as "15
  products"** — that count came from an earlier ad hoc query scoped to one category+price
  slice, not the true total, and was repeated without re-deriving it. The actual figure,
  verified directly against the full table: **7,505 products — roughly 30% of all
  brand-bearing products in the catalog** — carried this placeholder. Total products with a
  real `brand_normalized` value dropped from 24,820 to 17,315, exactly accounting for the
  difference (24,820 − 7,505 = 17,315). This is a substantially bigger catalog data-quality
  finding than first reported, not a minor cleanup.

Verified via a full teardown: `docker compose down -v` (containers + volumes removed),
rebuilt from scratch, schema reapplied, real data reloaded, the two already-reviewed
canonicalization CSVs re-applied (not regenerated — they're versioned review artifacts, not
derived state) — identical counts every time (25,881 products, 272→244 categories, 1692→1656
brands). Full suite (31 tests) run 3× against this fresh state: 5.48–5.86s, no recurrence of
the earlier 17.5s outlier.

## 12. SearchAdapter scope audit (2026-09-09) — speculative code found and removed

Explicit check: does `src/search_adapter/adapter.py` do anything beyond what
`keyword_baseline.py` needs today, built ahead of Sprint 2/3's actual requirements?

**Found**: `validate_filter_value()` + `ValidationOutcome`, plus the two query-layer
functions only it used (`resolve_category_slug`, `resolve_brand` in
`src/search_engine/query.py`). Confirmed via grep across `src/` and `tests/` that neither
`keyword_baseline.py` nor `src/api/routes.py` ever called it — its only caller was a test
written specifically to exercise it. This existed because the *original* contract draft
(written before any Sprint 1 code) designed it for Sprint 3's Validation step ahead of that
step having any real requirements to design against.

**Removed**: the method, the dataclass, and both now-orphaned query functions. FR-020
compliance (never hard-reject, never fabricate on a missing brand) is fully proven by
`search()` alone — confirmed by rerunning the full suite (32/32 still passing) after
removal, with the two tests that had used `validate_filter_value` rewritten to rely only on
`search()`'s actual behavior.

**Kept, after consideration**: `FilterSet.__post_init__`'s `price_min > price_max` rejection
(§11). Deliberately NOT treated as the same kind of speculative overreach — it was added in
direct response to an explicit request in this session for `FilterSet`'s own construction-
time behavior today, not built ahead of a future caller that doesn't exist yet.

**LLM check, specifically on the removed code**: grepped the speculative
`validate_filter_value`/`resolve_category_slug`/`resolve_brand` chain for
`openai|anthropic|llm|gpt|completion` before removing it — zero hits. Combined with the
existing AST-level import check on `src/api/routes.py`, there was and is no LLM involvement
anywhere in this path.

`contracts/search-adapter.md` and `tasks.md` (T021, T026) updated to record this as a
correction, not silently dropped — including a "Deferred" section so the original design
intent for Sprint 3 isn't lost, just not built prematurely.

## 10. Non-descriptive `url_key` products (originally flagged as an open item)

**Decision**: Resolved by verified data, not a decision — no action needed. `catalog_productname`
provides a full, bilingual, structured name for 100% of products (25,881 English + 25,881
Arabic rows), independent of `url_key` quality. `url_key` (74.5% descriptive) is only a
secondary/fallback signal, not the primary name source an earlier draft assumed. Every
product is name-searchable in both languages regardless of its `url_key`.
