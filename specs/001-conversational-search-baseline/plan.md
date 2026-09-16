# Implementation Plan: Conversational Search Baseline

**Branch**: `001-conversational-search-baseline` | **Date**: 2026-09-08 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-conversational-search-baseline/spec.md`

## Summary

Build a conversational search prototype over a real 25,881-product bilingual (EN/AR)
Spinneys Egypt supermarket catalog, and prove — via a shared evaluation set run against both
systems — whether it reduces search friction relative to a traditional keyword-search
baseline over the same corpus. Architecture: **conversational search + retrieval, not RAG.**
One LLM call per turn does two narrow jobs (understand the message into schema-constrained
JSON; later phrase a response strictly grounded in returned data). A deterministic,
non-LLM **Validation** step checks the LLM's output against known Postgres values (mainly the
canonicalized category enum). A deterministic, non-LLM **State Manager** applies the
validated action to session filter state. A **Search Adapter** converts current state into a
request against a **Search Engine built from scratch** (the instructor's explicit first ask,
not a wrapped OpenSearch/Elasticsearch instance) over data loaded from the source MySQL dump
into PostgreSQL. The instructor's immediate priority is the search engine itself (Sprint 0 +
1 below), standalone, before any conversational/LLM work.

## Technical Context

**Language/Version**: Python 3.12 (confirmed — matches the 3.12.10 already installed in the
dev environment). The source dump is unambiguously a Django application export
(`django_migrations`, `django_session`, `django_admin_log`, `django_content_type`, and every
`catalog_*`/`recommendations_*` table follows Django's `app_model` naming convention);
Python was inferred from that before confirmation, and the guess held.

**Primary Dependencies**: FastAPI (async HTTP layer — a good fit for LLM-call-in-the-loop
latency), SQLAlchemy 2.x + `psycopg` v3 (the `postgresql+psycopg` dialect — chosen over
`psycopg2-binary`, which is unmaintained for new feature work and has weaker Python 3.12
wheel support), Pydantic — used with the same schema discipline in three distinct places:
the Understanding LLM's Action output, the SearchState session model, and FastAPI
request/response validation — and pandas + `rapidfuzz` (Sprint 0 dump-cleaning and
category/brand canonicalization scripts). LLM provider is **OpenAI** (confirmed; API access
arriving separately) — specific model choice is deferred to Sprint 2's isolated EN/AR test,
per research.md, and is deliberately not locked into tasks.md.

**Storage**: PostgreSQL only (target version 16, the current Docker official image, with the
`pg_trgm` extension enabled for indexed fuzzy/substring matching on name/brand columns). The
source MySQL dump (`data/spinneys_database.sql`) is loaded and transformed into Postgres as
the system's actual store — Postgres is queried directly by the Search Engine and Validation
step; the MySQL dump is not queried live. SQLite is explicitly not used (the corpus and
canonicalization mappings need to support concurrent sessions and the evaluation harness, not
a single-file embedded store).

**Testing**: pytest (unit tests for State Manager transitions, Search Adapter, Search
Engine ranking); a hand-written EN/AR utterance set for the Understanding LLM call (Sprint 2,
tested in isolation before wiring); the Sprint 6 evaluation harness itself doubles as an
integration/acceptance test suite run against both systems.

**Target Platform**: Linux server (containerized — Docker, per the production-readiness
notes in §6), accessed via HTTP API; no native client.

**Project Type**: Web service (single backend; no separate frontend is in scope for this
feature — a thin evaluation/demo client is sufficient, not a production storefront UI, per
FR-018 and the constitution's Scope Boundaries).

**Performance Goals**: Not numerically specified by the user for this prototype; keeping
per-turn token cost roughly flat regardless of session length (bounded state, §Session State
below) is the one performance-shaped constraint that *is* specified. No req/s or latency SLO
is defined — treat as a prototype-stage gap, not a silently invented number.

**Constraints**: Message length cap, per-session turn cap before suggesting reset, and a
repeat-query rate limit (Sprint 4, constitution-level abuse guards) — resolved in Sprint 4
(`src/scenario/guard.py`): 500-char message cap, `SESSION_TURN_CAP=40` (non-blocking, appends
a reset suggestion), `REPEAT_THRESHOLD=4`/`REPEAT_WINDOW_SECONDS=30` (the 4th identical
normalized message within 30s is blocked before the LLM is called; deliberately one more than
the recommendation policy's `MAX_RELAXATION_STEPS=3` so three genuine identical exploration
requests are never mistaken for abuse). LLM never sees the full catalog and never authors final
result content (architectural constraint, not a performance one).

**Scale/Scope**: Fixed corpus of 25,881 products / 272 raw category records (canonicalizing
to fewer after Sprint 0 cleanup) / bilingual (EN/AR) throughout. Session-scoped state only —
no cross-session persistence requirement (per spec Assumptions). Correction: `catalog_category`
has a `parent_category_id` column, but it is `NULL` for all 272 rows in the actual dump
(verified directly) — there is no usable category hierarchy signal in this dataset, despite
the column's presence; category canonicalization (research.md §2) is designed around a flat
272-record list, not a hierarchy.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | How this plan satisfies it |
|---|---|---|
| I. Conversation Over Query | **PASS** | State Manager holds accumulated filters + last result set + last intent per session (FR-006), applies add/modify/remove/reset deterministically, and every response is traceable to the resolved filters/intent that produced it (FR-013). |
| II. Bilingual Parity | **PASS, with a documented gap** | Category names are natively bilingual in the source data (`catalog_categoryname`) and product names are natively bilingual for 100% of products (`catalog_productname`) — no translation step needed for either. The documented gap: brand matching is best-effort free text (~1,700 raw spellings mixing EN/AR) rather than a validated enum like category (see Key Entities in spec.md) — this is disclosed, not silently accepted, and is explicitly budgeted as a research spike (Sprint 5). |
| III. Baseline-Relative Evaluation | **PASS** | System A (keyword-search baseline) is a required, standalone deliverable (Sprint 1) built before any conversational-layer work, and Sprint 6 runs the identical EN/AR, single- and multi-turn evaluation set against both systems from the same corpus (FR-014–017). |
| IV. Transparent, Debuggable Behavior | **PASS** | Validation and State Manager are deterministic, non-LLM code; every turn's resolved filters/intent are recorded (FR-013); no result content is LLM-authored (results come only from the Search Adapter/Engine). |
| V. Honest Prototype Scoping | **PASS** | FR-018 plus the Section 4 scenario-redirect table keep off-topic/recommendation/out-of-catalog requests from silently expanding scope; the corpus's real-world messiness (19.1% uncategorized, near-duplicate categories, fragmented brand spellings) is documented rather than hidden. |
| VI. Data & Query Privacy by Default | **NEEDS ATTENTION, tracked not deferred** | No concrete retention/access policy for logged session transcripts exists yet. This is flagged explicitly here (per the constitution's own "must be flagged and resolved before proceeding, not deferred silently" rule) and assigned to Sprint 4 (logging/guard rails) and Sprint 7 (production hardening) rather than left implicit. |

No violations require justification in Complexity Tracking at this stage.

## Project Structure

### Documentation (this feature)

```text
specs/001-conversational-search-baseline/
├── plan.md              # This file
├── research.md           # Phase 0 output
├── data-model.md          # Phase 1 output
├── quickstart.md          # Phase 1 output
├── contracts/             # Phase 1 output
│   └── search-adapter.md
└── tasks.md               # Phase 2 output (/speckit-tasks — not created by this command)
```

### Source Code (repository root)

```text
src/
├── ingestion/            # Sprint 0: MySQL dump -> Postgres load + cleaning
│   ├── load_dump.py
│   ├── category_canonicalization.py   # raw category record -> canonical filter value
│   └── brand_normalization.py         # lowercase/trim/light alias grouping over ~1,700 raw brand strings
├── search_engine/        # Sprint 1: System A, plain keyword/attribute search, no LLM
│   ├── index.py           # in-memory EN/AR token index over catalog_productname, built over the full corpus
│   ├── ranking.py         # hand-rolled BM25 scoring over a Stage-1 candidate set (hybrid design, research.md §2)
│   └── query.py           # Stage 1: Postgres hard filters -- category (canonical enum), price range, brand (exact canonical identity, case-insensitive)
├── search_adapter/       # Sprint 0 interface, Sprint 1 first real implementation
│   └── adapter.py         # session filter state -> Search Engine request (see contracts/search-adapter.md)
├── understanding/        # Sprint 2: the "read message -> structured action" LLM call
│   ├── prompts/
│   └── schema.py           # Pydantic models for the schema-constrained JSON action
├── validation/            # Sprint 3: deterministic check of LLM output against Postgres
│   └── validate.py
├── state_manager/         # Sprint 3: deterministic add/modify/remove/reset + topic-switch-as-reset
│   └── state_manager.py
├── scenario/               # Sprint 4: internal scenario labels (off_topic, out_of_catalog, ...)
│   └── classify.py
├── response/               # Sprint 2's second LLM job: phrase the grounded reply
│   └── generate.py
├── api/                    # FastAPI routes (conversational session endpoint + keyword-baseline endpoint)
│   └── routes.py
└── models/                  # SQLAlchemy models (Product, Category, CategoryAlias, BrandAlias, ...)
    └── db.py

evaluation/                 # Sprint 6
├── query_set/               # versioned EN/AR single- and multi-turn evaluation queries
├── run_baseline.py
├── run_conversational.py
└── report.py                 # Search Success / Zero-Result / Follow-Up / (Conversion if available)

tests/
├── unit/                    # state_manager transitions, search_engine ranking, validation
├── integration/              # full turn: message in -> action -> validated -> state -> results
└── understanding/            # Sprint 2's isolated EN/AR utterance test set
```

**Structure Decision**: Single backend service (FastAPI + PostgreSQL), no separate frontend
project — matches "Web service" Project Type above and the feature's scope (no storefront
UI, per FR-018). The tree mirrors the Sprint 0–7 plan directly (`ingestion/` and
`search_engine/` are the Sprint 0/1 near-term priority; `understanding/` through `scenario/`
land in Sprints 2–4; `evaluation/` is Sprint 6) so each sprint's deliverable has one obvious
home and later sprints don't need to restructure earlier ones.

## Complexity Tracking

*No Constitution Check violations to justify.* The one open item (Principle VI, data
retention/access policy) is a gap to close in a later sprint, not a principle the
architecture violates — no complexity trade-off is being made to work around it.
