# Quickstart: Validating Sprint 0–4

This validates the search engine (Sprint 1), the Understanding/Validation layer (Sprint 2),
the State Manager (Sprint 3), and the conversational orchestration/scenario layer (Sprint 4),
all of which are built. `POST /session/{session_id}/message` (`src/api/routes.py`) is now the
live, public conversational HTTP endpoint — see "Sprint 4: conversational endpoint" below.
`GET /search/keyword` and `GET /health` remain live as System A, the keyword-search baseline,
unchanged. EN/AR canonical-intent equivalence is exercised throughout `tests/understanding/`.

## Prerequisites

- Docker (for PostgreSQL — `pgvector/pgvector:pg16`, per `docker-compose.yml`).
- `data/spinneys_database.sql` present (the real Spinneys Egypt dump).
- Python 3.11+ environment with project dependencies installed (`pip install -r requirements.txt`).
- An `OPENAI_API_KEY` (see `.env.example`) only if exercising the Sprint 2 Understanding layer
  (`tests/understanding/`) — the keyword-search endpoint and BM25/vector search need no LLM at all.

## Setup (normal — uses the checked-in, already-reviewed canonicalization data)

This is the path for anyone reproducing the project as checked in. It reuses the two reviewed
CSVs (`specs/001-conversational-search-baseline/{category,brand}_canonicalization_review.csv`)
exactly as committed — it does **not** regenerate them (see "Maintainer-only" below for why
that matters).

1. Start Postgres: `docker compose up -d` (this only runs
   `docker/postgres-init/01-extensions.sql`, which creates the `pg_trgm`/`pgcrypto`/`vector`
   extensions — it does **not** create any application tables on its own).
2. Apply the schema (creates `product`, `category`, `canonical_category`, `canonical_brand`,
   `brand_alias`, `product_category`, `product_embeddings`, `search_session`):
   `docker exec -i conv_search_postgres psql -U conv_search -d conv_search < src/models/schema.sql`
3. Load and transform the dump into Postgres:
   `python -m src.ingestion.load_dump --source data/spinneys_database.sql`
4. Apply the (already-reviewed) category canonicalization mapping:
   `python -m src.ingestion.category_canonicalization_apply`
   — Expected: 272 raw category records collapse to 244 canonical categories.
5. Apply the (already-reviewed) brand canonicalization mapping:
   `python -m src.ingestion.brand_normalization_apply`
   — Expected: 974 canonical brands from 1691 raw brand values.
   — Two DIFFERENT metrics, do not mix them: `brand_raw_en`/`brand_raw_ar` is present (either
   column non-empty) for 24,820/25,881 products (≈95.9%); `product.brand_normalized` ends up
   actually resolved for 17,315/25,881 products (≈67%) once the literal placeholder value
   "Please select a brand." (7,505 products) is excluded as junk rather than treated as a
   real brand.
6. Run the app: `uvicorn src.api.routes:app --reload` (or hit it in-process via
   `fastapi.testclient.TestClient`, as the test suite does). There is no separate "build the
   index" step or CLI — `src/search_engine/index.py`'s `get_index()` lazily builds the
   in-memory BM25 index (`SearchIndex.build_from_db()`) the first time a text search actually
   needs it, then caches it as a module-level singleton for the process's lifetime.
7. *(Optional, slow — only needed for vector/hybrid search, not for keyword-only BM25
   search)*: build embeddings per `src/ingestion/build_embeddings.py`'s own docstring
   (~5.4 hours for the full 25,881-product catalog on CPU). Not required to validate the
   scenarios below.

## Maintainer-only: regenerating the canonicalization mappings

`python -m src.ingestion.category_canonicalization` and
`python -m src.ingestion.brand_normalization` are the **generator** scripts — they read the
live `product`/`category` tables and **overwrite** the review CSVs above with fresh proposals,
resetting every `reviewer_decision` cell to blank. Never run these as part of normal setup —
doing so destroys the recorded human review decisions the checked-in CSVs represent. Only run
them if you are deliberately starting a new canonicalization review cycle (e.g. after loading
a materially different source dump), and re-review the output before ever running the
`_apply` scripts above against it.

## Validation scenarios

1. **Category + price filter**: query category=`Meat` (any of its 5 raw source spellings),
   price_max=100 EGP. Expected: only products from all 5 underlying "Meat"-equivalent
   category records are considered, all returned products have `price <= 100`, matching
   spec.md User Story 1 / FR-019.
2. **Zero-result correctness**: query a valid category with an unreasonably low price_max
   (e.g. 0.01 EGP). Expected: `SearchResult.zero_result == True`, empty `products`, no
   substituted results (FR-012).
3. **Bilingual name search**: query the English name of a known product, then its Arabic
   name (from `catalog_productname`) in a fresh request. Expected: same product returned by
   both, independent of `url_key` quality (data-model.md Product).
