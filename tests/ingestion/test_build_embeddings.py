"""Sprint 1b rebuild-safety fix (independent audit, 2026-09) to
build_embeddings.py's --sample-size guard. Pure function, no DB, no
embedding model -- the embedding job itself is never run by this suite.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest  # noqa: E402

from src.ingestion.build_embeddings import check_sample_size_safe  # noqa: E402


def test_refuses_sample_smaller_than_an_existing_full_table():
    """The real destructive case this fixes: a prior full run left 25,881
    rows, and --sample-size 2000 would otherwise TRUNCATE straight through
    them unconditionally."""
    with pytest.raises(RuntimeError, match="25881"):
        check_sample_size_safe(existing_count=25_881, sample_size=2000)


def test_allows_sample_when_table_is_empty():
    check_sample_size_safe(existing_count=0, sample_size=2000)  # must not raise


def test_allows_sample_when_existing_rows_are_within_the_requested_size():
    check_sample_size_safe(existing_count=1500, sample_size=2000)  # must not raise


def test_allows_sample_exactly_equal_to_existing_count():
    check_sample_size_safe(existing_count=2000, sample_size=2000)  # boundary: not > , must not raise


def test_no_bare_assert_statements_guard_destructive_validation():
    """`python -O` compiles every bare `assert` to a no-op, silently
    disabling a destructive-write guard -- confirmed empirically
    elsewhere in this project. Statically confirms none remain here."""
    import ast

    source_path = Path(__file__).resolve().parents[2] / "src" / "ingestion" / "build_embeddings.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    asserts = [node for node in ast.walk(tree) if isinstance(node, ast.Assert)]
    assert asserts == []
