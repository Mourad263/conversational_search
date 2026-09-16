"""Sprint 0: extract the 6 target tables from data/spinneys_database.sql and
bulk-load them into PostgreSQL per src/models/schema.sql.

No MySQL server is used or required -- src.ingestion.dump_reader reads the
dump's text directly. This script only loads `category`/`product` raw data
and the flattened bilingual names/brand text; canonicalization
(category_canonicalization.py, brand_normalization.py) runs afterward as a
separate, human-reviewed step.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.ingestion.dump_reader import iter_table_rows  # noqa: E402
from src.models.config import settings  # noqa: E402

EXPECTED_COUNTS = {
    "product": 25_881,
    "category": 272,
    "categoryname_rows": 544,
    "productname_rows": 51_762,
    "productattributes_rows": 51_762,
    "product_category_links": 50_309,
}


def load_categories(dump_path: str) -> dict[int, dict]:
    categories: dict[int, dict] = {}
    for fields in iter_table_rows(dump_path, "catalog_category"):
        cid, parent_id, created_at, integration_id, updated_at = fields
        categories[int(cid)] = {
            "id": int(cid),
            "parent_category_id": int(parent_id) if parent_id is not None else None,
            "integration_id": integration_id,
            "created_at": created_at,
            "updated_at": updated_at,
            "name_en": None,
            "name_ar": None,
        }
    return categories


def apply_category_names(dump_path: str, categories: dict[int, dict]) -> int:
    count = 0
    for fields in iter_table_rows(dump_path, "catalog_categoryname"):
        _id, name, language, category_id = fields
        count += 1
        # Language validated BEFORE the entity-existence check below -- a
        # real, confirmed gap this fixes: checking language only after an
        # `if cat is None: continue` let a malformed row (unexpected
        # language AND an unknown category id) slip through silently,
        # since it never reached the language check at all. Unknown
        # entity + a VALID language is still tolerated, deliberately --
        # that's a separate, established loader behavior, not a language
        # problem.
        if language not in ("English", "Arabic"):
            raise ValueError(
                f"unexpected language {language!r} in catalog_categoryname "
                f"(id={_id}, category_id={category_id})"
            )
        cat = categories.get(int(category_id))
        if cat is None:
            continue
        if language == "English":
            cat["name_en"] = name
        else:
            cat["name_ar"] = name
    return count


def load_products(dump_path: str) -> dict[int, dict]:
    products: dict[int, dict] = {}
    for fields in iter_table_rows(dump_path, "catalog_product"):
        pid, created_at, sku, image, updated_at, url_key, price, special_price = fields
        products[int(pid)] = {
            "id": int(pid),
            "sku": sku,
            "image_url": image,
            "url_key": url_key,
            "price": float(price) if price is not None else None,
            "special_price": float(special_price) if special_price is not None else None,
            "created_at": created_at,
            "updated_at": updated_at,
            "name_en": None,
            "name_ar": None,
            "brand_raw_en": None,
            "brand_raw_ar": None,
        }
    return products


def apply_product_names(dump_path: str, products: dict[int, dict]) -> int:
    count = 0
    for fields in iter_table_rows(dump_path, "catalog_productname"):
        _id, name, language, _created_at, product_id = fields
        count += 1
        # Language validated before the entity-existence check -- see
        # apply_category_names() for why.
        if language not in ("English", "Arabic"):
            raise ValueError(
                f"unexpected language {language!r} in catalog_productname "
                f"(id={_id}, product_id={product_id})"
            )
        p = products.get(int(product_id))
        if p is None:
            continue
        if language == "English":
            p["name_en"] = name
        else:
            p["name_ar"] = name
    return count


def _extract_brand(attributes_json: str | None) -> str | None:
    if not attributes_json:
        return None
    try:
        attrs = json.loads(attributes_json)
    except (json.JSONDecodeError, TypeError):
        return None
    for entry in attrs:
        if entry.get("code") == "product_brand_id":
            value = entry.get("value")
            if isinstance(value, str) and value.strip():
                return value.strip()
            return None
    return None


def apply_product_attributes(dump_path: str, products: dict[int, dict]) -> int:
    count = 0
    for fields in iter_table_rows(dump_path, "catalog_productattributes"):
        _id, attributes_json, language, product_id = fields
        count += 1
        # Language validated before EITHER early exit below (unknown
        # entity, or no product_brand_id in this row's attributes) -- a
        # real, confirmed gap this fixes: a malformed-language row with no
        # brand attribute at all used to slip through silently via the
        # `if brand is None: continue` before the language check ever ran.
        if language not in ("English", "Arabic"):
            raise ValueError(
                f"unexpected language {language!r} in catalog_productattributes "
                f"(id={_id}, product_id={product_id})"
            )
        p = products.get(int(product_id))
        if p is None:
            continue
        brand = _extract_brand(attributes_json)
        if brand is None:
            continue
        if language == "English":
            p["brand_raw_en"] = brand
        else:
            p["brand_raw_ar"] = brand
    return count


def load_product_categories(dump_path: str) -> list[tuple[int, int]]:
    links: list[tuple[int, int]] = []
    for fields in iter_table_rows(dump_path, "catalog_product_categories"):
        _id, product_id, category_id = fields
        links.append((int(product_id), int(category_id)))
    return links


def find_invalid_links(
    links: list[tuple[int, int]], products: dict[int, dict], categories: dict[int, dict]
) -> list[tuple[int, int]]:
    """product_category links whose product_id/category_id was never
    loaded. Must be empty for a clean load -- a real, confirmed gap this
    replaces: write_to_postgres() used to silently drop such links inside
    its COPY loop instead of failing the load, so a bad source reference
    could silently reduce data completeness with no signal at all."""
    valid_products = set(products)
    valid_categories = set(categories)
    return [(pid, cid) for pid, cid in links if pid not in valid_products or cid not in valid_categories]


def find_missing_bilingual_names(records: dict[int, dict]) -> list[int]:
    """ids (of either a products dict or a categories dict -- both share
    this name_en/name_ar shape) whose English or Arabic name is missing
    or empty. Must be empty for a clean load -- previously never checked
    at all; the only prior guarantee was a gross row COUNT matching, which
    doesn't prove every counted row actually reached a name field."""
    return [rid for rid, r in records.items() if not r.get("name_en") or not r.get("name_ar")]


