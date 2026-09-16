"""Sprint 0 rebuild-safety fixes (independent audit, 2026-09) to
load_dump.py's validation gate.

Deliberately hermetic: tiny synthetic dump-format snippets (matching the
real mysqldump INSERT-statement text load_dump.py actually parses), not
the real 791MB data/spinneys_database.sql -- and the two new pure
completeness helpers are tested directly on hand-built dicts, no file I/O
at all.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest  # noqa: E402

from src.ingestion.load_dump import (  # noqa: E402
    EXPECTED_COUNTS,
    apply_category_names,
    apply_product_attributes,
    apply_product_names,
    find_invalid_links,
    find_missing_bilingual_names,
)


# --- apply_*: unexpected language values must be a hard error, not a
# silent skip (previously: silently ignored, but still counted toward the
# row-count total the caller checks) ---

def test_apply_category_names_accepts_clean_english_and_arabic(tmp_path):
    dump = tmp_path / "dump.sql"
    dump.write_text(
        "INSERT INTO `catalog_categoryname` VALUES "
        "(1,'Snacks','English',10),(2,'وجبات خفيفة','Arabic',10);\n",
        encoding="utf-8",
    )
    categories = {10: {"name_en": None, "name_ar": None}}
    count = apply_category_names(str(dump), categories)
    assert count == 2
    assert categories[10]["name_en"] == "Snacks"
    assert categories[10]["name_ar"] == "وجبات خفيفة"


def test_apply_category_names_rejects_unexpected_language(tmp_path):
    dump = tmp_path / "dump.sql"
    dump.write_text(
        "INSERT INTO `catalog_categoryname` VALUES "
        "(1,'Snacks','English',10),(2,'Collation','French',10);\n",
        encoding="utf-8",
    )
    categories = {10: {"name_en": None, "name_ar": None}}
    with pytest.raises(ValueError, match="French"):
        apply_category_names(str(dump), categories)


def test_apply_product_names_rejects_unexpected_language(tmp_path):
    dump = tmp_path / "dump.sql"
    dump.write_text(
        "INSERT INTO `catalog_productname` VALUES "
        "(1,'Milk','English','2020-01-01 00:00:00',100),"
        "(2,'???','Klingon','2020-01-01 00:00:00',100);\n",
        encoding="utf-8",
    )
    products = {100: {"name_en": None, "name_ar": None}}
    with pytest.raises(ValueError, match="Klingon"):
        apply_product_names(str(dump), products)


def test_apply_product_attributes_rejects_unexpected_language(tmp_path):
    dump = tmp_path / "dump.sql"
    dump.write_text(
        'INSERT INTO `catalog_productattributes` VALUES '
        '(1,\'[{"code":"product_brand_id","value":"Nike"}]\',\'English\',100),'
        '(2,\'[{"code":"product_brand_id","value":"Nike"}]\',\'Martian\',100);\n',
        encoding="utf-8",
    )
    products = {100: {"brand_raw_en": None, "brand_raw_ar": None}}
    with pytest.raises(ValueError, match="Martian"):
        apply_product_attributes(str(dump), products)


# --- Language validation must fire BEFORE the entity-existence/brand-
# presence early exits, not after (independent audit, 2026-09): a
# malformed row used to slip through silently whenever it ALSO referenced
# an unknown product/category or had no brand attribute, since the old
# language check sat after those early `continue`s and never ran. ---

def test_apply_category_names_rejects_bad_language_even_with_unknown_category_id(tmp_path):
    dump = tmp_path / "dump.sql"
    dump.write_text(
        "INSERT INTO `catalog_categoryname` VALUES (1,'Zzz','Klingon',99999);\n",
        encoding="utf-8",
    )
    categories = {10: {"name_en": None, "name_ar": None}}  # 99999 does not exist
    with pytest.raises(ValueError, match="Klingon"):
        apply_category_names(str(dump), categories)


def test_apply_product_names_rejects_bad_language_even_with_unknown_product_id(tmp_path):
    dump = tmp_path / "dump.sql"
    dump.write_text(
        "INSERT INTO `catalog_productname` VALUES (1,'Zzz','Klingon','2020-01-01 00:00:00',99999);\n",
        encoding="utf-8",
    )
    products = {100: {"name_en": None, "name_ar": None}}  # 99999 does not exist
    with pytest.raises(ValueError, match="Klingon"):
        apply_product_names(str(dump), products)


def test_apply_product_attributes_rejects_bad_language_with_no_brand_attribute_at_all(tmp_path):
    """The exact scenario that used to slip through: a row with an
    unexpected language AND no product_brand_id in its attributes JSON --
    the old code's `if brand is None: continue` ran before the language
    check ever had a chance to fire."""
    dump = tmp_path / "dump.sql"
    dump.write_text(
        'INSERT INTO `catalog_productattributes` VALUES '
        '(1,\'[{"code":"some_other_attr","value":"x"}]\',\'Martian\',100);\n',
        encoding="utf-8",
    )
    products = {100: {"brand_raw_en": None, "brand_raw_ar": None}}
    with pytest.raises(ValueError, match="Martian"):
        apply_product_attributes(str(dump), products)


def test_apply_product_attributes_rejects_bad_language_with_unknown_product_id(tmp_path):
    dump = tmp_path / "dump.sql"
    dump.write_text(
        'INSERT INTO `catalog_productattributes` VALUES '
        '(1,\'[{"code":"product_brand_id","value":"Nike"}]\',\'Martian\',99999);\n',
        encoding="utf-8",
    )
    products = {100: {"brand_raw_en": None, "brand_raw_ar": None}}  # 99999 does not exist
    with pytest.raises(ValueError, match="Martian"):
        apply_product_attributes(str(dump), products)


def test_valid_language_with_unknown_entity_is_still_a_tolerated_noop(tmp_path):
    """Preserves the established, intentional loader tolerance: a row
    referencing an entity that was never loaded is silently skipped when
    its language IS valid -- this must not be conflated with the
    unexpected-language checks above."""
    dump = tmp_path / "dump.sql"
    dump.write_text(
        "INSERT INTO `catalog_productname` VALUES (1,'Ghost','English','2020-01-01 00:00:00',99999);\n",
        encoding="utf-8",
    )
    products = {100: {"name_en": None, "name_ar": None}}
    count = apply_product_names(str(dump), products)
    assert count == 1
    assert products[100]["name_en"] is None  # untouched, not an error


def test_expected_product_category_links_count_is_the_verified_authoritative_value():
    assert EXPECTED_COUNTS["product_category_links"] == 50_309


def test_no_bare_assert_statements_guard_destructive_validation():
    """`python -O` compiles every bare `assert` to a no-op (confirmed
    empirically elsewhere in this project), which would silently disable
    every one of load_dump.py's destructive-write guards. Statically
    confirms none remain -- a permanent regression guard against a future
    edit reintroducing one."""
    import ast

    source_path = Path(__file__).resolve().parents[2] / "src" / "ingestion" / "load_dump.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    asserts = [node for node in ast.walk(tree) if isinstance(node, ast.Assert)]
    assert asserts == []


# --- find_invalid_links: a real, confirmed gap -- these used to be
# silently dropped inside write_to_postgres()'s COPY loop instead of
# failing the load ---

def test_find_invalid_links_flags_a_link_to_an_unloaded_product():
    links = [(1, 10), (999, 10)]
    products = {1: {}}
    categories = {10: {}}
    assert find_invalid_links(links, products, categories) == [(999, 10)]


def test_find_invalid_links_flags_a_link_to_an_unloaded_category():
    links = [(1, 10), (1, 999)]
    products = {1: {}}
    categories = {10: {}}
    assert find_invalid_links(links, products, categories) == [(1, 999)]


def test_find_invalid_links_empty_when_all_links_reference_loaded_rows():
    links = [(1, 10), (2, 11)]
    products = {1: {}, 2: {}}
    categories = {10: {}, 11: {}}
    assert find_invalid_links(links, products, categories) == []


# --- find_missing_bilingual_names: previously never checked at all,
# only a gross row-count total was validated ---

def test_find_missing_bilingual_names_flags_missing_arabic():
    records = {1: {"name_en": "Milk", "name_ar": None}, 2: {"name_en": "Juice", "name_ar": "عصير"}}
    assert find_missing_bilingual_names(records) == [1]


def test_find_missing_bilingual_names_flags_empty_string_as_missing():
    records = {1: {"name_en": "Milk", "name_ar": ""}}
    assert find_missing_bilingual_names(records) == [1]


def test_find_missing_bilingual_names_empty_when_all_records_are_complete():
    records = {1: {"name_en": "Milk", "name_ar": "لبن"}, 2: {"name_en": "Juice", "name_ar": "عصير"}}
    assert find_missing_bilingual_names(records) == []
