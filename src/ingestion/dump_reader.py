"""Streaming extractor for the 6 target tables in data/spinneys_database.sql.

Each INSERT statement in this mysqldump is a single line (extended-insert
batches many row-tuples into one statement, but never splits a statement
across lines) -- verified empirically against the real file, so a simple
line-by-line scan is sufficient: for the ~23 out-of-scope tables we only
look at the line's byte prefix (cheap), and only run the tuple/field parser
on lines belonging to one of the 6 tables this feature needs. No MySQL
server is available or required -- this reads the dump's text directly.
"""

from __future__ import annotations

from collections.abc import Iterator

TARGET_TABLES = (
    "catalog_product",
    "catalog_productname",
    "catalog_category",
    "catalog_categoryname",
    "catalog_product_categories",
    "catalog_productattributes",
)

_MYSQL_ESCAPES = {
    "'": "'",
    '"': '"',
    "\\": "\\",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "0": "\0",
    "Z": "\x1a",
}


def mysql_unescape(raw: str) -> str | None:
    """Unescape a single field's raw source text. Returns None for NULL,
    the unescaped string content for a quoted string, or the raw literal
    text for a bare numeric/boolean token."""
    raw = raw.strip()
    if raw == "NULL":
        return None
    if len(raw) >= 2 and raw[0] == "'" and raw[-1] == "'":
        inner = raw[1:-1]
        out: list[str] = []
        i = 0
        n = len(inner)
        while i < n:
            c = inner[i]
            if c == "\\" and i + 1 < n:
                out.append(_MYSQL_ESCAPES.get(inner[i + 1], inner[i + 1]))
                i += 2
                continue
            out.append(c)
            i += 1
        return "".join(out)
    return raw


def split_top_level(s: str, sep: str = ",") -> list[str]:
    """Split on a top-level separator, quote-aware (MySQL backslash escaping,
    not CSV doubled-quote escaping) so commas inside quoted strings --
    including embedded JSON -- are never mistaken for field separators."""
    fields: list[str] = []
    buf: list[str] = []
    in_quotes = False
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if in_quotes:
            if c == "\\" and i + 1 < n:
                buf.append(c)
                buf.append(s[i + 1])
                i += 2
                continue
            buf.append(c)
            if c == "'":
                in_quotes = False
            i += 1
            continue
        if c == "'":
            in_quotes = True
            buf.append(c)
            i += 1
            continue
        if c == sep:
            fields.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(c)
        i += 1
    fields.append("".join(buf))
    return fields


def extract_tuples(s: str) -> list[str]:
    """Find top-level (...) tuple boundaries in a VALUES list, quote-aware,
    so a stray '(' or ')' inside a quoted string (e.g. embedded JSON text)
    never prematurely opens/closes a tuple."""
    tuples: list[str] = []
    depth = 0
    in_quotes = False
    start = 0
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if in_quotes:
            if c == "\\" and i + 1 < n:
                i += 2
                continue
            if c == "'":
                in_quotes = False
            i += 1
            continue
        if c == "'":
            in_quotes = True
            i += 1
            continue
        if c == "(":
            if depth == 0:
                start = i + 1
            depth += 1
            i += 1
            continue
        if c == ")":
            depth -= 1
            if depth == 0:
                tuples.append(s[start:i])
            i += 1
            continue
        i += 1
    return tuples


def iter_table_rows(dump_path: str, table: str) -> Iterator[list[str | None]]:
    """Yield one list-of-fields per row for `table`, in file order."""
    prefix = f"INSERT INTO `{table}` VALUES "
    with open(dump_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if not line.startswith(prefix):
                continue
            values_part = line[len(prefix):].rstrip("\n")
            if values_part.endswith(";"):
                values_part = values_part[:-1]
            for tup in extract_tuples(values_part):
                yield [mysql_unescape(field) for field in split_top_level(tup)]