def write_to_postgres(
    conn: psycopg.Connection,
    categories: dict[int, dict],
    products: dict[int, dict],
    links: list[tuple[int, int]],
) -> None:
    """Assumes the caller (main()) has already validated `links` against
    `products`/`categories` via find_invalid_links() -- every link here is
    written unconditionally, no silent per-row filtering."""
    with conn.cursor() as cur:
        cur.execute("TRUNCATE product_category, brand_alias, canonical_brand, "
                    "search_session, product, category, canonical_category RESTART IDENTITY CASCADE")

        with cur.copy(
            "COPY category (id, parent_category_id, name_en, name_ar, integration_id, "
            "created_at, updated_at) FROM STDIN"
        ) as copy:
            for c in categories.values():
                copy.write_row((
                    c["id"], c["parent_category_id"], c["name_en"] or "",
                    c["name_ar"] or "", c["integration_id"], c["created_at"], c["updated_at"],
                ))

        with cur.copy(
            "COPY product (id, sku, name_en, name_ar, url_key, price, special_price, "
            "brand_raw_en, brand_raw_ar, image_url, created_at, updated_at) FROM STDIN"
        ) as copy:
            for p in products.values():
                copy.write_row((
                    p["id"], p["sku"], p["name_en"] or "", p["name_ar"] or "",
                    p["url_key"], p["price"], p["special_price"],
                    p["brand_raw_en"], p["brand_raw_ar"], p["image_url"],
                    p["created_at"], p["updated_at"],
                ))

        with cur.copy(
            "COPY product_category (product_id, category_id) FROM STDIN"
        ) as copy:
            for product_id, category_id in links:
                copy.write_row((product_id, category_id))

    conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="data/spinneys_database.sql")
    args = parser.parse_args()

    print(f"Reading categories from {args.source} ...")
    categories = load_categories(args.source)
    catname_rows = apply_category_names(args.source, categories)
    print(f"  {len(categories)} categories, {catname_rows} categoryname rows")

    print("Reading products ...")
    products = load_products(args.source)
    prodname_rows = apply_product_names(args.source, products)
    print(f"  {len(products)} products, {prodname_rows} productname rows")

    print("Reading product attributes (brand extraction) ...")
    attr_rows = apply_product_attributes(args.source, products)
    print(f"  {attr_rows} productattributes rows scanned")

    print("Reading product-category links ...")
    links = load_product_categories(args.source)
    print(f"  {len(links)} product_category links")

    # Validation gate: fail loudly on mismatch, per research.md's ingestion
    # design. Explicit exceptions, never `assert` -- `python -O` compiles
    # every `assert` statement to a no-op (confirmed empirically: the
    # exact same check that raises AssertionError under normal `python`
    # silently passes under `python -O`), which would silently disable
    # every one of these destructive-write guards.
    if len(products) != EXPECTED_COUNTS["product"]:
        raise ValueError(f"expected {EXPECTED_COUNTS['product']} products, got {len(products)}")
    if len(categories) != EXPECTED_COUNTS["category"]:
        raise ValueError(f"expected {EXPECTED_COUNTS['category']} categories, got {len(categories)}")
    if catname_rows != EXPECTED_COUNTS["categoryname_rows"]:
        raise ValueError(
            f"expected {EXPECTED_COUNTS['categoryname_rows']} categoryname rows, got {catname_rows}"
        )
    if prodname_rows != EXPECTED_COUNTS["productname_rows"]:
        raise ValueError(
            f"expected {EXPECTED_COUNTS['productname_rows']} productname rows, got {prodname_rows}"
        )
    if attr_rows != EXPECTED_COUNTS["productattributes_rows"]:
        raise ValueError(
            f"expected {EXPECTED_COUNTS['productattributes_rows']} productattributes rows, got {attr_rows}"
        )
    if len(links) != EXPECTED_COUNTS["product_category_links"]:
        # A truncated-but-internally-consistent product_category section
        # (every parsed link still references a loaded product/category)
        # would otherwise pass find_invalid_links() below with zero
        # complaints -- this is the only check that catches fewer links
        # existing in the first place, not just bad references among
        # whatever was actually parsed.
        raise ValueError(
            f"expected {EXPECTED_COUNTS['product_category_links']} product_category links, "
            f"got {len(links)}"
        )

    missing_product_names = find_missing_bilingual_names(products)
    if missing_product_names:
        raise ValueError(
            f"{len(missing_product_names)} products missing an English or Arabic name: "
            f"{missing_product_names[:20]}"
        )
    missing_category_names = find_missing_bilingual_names(categories)
    if missing_category_names:
        raise ValueError(
            f"{len(missing_category_names)} categories missing an English or Arabic name: "
            f"{missing_category_names[:20]}"
        )
    invalid_links = find_invalid_links(links, products, categories)
    if invalid_links:
        raise ValueError(
            f"{len(invalid_links)} product_category links reference a product/category that "
            f"wasn't loaded: {invalid_links[:20]}"
        )

    print(f"Connecting to {settings.database_url!r} ...")
    with psycopg.connect(settings.database_url.replace("postgresql+psycopg://", "postgresql://")) as conn:
        print("Writing to Postgres ...")
        write_to_postgres(conn, categories, products, links)

    brand_count = sum(1 for p in products.values() if p["brand_raw_en"] or p["brand_raw_ar"])
    uncategorized = len(products) - len({pid for pid, _ in links if pid in products})
    print("Done.")
    print(f"  products with a brand value: {brand_count} ({100 * brand_count / len(products):.1f}%)")
    print(f"  uncategorized products: {uncategorized} ({100 * uncategorized / len(products):.1f}%)")


if __name__ == "__main__":
    main()
