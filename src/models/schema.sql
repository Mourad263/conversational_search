-- Conversational Search Baseline -- target PostgreSQL schema (Sprint 0)
-- Source IDs are preserved (not resequenced) so canonicalization mappings and
-- evaluation records stay traceable back to the original MySQL dump rows.

CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;

-- ── Canonicalization output tables ──────────────────────────────────────────

CREATE TABLE IF NOT EXISTS canonical_category (
    id               SERIAL PRIMARY KEY,
    slug             TEXT NOT NULL UNIQUE,
    display_name_en  TEXT NOT NULL,
    display_name_ar  TEXT NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS category (
    id                     BIGINT PRIMARY KEY,
    parent_category_id     BIGINT NULL REFERENCES category(id),
    name_en                TEXT NOT NULL,
    name_ar                TEXT NOT NULL,
    integration_id         TEXT NULL,
    canonical_category_id  INT NULL REFERENCES canonical_category(id),
    is_junk                BOOLEAN NOT NULL DEFAULT FALSE,
    created_at             TIMESTAMPTZ,
    updated_at             TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_category_canonical_category_id ON category (canonical_category_id);
CREATE INDEX IF NOT EXISTS idx_category_parent ON category (parent_category_id);

-- ── Product ──────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS product (
    id                BIGINT PRIMARY KEY,
    sku               TEXT UNIQUE,
    name_en           TEXT NOT NULL,
    name_ar           TEXT NOT NULL,
    url_key           TEXT NULL,
    price             NUMERIC(12,2) NULL,
    special_price     NUMERIC(12,2) NULL,
    brand_raw_en      TEXT NULL,
    brand_raw_ar      TEXT NULL,
    brand_normalized  TEXT NULL,
    image_url         TEXT NULL,
    created_at        TIMESTAMPTZ,
    updated_at        TIMESTAMPTZ,
    CONSTRAINT price_nonnegative CHECK (price IS NULL OR price >= 0)
);
CREATE INDEX IF NOT EXISTS idx_product_price ON product (price);
CREATE INDEX IF NOT EXISTS idx_product_brand_normalized ON product (brand_normalized);
CREATE INDEX IF NOT EXISTS idx_product_name_en_trgm ON product USING GIN (name_en gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_product_name_ar_trgm ON product USING GIN (name_ar gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_product_brand_normalized_trgm ON product USING GIN (brand_normalized gin_trgm_ops);

CREATE TABLE IF NOT EXISTS product_category (
    product_id  BIGINT NOT NULL REFERENCES product(id),
    category_id BIGINT NOT NULL REFERENCES category(id),
    PRIMARY KEY (product_id, category_id)
);
CREATE INDEX IF NOT EXISTS idx_product_category_category_id ON product_category (category_id);

-- ── Product embeddings (Sprint 1b Part A -- dense/semantic search) ─────────
-- ibm-granite/granite-embedding-278m-multilingual, confirmed 768-dim output
-- (research.md's Sprint 1b section). One embedding per product, built from
-- name_en + name_ar + its canonical category name(s).

CREATE TABLE IF NOT EXISTS product_embeddings (
    product_id  BIGINT PRIMARY KEY REFERENCES product(id),
    embedding   vector(768) NOT NULL
);
-- HNSW index is built by src/ingestion/build_embeddings.py AFTER the bulk
-- load, not here -- building it against an empty table then trickling in
-- 25,881 rows one at a time is slower than a bulk build, and this project
-- wants the one-time build time actually measured as its own step.

-- ── Brand canonicalization output ───────────────────────────────────────────

CREATE TABLE IF NOT EXISTS canonical_brand (
    id            SERIAL PRIMARY KEY,
    slug          TEXT NOT NULL UNIQUE,
    display_name  TEXT NOT NULL,
    method        TEXT NOT NULL,
    confidence    NUMERIC(5,2) NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS brand_alias (
    raw_value           TEXT PRIMARY KEY,
    normalized_value    TEXT NOT NULL,
    script              TEXT NOT NULL,
    canonical_brand_id  INT NOT NULL REFERENCES canonical_brand(id)
);

-- ── Session state ────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS search_session (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    active_filters   JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_result_set  JSONB NOT NULL DEFAULT '[]'::jsonb,
    last_intent      TEXT NULL,
    languages_used   TEXT[] NOT NULL DEFAULT '{}'
);
