"""Real HTTP-layer test of the FastAPI keyword-search endpoint (via
TestClient, which exercises actual request/response validation -- not the
Python functions directly)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient  # noqa: E402

from src.api.routes import app  # noqa: E402

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_search_endpoint_returns_results():
    r = client.get("/search/keyword", params={"q": "meat under 100"})
    assert r.status_code == 200
    data = r.json()
    assert data["resolved_category"] == "meat"
    assert data["price_max"] == 100.0
    assert not data["zero_result"]
    assert len(data["products"]) == data["total_count"] == 2


def test_search_endpoint_zero_result_case():
    r = client.get("/search/keyword", params={"q": "meat under 0.01"})
    assert r.status_code == 200
    data = r.json()
    assert data["zero_result"] is True
    assert data["products"] == []
    assert data["total_count"] == 0


def test_search_endpoint_rejects_missing_query():
    r = client.get("/search/keyword")
    assert r.status_code == 422  # FastAPI/Pydantic validation, not a 500