4. **Exact brand match**: query brand="Munchi" (a real value confirmed present in the
   corpus). Expected: non-empty results, `brand_normalized == "munchi"` for every result
   (canonical brand filtering is exact identity, not substring — a typo like "munshi" is
   still resolved first via fuzzy matching in `parse_keyword_query`, then filtered exactly);
   then query an invented brand not in the corpus. Expected: `zero_result == True`, not a
   fabricated/near match (FR-020).
5. **Uncategorized products remain searchable**: pick a known product with zero category
   links; query it by name with no category filter. Expected: it is returned. Query it again
   with any category filter applied. Expected: it is correctly excluded (research.md §4).

## Sprint 4: conversational endpoint

`POST /session/{session_id}/message` (body: `{"message": str}`, 1–500 chars) wires together
every already-built component into one turn pipeline: a pre-LLM System Guard
(`src/scenario/guard.py`) → `understand()` (`src/understanding/llm.py`) → two deterministic
Action repairs (`src/scenario/decision.py`) → `validate()`/`StateManager` or the deterministic
recommendation policy → `SearchAdapter` → deterministic response wording
(`src/response/messages.py`). Orchestration itself lives in `src/scenario/orchestrator.py`;
`src/api/routes.py` only wires it to FastAPI. Response `resolved_category`/`resolved_brand`/
`price_min`/`price_max` always reflect `StateManager.get_state()` **after** the turn — never
only the current turn's own mentioned fields.

Two ownership boundaries, deliberately kept separate:
- **StateManager** (`src/state_manager/state_manager.py`) owns canonical, user-stated search
  constraints only (category/brand/price/query_text) — unchanged since Sprint 3.
- **SessionActivity** (`src/scenario/session_activity.py`) owns runtime/conversational
  metadata only: bounded history for `understand()`'s continuity judgment, rapid-repeat
  bookkeeping, the accepted-turn counter, and the recommendation relaxation step. It never
  duplicates a canonical field.

Sprint 4 handles seven scenarios, all through the pipeline above (no second orchestration
path, no per-scenario special-casing beyond what's listed):

1. **off_topic** — a message with no product-search purpose (weather, jokes) gets a static
   refocus reply; no search, no state mutation, no history append; the turn still counts.
2. **recommendation_request / exploration** — "what do you recommend?", "show me more",
   "anything else?" reuse the CURRENT canonical search context; the LLM never invents a
   product or a budget. With an active price ceiling, up to `MAX_RELAXATION_STEPS=3`
   automatic price **bands** are explored (`RELAXATION_FACTOR=1.20`): band *N* is
   `[canonical_max × 1.20^(N-1), canonical_max × 1.20^N]` — e.g. a `≤100` search explores
   `100–120`, then `120–144`, then `144–172.8`. These bands are temporary, passed only to
   `SearchAdapter`, and **never** written back to `StateManager` — the user's canonical budget
   never changes because the system chose to explore wider. A bare recommendation with no
   active product target gets a clarification reply, never a whole-catalog search. An explicit
   new price in the same message (e.g. "under 150") is normal state-changing search instead,
   and resets the relaxation step — never both an explicit value and an automatic band on the
   same turn.
3. **out_of_catalog** — `likely_out_of_catalog` is a conservative, evidence-based signal only,
   never a certainty claim: it requires an actual zero-result search, non-empty searched free
   text, no resolved category/brand, and zero literal token overlap in the existing
   `SearchIndex` vocabulary (no new DB query, no new infrastructure). A zero-result search with
   a resolved category/brand is a filter combination that found nothing, not an out-of-catalog
   concept, and is worded accordingly ("I couldn't find any matching products for that
   search," never "we don't carry that").
4. **customer_service** — tone is orthogonal to intent: a frustrated message with real search
   content still executes that search normally; only a brief deterministic acknowledgment is
   prepended.
5. **prompt_injection** — user/history content is always untrusted message data, never
   instructions; there is no keyword blacklist anywhere in the guard or orchestration layer. A
   pure injection attempt is handled as ordinary `off_topic`; injection mixed with a real
   request still executes that real search.
6. **token_abuse** — a System Guard, never an LLM judgment: messages over 500 chars are
   rejected by the request schema before `understand()` is ever called; the 4th identical
   (normalized) message within a 30-second window is blocked the same way (the 1st, 2nd, and
   3rd all pass — `REPEAT_THRESHOLD=4` is deliberately one more than
   `MAX_RELAXATION_STEPS=3`, so a user exploring a recommendation by repeating the exact same
   phrase can still reach all three price bands). `SESSION_TURN_CAP=40` is non-blocking — the
   turn still executes, with a deterministic reset suggestion appended. No Redis, no Celery, no
   generic rate limiter.
7. **topic_switch** — unchanged Sprint 3 behavior: `understand()`'s bounded history lets it
   classify a genuinely unrelated new product as `search`, and `StateManager`'s existing
   replace-on-search semantics wipe the old filters. No second topic-switch mechanism.
