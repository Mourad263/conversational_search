# Tasks: Conversational Search Baseline

**Input**: Design documents from `/specs/001-conversational-search-baseline/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/search-adapter.md, quickstart.md

**Tests**: Not mandated by spec.md beyond the Sprint 6 evaluation harness itself and the
Sprint 2 isolated EN/AR utterance test already named in plan.md. A small number of
`pytest` unit-test tasks are included as optional/lower-priority (marked accordingly), not a
blocking TDD gate.

**Organization**: Sprint 0 (Postgres schema, dump extraction, category/brand
canonicalization) and Sprint 1 (the hybrid search engine) are the Foundational phase — the
instructor's explicit near-term priority, and a hard dependency of every user story below,
since none of US1–US5 can produce a real search result without them. User stories US1–US5
map directly to spec.md's five prioritized stories.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: Maps to spec.md's US1–US5; Setup/Foundational/Polish tasks carry no story label

---

## Phase 1: Setup

- [x] T001 Create the source tree per plan.md's Project Structure (`src/ingestion/`,
  `src/search_engine/`, `src/search_adapter/`, `src/understanding/`, `src/validation/`,
  `src/state_manager/`, `src/scenario/`, `src/response/`, `src/api/`, `src/models/`,
  `evaluation/`, `tests/unit/`, `tests/integration/`, `tests/understanding/`)
- [x] T002 [P] Add `requirements.txt` (or `pyproject.toml`) pinning: fastapi, sqlalchemy,
  `psycopg[binary]`, pydantic, pydantic-settings, pandas, rapidfuzz, uvicorn,
  python-dotenv, openai
- [x] T003 [P] Install the packages not already present in this dev environment
  (`psycopg`, `rapidfuzz`, `openai` — fastapi/pandas/pydantic/SQLAlchemy are already
  installed)
- [x] T004 [P] Create `docker-compose.yml` provisioning `postgres:16`, with `pg_trgm` and
  `pgcrypto` extensions enabled via an init script, and a named volume for persistence
- [ ] T005 [P] Configure linting/formatting (ruff + black or equivalent) -- **Corrected
  2026-09**: previously checked off without ever actually happening; no ruff/black/flake8
  config file or dependency exists anywhere in the repo (confirmed by direct inspection).
  Not required by spec.md (no functional requirement mentions linting) -- left unchecked
  rather than configuring a tool nobody has asked for, per the standing instruction not to
  introduce tooling merely to make a checkbox true.
- [x] T006 Create `.env.example` and a `pydantic-settings`-based config module in
  `src/models/config.py` for the DB connection string and `OPENAI_API_KEY` (no real key
  committed)

---

## Phase 2: Foundational — Sprint 0 (Postgres schema + real-data load + canonicalization)

**⚠️ CRITICAL**: No user story work can begin until this phase is complete — every story
depends on a real, queryable corpus.

- [x] T007 Write the DDL (or SQLAlchemy declarative models producing equivalent DDL) for
  `category`, `canonical_category`, `product`, `canonical_brand`, `brand_alias`,
  `product_category`, `search_session` in `src/models/schema.sql` (or `src/models/db.py`),
  exactly per data-model.md — source IDs preserved (not resequenced), `NUMERIC(12,2)` for
  price fields, `gin_trgm_ops` indexes on `product.name_en`/`name_ar`/`brand_normalized`
- [x] T008 Start Postgres (`docker compose up -d`) and apply the T007 schema, confirming
  `pg_trgm`/`pgcrypto` extensions are active
- [x] T009 [P] Implement a streaming, quote/escape-aware MySQL-dump table extractor in
  `src/ingestion/dump_reader.py` — isolates just the 6 target tables'
  `INSERT INTO ... VALUES (...),(...);` data sections from `data/spinneys_database.sql`
  (828MB, no MySQL server available) and splits each into top-level tuples/fields without
  naive comma-splitting, per research.md's "Extraction from the MySQL Dump" section
- [x] T010 [P] Implement `src/ingestion/load_dump.py`: extract `catalog_product`,
  `catalog_productname`, `catalog_category`, `catalog_categoryname`,
  `catalog_product_categories`, `catalog_productattributes`; flatten EN/AR name pairs onto
  `product.name_en/ar` and `category.name_en/ar`; parse the `attributes` JSON for the
  `product_brand_id` code into `product.brand_raw_en`/`brand_raw_ar`; bulk-load via
  `COPY` for the large tables and batched `INSERT` for the small ones; assert post-load row
  counts (25,881 products, 272 categories, 544 categorynames, 51,762 productattributes
  rows) and fail loudly on mismatch
- [x] T011 Implement `src/ingestion/category_canonicalization.py` (generate step, no DB
  writes): normalize → junk-exclude (`^test\d*$`) → exact-duplicate auto-merge → rapidfuzz
  fuzzy-candidate detection (`token_sort_ratio`/`WRatio`, cutoff 80, union-find), per
  research.md §5; output `category_canonicalization_review.csv`
- [x] T012 Manually review `category_canonicalization_review.csv` (fill in
  `reviewer_decision` for every `fuzzy_candidate` and `junk_excluded` row) — human task
- [x] T013 [depends on T012] Implement `src/ingestion/category_canonicalization_apply.py`:
  read the reviewed CSV, write `canonical_category` rows for approved groups, set
  `category.canonical_category_id`/`is_junk`
- [x] T014 [P] Implement `src/ingestion/brand_normalization.py` (generate step): extract
  distinct raw brand strings, script-classify (Arabic vs. Latin), normalize per script,
  exact-merge, then rapidfuzz fuzzy-cluster within each script bucket only
  (`token_sort_ratio`, cutoff 90); auto-accept clusters ≥97, flag the 90–96.9 band for
  review, per research.md §6; output `brand_canonicalization_review.csv`
- [x] T015 Manually review the 90–96.9-confidence band of
  `brand_canonicalization_review.csv` — human task (smaller than T012's scope, per the
  differentiated review policy)
- [x] T016 [depends on T015] Implement `src/ingestion/brand_normalization_apply.py`: read
  the (partially) reviewed CSV, write `canonical_brand`/`brand_alias` rows, back-fill
  `product.brand_normalized`

## Phase 2 (cont'd): Foundational — Sprint 1 (hybrid search engine, System A)

- [x] T017 [depends on T013] Implement `src/search_engine/query.py` — Stage 1 Postgres hard
  filters: category (expanded through `canonical_category_id` to every equivalent raw
  record, FR-019), price range, brand `ILIKE` over `brand_normalized` (`pg_trgm`-indexed);
  no `LIMIT`/`OFFSET` at this stage, per research.md §2
- [x] T018 Implement `src/search_engine/tokenizer.py` — per-token Unicode-block
  classification (Arabic-range → Arabic path, else Latin), Latin normalization
  (NFKC/lowercase/punctuation-strip/plural-suffix trim), Arabic normalization
  (NFKC/diacritics+tatweel strip/alef-variant fold), per research.md §2
- [x] T019 [P] [depends on T016, T018] Implement `src/search_engine/index.py` — build the
  in-memory `token -> postings` index plus corpus-wide IDF/average-doc-length over the
  *full* `catalog_productname` (EN+AR) corpus at startup, not per-query
- [x] T020 [depends on T018, T019] Implement `src/search_engine/ranking.py` — hand-rolled
  BM25 scorer (`k1≈1.2–1.5`, `b≈0.75`) over the Stage-1 candidate set, exact-SKU/`url_key`
  boosting, final sort, then `[offset:limit]` slice
- [x] T021 [depends on T017, T020] Implement `src/search_adapter/adapter.py` per
  contracts/search-adapter.md: `search(filters, limit, offset) -> SearchResult` composing
  Stage 1 + Stage 2. **Corrected 2026-09-09**: this originally also included
  `validate_filter_value(attribute, value) -> ValidationOutcome`, but an explicit audit
  found it had zero real callers (not `keyword_baseline.py`, not the API route — only a
  test built to exercise it) and was speculative work for Sprint 3's not-yet-built
  Validation step. Removed from `adapter.py` and `query.py`
  (`resolve_category_slug`/`resolve_brand`); FR-020 is fully proven by `search()` alone.
  See contracts/search-adapter.md's "Deferred" section.
- [x] T022 [P] [OPTIONAL] `pytest` tests against the real running system (Postgres +
  loaded corpus, not mocked) in `tests/integration/test_search_engine.py` — covers a
  normal keyword match, an Arabic query, a category+price combo, and two zero-result
  cases (implausible price ceiling; nonsense brand). All 6 pass.
- [x] T023 [depends on T021] Run quickstart.md's 5 validation scenarios against the live
  system; confirm every expected outcome

- [x] T017b Implement `src/search_engine/keyword_baseline.py` (FR-014 / T048, pulled forward
  from Phase 7 — a live status check found System A had no standalone entry point: naive
  English-only price-phrase regex extraction (`under`/`between`/range), literal EN+AR
  category/brand phrase matching via word-boundary regex against `canonical_category`/
  `brand_alias`, remaining text passed through as `query_text`. Two real bugs found and
  fixed during this work: (1) category EN/AR names were unioned into one required token
  set instead of checked as alternatives, so no plain-language query could ever match; (2)
  a matched category/brand phrase stayed in the leftover free text and became an
  additionally-required BM25 text term, causing false zero-results (e.g. "meat under 100"
  found nothing because no meat product's title contains the literal word "meat"). Both
  covered by regression tests in `tests/integration/test_keyword_baseline.py`.
- [x] T017c Expose T017b over a real FastAPI endpoint: `src/api/schemas.py` (Pydantic
  request/response models — the third Pydantic usage site named in plan.md) and
  `src/api/routes.py` (`GET /search/keyword`, `GET /health`). Verified both via
  `TestClient` and as an actually-running `uvicorn` process hit with real `curl` requests
  over the network, not just in-process.

**Checkpoint**: Foundation ready — System A (the search engine the conversational layer will
later be measured against) is functional, independently queryable both as a Python
`SearchAdapter` and as a live HTTP endpoint taking a plain typed keyword string, with real
canonicalized data behind it.

---

## Phase 3: User Story 1 - Natural-Language Search With Multiple Requirements (P1) 🎯 MVP

**Goal**: A single NL message bundling 2+ requirements returns correct, corpus-only results.

**Independent Test**: Per spec.md US1 — submit one message with 2+ distinct requirements,
verify the returned products satisfy all of them and come from the corpus.

- [ ] T024 [P] [US1] Define the schema-constrained `Action` Pydantic model (intent +
  filters-to-add) in `src/understanding/schema.py` — Pydantic usage site 1 of 3
- [ ] T025 [US1] [depends on T024] Implement the Understanding LLM call in
  `src/understanding/llm.py` — OpenAI API (model choice deferred to this task's own
  evaluation, not hardcoded), prompt + EN/AR few-shot examples, parses output into `Action`
- [ ] T026 [US1] [depends on T021, T025] Implement `src/validation/validate.py` —
  deterministic check of an `Action`'s filters against Postgres. **Note (2026-09-09)**:
  the originally-assumed `SearchAdapter.validate_filter_value` no longer exists (removed
  as speculative/unused — see contracts/search-adapter.md). Design this task's actual
  validation logic from the State Manager's real requirements when this task is picked
  up, not from that removed method's shape.
- [ ] T027 [US1] [depends on T026] Implement the "new search" path in
  `src/state_manager/state_manager.py`: apply a validated Action to a fresh `SearchSession`,
  call `SearchAdapter.search()`
- [ ] T028 [P] [US1] Define the `SearchState` Pydantic session model in
  `src/state_manager/session_model.py` (`active_filters`, `last_result_set`,
  `last_intent`, `languages_used`) — Pydantic usage site 2 of 3
- [ ] T029 [US1] [depends on T027] Implement `src/response/generate.py` — the second LLM
  call, phrasing the user-facing reply strictly grounded in the returned `SearchResult`
  (FR-011: never fabricate a product/attribute)
- [ ] T030 [US1] [depends on T027, T029] Implement `POST /session/{id}/message` in
  `src/api/routes.py`, wiring Understanding → Validation → State Manager → SearchAdapter →
  Response, with Pydantic request/response models — Pydantic usage site 3 of 3
- [ ] T031 [US1] [depends on T030] Confirm zero-result handling: `SearchResult.zero_result`
  surfaces as an explicit "no results" reply, never a silently loosened/substituted one
  (FR-012)

**Checkpoint**: US1 fully functional and independently testable.

---

## Phase 4: User Story 2 - Multi-Turn Filter Refinement (P1)

**Goal**: Add/modify/remove/reset filters across turns without restating prior requirements.

**Independent Test**: Per spec.md US2 — run a fixed follow-up sequence, verify the resulting
filter set and results after each turn.

- [ ] T032 [US2] Write the state-transition truth table by hand (current state × new
  `Action` → resulting state), covering add/modify/remove/reset/conflicting-filter/
  topic-switch cases, as `specs/001-conversational-search-baseline/state-transitions.md` —
  design artifact, per plan.md's Sprint 3 note that this is a research task, not a coding
  one, and skipping it is where bugs hide
- [ ] T033 [US2] [depends on T032] Implement add/modify/remove logic in
  `src/state_manager/state_manager.py` per the truth table (FR-002/FR-003/FR-004)
- [ ] T034 [US2] [depends on T033] Implement explicit reset (FR-005), clearing
  `SearchSession.active_filters`/context
- [ ] T035 [US2] [depends on T033] Implement topic-switch-as-implicit-reset (plan.md §4)
- [ ] T036 [US2] [depends on T033] Implement the "remove a filter that isn't active" edge
  case: a stated no-op response, not a fabricated removal or silent error (spec.md Edge
  Cases)
- [ ] T037 [US2] [depends on T027] Implement implicit-reference resolution ("cheaper ones",
  "a different brand") against `SearchSession.last_result_set`/`active_filters`
- [ ] T038 [US2] [depends on T033] Persist `SearchSession` to the `search_session` table so
  state survives across API calls within a session

**Checkpoint**: US2 fully functional — the fixed follow-up sequence produces the correct
accumulated filter set at every step.

---

## Phase 5: User Story 3 - Bilingual Search With Canonical Equivalence (P1)

**Goal**: EN/AR requests expressing the same requirements resolve to the same canonical
intent; language can switch mid-session.

**Independent Test**: Per spec.md US3 — matched EN/AR message pairs produce the same
resolved filters and result set.

- [ ] T039 [P] [US3] Expand the Understanding prompt's few-shot set with matched EN/AR
  request pairs covering spec.md US3's acceptance scenarios
- [ ] T040 [US3] [depends on T039] Run matched EN/AR query pairs through Understanding +
  Validation and assert identical resolved `FilterSet` (an informal check here; the formal
  SC-004 harness is US5's job)
- [ ] T041 [US3] [depends on T018] Confirm the tokenizer's mixed-script handling (spec.md
  edge case: an Arabic sentence with an English brand name) extracts filters correctly
  rather than failing outright
- [ ] T042 [US3] [depends on T033] Confirm a language switch mid-session (EN session, AR
  follow-up) correctly applies to the existing `SearchSession`, not treated as a fresh one

**Checkpoint**: US3 fully functional.

---

## Phase 6: User Story 4 - Clarification of Ambiguous Requests (P2)

**Goal**: Genuinely ambiguous input gets a targeted clarifying question, not a guess.

**Independent Test**: Per spec.md US4 — intentionally ambiguous EN/AR messages get a
clarifying question, not a guessed result set.

- [ ] T043 [P] [US4] Extend the `Action` schema (`src/understanding/schema.py`) with
  `is_ambiguous` and `clarifying_question` fields
- [ ] T044 [US4] [depends on T043] Implement ambiguity handling in
  `src/state_manager/state_manager.py`: when `is_ambiguous`, return the clarifying question
  instead of calling `SearchAdapter` (FR-007); track "awaiting clarification" in
  `SearchSession` so the same question isn't repeated once answered (FR-007 Acceptance
  Scenario 2)
- [ ] T045 [P] [US4] Wire the seven internal scenario labels (plan.md §4: `off_topic`,
  `recommendation_request`, `out_of_catalog`, `customer_service`, `prompt_injection`,
  `token_abuse`, `topic_switch`) into `src/scenario/classify.py`, all mapping to the single
  `unsupported_request` user-facing family (FR-018)
- [ ] T046 [US4] Implement the constitution-level abuse guards (message length cap,
  per-session turn cap before suggesting reset, repeat-query rate limit) in
  `src/scenario/` or FastAPI middleware
- [ ] T047 [US4] [depends on T026] Confirm `out_of_catalog` detection is driven by category
  validation against the canonical enum, not by intent classification (plan.md §4)

**Checkpoint**: US4 fully functional.

---

## Phase 7: User Story 5 - Baseline Comparison Evaluation (P2)

**Goal**: A side-by-side report of Search Success Rate, Zero-Result Rate, Follow-Up Success
Rate (and Conversion where measurable) for both systems on the same query set/corpus.

**Independent Test**: Per spec.md US5 — run the shared evaluation set against both systems,
confirm a report with all four metrics is produced.

- [x] T048 [P] [US5] [depends on T021] Implement the keyword-search baseline (System A) —
  **done as T017b** (`src/search_engine/keyword_baseline.py`), pulled forward into Sprint 1
  rather than deferred to Sprint 6, since a live status check showed Sprint 1 had no
  standalone entry point without it. `evaluation/baseline.py` (T051) will import this
  directly rather than reimplementing it.
- [ ] T049 [P] [US5] Build the versioned EN/AR evaluation query set (single-turn +
  multi-turn, including deliberately ambiguous and out-of-catalog cases) in
  `evaluation/query_set/` (FR-015)
- [ ] T050 [US5] Decide and document the Search-Success-Rate rubric (LLM-as-judge,
  offline/batch, separate from the real-time Understanding/Response calls) — plan.md's
  Sprint 6 open item; blocks T051 from producing meaningful numbers
- [ ] T051 [US5] [depends on T048, T049, T050] Implement `evaluation/run_baseline.py` and
  `evaluation/run_conversational.py`, executing the shared query set against both systems
  and recording `EvaluationResult` rows per data-model.md
- [ ] T052 [US5] [depends on T051] Implement `evaluation/report.py` computing Search
  Success Rate, Zero-Result Rate, Follow-Up Success Rate for both systems, and Search
  Conversion Rate only where real transaction data exists — otherwise explicitly labeled an
  unmeasured hypothesis (FR-016/FR-017)
- [ ] T053 [US5] [depends on T051] Confirm the keyword baseline's inability to carry
  multi-turn context is recorded as a measured `follow_up_success = false` outcome, not
  silently skipped (spec.md US5 Acceptance Scenario 2)

**Checkpoint**: US5 fully functional — all prior user stories are now measured against the
baseline, producing the evidence the project's central hypothesis depends on.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [ ] T054 [P] Add structured logging across Understanding/Validation/State
  Manager/SearchAdapter calls (Principle IV traceability, FR-013)
- [ ] T055 [P] Add retries/fallback handling for the OpenAI and Postgres calls (plan.md §6)
- [ ] T056 [P] Harden FastAPI-boundary input validation (cross-references T030's Pydantic
  request models)
- [ ] T057 Document the in-memory/single-instance session-state limitation and the sticky-
  sessions-then-Redis remediation path (plan.md §6)
- [ ] T058 [P] Dockerize the service (Dockerfile + a service entry alongside Postgres in
  `docker-compose.yml`)
- [ ] T059 Define and document the logging retention/access policy for session transcripts
  — closes plan.md's flagged Constitution Principle VI "NEEDS ATTENTION" item
- [ ] T060 Final read-through of spec.md/plan.md/research.md/data-model.md against the
  as-built system, per the constitution's Governance clause (checked against Principles
  II/III/IV before being marked complete)

---

## Dependencies & Execution Order

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2, Sprint 0 + Sprint 1)**: Depends on Setup. **Blocks every user
  story** — this is the instructor's stated near-term priority and the literal prerequisite
  for any search result to exist. Within Phase 2: T007→T008→T010 (schema before load);
  T009 before T010 (extractor before its caller); T011→T012→T013 and T014→T015→T016 are two
  independent canonicalization tracks, each generate→review→apply, and can run in parallel
  with each other; Sprint 1 (T017–T023) depends on T013 and T016 (needs canonicalized
  category/brand data to filter/match against).
- **User Stories (Phase 3–7)**: All depend on Phase 2 completion. US1 has no dependency on
  other stories. US2–US5 each build on US1's Understanding/Validation/State-Manager
  scaffolding (T025–T027) but are independently testable per their own Independent Test
  criteria once that scaffolding exists.
- **Polish (Phase 8)**: Depends on whichever user stories are in scope for the current
  milestone being complete.

### Parallel Opportunities

- All `[P]` tasks within Phase 1 and within Phase 2's two canonicalization tracks
  (T011–T013 vs. T014–T016) can run in parallel.
- T019 (index build) and other `[P]` Sprint 1 tasks can proceed in parallel once their
  stated dependencies clear.
- US3's tasks (Phase 5) can largely proceed in parallel with US2 (Phase 4) once US1's
  scaffolding exists, since bilingual handling and multi-turn state are largely orthogonal
  concerns.

---

## Implementation Strategy

### MVP First

1. Phase 1 (Setup) → Phase 2 (Foundational: Sprint 0 + Sprint 1 — **today's target**) →
   Phase 3 (US1).
2. **STOP and VALIDATE**: US1 alone is a demonstrable MVP — a single NL message with
   multiple requirements returns correct, corpus-only results, with the keyword baseline
   (System A) already independently provable via quickstart.md.

### Incremental Delivery

Phase 2 → US1 (MVP) → US2 (refinement) → US3 (bilingual parity) → US4 (clarification) → US5
(the evaluation that actually proves or disproves the project's hypothesis) → Phase 8
(polish/production-hardening).

## Notes

- `[P]` tasks touch different files with no dependency on an incomplete task.
- Every Sprint 0 canonicalization step is generate → **human review** → apply, by design —
  no script writes to Postgres without a human-reviewed CSV in between (category: full
  review of every fuzzy/junk row; brand: a narrower 90–96.9-confidence band only, per
  research.md §6's differentiated policy).
- LLM provider is OpenAI; no task above names a specific model — that choice is made and
  recorded as part of executing T025, not before.
