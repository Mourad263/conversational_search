"""Sprint 4 Part 3/4: a small REAL end-to-end walkthrough through the
actual POST /session/{session_id}/message endpoint -- real understand(),
real validate(), real StateManager, real SearchAdapter, real database.
Deliberately NOT a large real-LLM suite (see tests/understanding/
test_llm.py for that): one focused, continuous conversation covering
every Sprint-4 runtime behavior in sequence, per the Part 4 closure pass.

NOTE: unlike most of this suite, these calls hit a live, paid OpenAI API.
Requires OPENAI_API_KEY; skipped automatically otherwise.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api.routes import app  # noqa: E402
from src.models.config import settings  # noqa: E402

pytestmark = pytest.mark.skipif(
    not settings.openai_api_key,
    reason="OPENAI_API_KEY not configured -- Sprint 4 e2e walkthrough needs a real API call",
)

client = TestClient(app)


def test_conversational_session_full_sprint4_walkthrough():
    session_id = "sprint4-part4-walkthrough"

    # 1. milk under 50
    r1 = client.post(f"/session/{session_id}/message", json={"message": "I need milk under 50 pounds"})
    assert r1.status_code == 200
    b1 = r1.json()
    assert b1["resolved_category"] == "milk_29"
    assert b1["price_max"] == 50.0
    assert b1["total_count"] > 0
    assert len(b1["products"]) > 0
    assert all(isinstance(p["id"], int) for p in b1["products"])  # real catalog rows only

    # 2. also Juhayna
    r2 = client.post(f"/session/{session_id}/message", json={"message": "also from Juhayna"})
    b2 = r2.json()
    assert b2["resolved_category"] == "milk_29"
    assert b2["resolved_brand"] == "juhayna"
    assert b2["price_max"] == 50.0  # post-merge canonical state, not just turn 2's own field

    # 3. change price
    r3 = client.post(f"/session/{session_id}/message", json={"message": "actually make it under 30 instead"})
    b3 = r3.json()
    assert b3["resolved_category"] == "milk_29"
    assert b3["resolved_brand"] == "juhayna"
    assert b3["price_max"] == 30.0

    # 4. remove brand
    r4 = client.post(f"/session/{session_id}/message", json={"message": "never mind the brand"})
    b4 = r4.json()
    assert b4["resolved_category"] == "milk_29"
    assert b4["resolved_brand"] is None
    assert b4["price_max"] == 30.0  # unrelated filter untouched

    # 5. switch dairy target (same errand -> modify_filter on category, not a topic switch)
    r5 = client.post(f"/session/{session_id}/message", json={"message": "do you have cheese instead"})
    b5 = r5.json()
    assert b5["intent"] == "modify_filter"  # the actual semantic decision, not just the
    # resulting state -- this is the exact turn that regressed before the "instead"-vs-
    # topic-switch prompt fix (manual-acceptance boundary correction)
    assert b5["resolved_category"] == "cheese"
    assert b5["price_max"] == 30.0  # price carried over -- same errand

    # 6. topic switch to detergent (real, unrelated department -> old dairy state wiped)
    r6 = client.post(f"/session/{session_id}/message", json={"message": "Now I need detergent"})
    b6 = r6.json()
    assert b6["intent"] == "search"  # proves the "instead"-fix did not weaken real topic-switch
    assert b6["resolved_category"] == "detergents_19"
    assert b6["resolved_brand"] is None  # no leakage from turn 2/3
    assert b6["price_max"] is None  # no leakage from turn 3/5

    # 7. add price
    r7 = client.post(f"/session/{session_id}/message", json={"message": "under 100 pounds"})
    b7 = r7.json()
    assert b7["resolved_category"] == "detergents_19"
    assert b7["price_max"] == 100.0

    # 8. recommendation/exploration
    r8 = client.post(f"/session/{session_id}/message", json={"message": "show me more"})
    b8 = r8.json()
    assert b8["resolved_category"] == "detergents_19"
    assert b8["price_max"] == 100.0  # canonical unchanged by the automatic band
    assert b8["effective_price_min"] == 100.0
    assert b8["effective_price_max"] == 120.0

    # 9. RESET -- both StateManager and SessionActivity fully fresh
    r9 = client.post(f"/session/{session_id}/message", json={"message": "start over"})
    b9 = r9.json()
    assert b9["resolved_category"] is None
    assert b9["resolved_brand"] is None
    assert b9["price_min"] is None
    assert b9["price_max"] is None
    assert b9["effective_price_min"] is None
    assert b9["effective_price_max"] is None
