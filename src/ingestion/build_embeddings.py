"""Sprint 1b Part A, step 3: one-time batch script -- encode every product
into product_embeddings, then build the HNSW index (built AFTER the bulk
load, not before, so the index build itself can be measured as one step
rather than 25,881 incremental inserts into a live index).

Product text = name_en + name_ar + its canonical category name(s) (English)
-- catalog_productname EN+AR is exactly what we already have from Sprint 0;
category adds topical signal for products whose name alone is ambiguous.
Uncategorized products (19.1%, research.md §4) just get name_en + name_ar.

USAGE -- the real, full 25,881-product run (not done in-session; run this
yourself, e.g. overnight):

    python -m src.ingestion.build_embeddings

No arguments = the complete catalog. Measured throughput on this hardware
(CPU, batch_size=1 -- verified faster than batching here, see
embeddings.py): ~754ms/item -> roughly 5.4 hours end to end. Needs Postgres
up (`docker compose up -d`) and the schema applied first. Safe to re-run:
TRUNCATEs product_embeddings before writing, and now also DROPs the HNSW
index first so a rerun is a true bulk build, not incremental inserts into
an index that never went away (TRUNCATE alone preserves an existing
index -- confirmed empirically -- so without the explicit DROP here, a
second run's final CREATE INDEX IF NOT EXISTS step would silently be a
no-op, not a real rebuild, defeating the whole reason the index is built
AFTER the load rather than before).

For a quick end-to-end smoke test instead of the full run:

    python -m src.ingestion.build_embeddings --sample-size 2000
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import psycopg  # noqa: E402
from pgvector import Vector  # noqa: E402
from pgvector.psycopg import register_vector  # noqa: E402

from src.models.config import settings  # noqa: E402
from src.search_engine.embeddings import embed_batch  # noqa: E402

EXPECTED_PRODUCT_COUNT = 25_881


def _connect() -> psycopg.Connection:
    url = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
    conn = psycopg.connect(url)
    register_vector(conn)
    return conn


def build_product_texts(conn: psycopg.Connection) -> list[tuple[int, str]]:
    with conn.cursor() as cur:
        cur.execute("SELECT id, name_en, name_ar FROM product ORDER BY id")
        products = cur.fetchall()

        cur.execute("""
            SELECT pc.product_id, cc.display_name_en
            FROM product_category pc
            JOIN category c ON c.id = pc.category_id
            JOIN canonical_category cc ON cc.id = c.canonical_category_id
            WHERE c.canonical_category_id IS NOT NULL
        """)
        categories_by_product: dict[int, set[str]] = {}
        for product_id, cat_name in cur.fetchall():
            categories_by_product.setdefault(product_id, set()).add(cat_name)

    texts = []
    for product_id, name_en, name_ar in products:
        cats = categories_by_product.get(product_id)
        parts = [name_en or "", name_ar or ""]
        if cats:
            parts.append(", ".join(sorted(cats)))
        texts.append((product_id, " ".join(p for p in parts if p)))
    return texts


def check_sample_size_safe(existing_count: int, sample_size: int) -> None:
    """Refuse a --sample-size run that would TRUNCATE a table already
    holding MORE real rows than the requested sample -- a real, confirmed
    destructive-overwrite risk: TRUNCATE runs unconditionally regardless
    of --sample-size, so an accidental sample run after a full rebuild
    used to silently replace the complete 25,881-row table with a small
    sample, with no guard at all."""
    if existing_count > sample_size:
        raise RuntimeError(
            f"product_embeddings already has {existing_count} rows, more than the "
            f"requested --sample-size {sample_size} -- refusing to truncate a larger/"
            f"complete table down to a smaller sample. Run without --sample-size for a "
            f"real full rebuild, or pass --sample-size >= {existing_count}."
        )


MILK_MARKERS = ("milk", "حليب", "لبن")


def select_sample(
    texts: list[tuple[int, str]], sample_size: int, seed: int = 42
) -> list[tuple[int, str]]:
    """Deterministic random sample, PLUS every product whose text mentions
    milk (EN/AR) force-included -- this run exists specifically to prove
    the "milq" -> "milk" typo/cross-lingual case end-to-end, and a pure
    random sample of ~10% of the catalog isn't guaranteed to include any
    milk product at all."""
    milk_forced = [t for t in texts if any(m in t[1].lower() for m in MILK_MARKERS)]
    if len(milk_forced) > sample_size:
        # Bug found via a real run: sample_size=5 silently ran all 1,043
        # milk products because milk_forced was never capped -- cap it
        # deterministically (same seed) rather than assume sample_size is
        # always >= the milk-marker count.
        rng = random.Random(seed)
        milk_forced = rng.sample(milk_forced, sample_size)
    milk_ids = {pid for pid, _ in milk_forced}
    remaining = [t for t in texts if t[0] not in milk_ids]

    rng = random.Random(seed)
    n_random = max(0, sample_size - len(milk_forced))
    random_sample = rng.sample(remaining, min(n_random, len(remaining)))

    combined = milk_forced + random_sample
    print(f"  sample: {len(combined)} products ({len(milk_forced)} milk-marker products "
          f"force-included, {len(random_sample)} random, seed={seed})")
    return combined


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sample-size", type=int, default=None,
        help="If given, embed only a deterministic sample of this many products "
             "(plus all milk-marker products) instead of the full catalog. "
             "Omit for the real full-catalog run.",
    )
    args = parser.parse_args()

    conn = _connect()

    print("Building product text (name_en + name_ar + canonical category names) ...")
    texts = build_product_texts(conn)
    # Explicit exception, not `assert` -- `python -O` compiles every bare
    # `assert` to a no-op (confirmed empirically elsewhere in this
    # project), which would silently disable this guard right before the
    # destructive TRUNCATE + rewrite below.
    if len(texts) != EXPECTED_PRODUCT_COUNT:
        raise ValueError(f"expected {EXPECTED_PRODUCT_COUNT} products, got {len(texts)}")
    print(f"  {len(texts)} products in the full catalog")

    if args.sample_size is not None:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM product_embeddings")
            existing_count = cur.fetchone()[0]
        check_sample_size_safe(existing_count, args.sample_size)
        texts = select_sample(texts, args.sample_size)

    ids = [pid for pid, _ in texts]
    text_values = [t for _, t in texts]

    print(f"Encoding {len(text_values)} products with "
          f"ibm-granite/granite-embedding-278m-multilingual (CPU) ...")
    t0 = time.time()
    embeddings = embed_batch(text_values, batch_size=1)
    encode_time = time.time() - t0
    print(f"  encoded in {encode_time:.1f}s ({encode_time / len(text_values) * 1000:.1f}ms/item)")

    print("Writing to product_embeddings ...")
    t0 = time.time()
    with conn.cursor() as cur:
        # Drop any existing HNSW index before the bulk write -- TRUNCATE
        # alone preserves it (confirmed empirically), and writing into a
        # pre-existing index is a series of incremental inserts, not the
        # true bulk build this script's timing/design is meant to measure
        # (see the module docstring).
        cur.execute("DROP INDEX IF EXISTS idx_product_embeddings_hnsw")
        cur.execute("TRUNCATE product_embeddings")
        with cur.copy("COPY product_embeddings (product_id, embedding) FROM STDIN") as copy:
            for pid, vec in zip(ids, embeddings):
                # register_vector() adapts numpy/Vector types for normal
                # query execution, but COPY's row writer serializes a bare
                # Python list as a Postgres ARRAY literal ("{...}"), not a
                # pgvector literal ("[...]") -- wrap explicitly. Found via
                # a real failure: "Vector contents must start with '['."
                copy.write_row((pid, Vector(vec)))
    conn.commit()
    write_time = time.time() - t0
    print(f"  wrote {len(ids)} rows in {write_time:.1f}s")

    print("Building HNSW index (vector_cosine_ops) ...")
    t0 = time.time()
    with conn.cursor() as cur:
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_product_embeddings_hnsw "
            "ON product_embeddings USING hnsw (embedding vector_cosine_ops)"
        )
    conn.commit()
    index_time = time.time() - t0
    print(f"  HNSW index built in {index_time:.1f}s")

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM product_embeddings")
        count = cur.fetchone()[0]
    conn.close()

    print("Done.")
    print(f"  product_embeddings rows: {count}")
    print(f"  encode: {encode_time:.1f}s, write: {write_time:.1f}s, "
          f"HNSW build: {index_time:.1f}s, total: {encode_time + write_time + index_time:.1f}s")


if __name__ == "__main__":
    main()
