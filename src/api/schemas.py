"""FastAPI request/response Pydantic models -- the third of the three
Pydantic usage sites named in plan.md (LLM Action schema and the
conversational session response below are the other two)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ProductOut(BaseModel):
    id: int
    name_en: str
    name_ar: str
    price: float | None
    special_price: float | None
    brand_normalized: str | None
    url_key: str | None
    sku: str | None


class KeywordSearchResponse(BaseModel):
    query: str
    resolved_category: str | None
    resolved_brand: str | None
    price_min: float | None
    price_max: float | None
    products: list[ProductOut]
    total_count: int
    zero_result: bool
    limit: int
    offset: int


class SessionMessageRequest(BaseModel):
    # Enforced here (Pydantic/FastAPI layer) so an oversized message is
    # rejected with a 422 before src/scenario/orchestrator.py -- and
    # therefore understand()/OpenAI -- is ever reached (Sprint 4 Part 3),
    # same bound as /search/keyword's `q` (routes.py).
    message: str = Field(..., min_length=1, max_length=500)


class SessionMessageResponse(BaseModel):
    """Sprint 4 Part 3 conversational turn response. resolved_category/
    resolved_brand/price_min/price_max always reflect the CURRENT
    canonical StateManager state after this turn (never only the current
    turn's own mentioned fields) -- see src/scenario/orchestrator.py.
    effective_price_min/effective_price_max are populated ONLY during an
    automatic recommendation-exploration price-band turn; they are never
    the user's canonical budget and are never written back into
    StateManager."""

    session_id: str
    message: str | None  # deterministic wording (off-topic/clarification/
    # acknowledgment/zero-result/...); null for an ordinary successful
    # search turn with nothing extra to say
    intent: str  # the effective intent this turn resolved to, after
    # deterministic normalization/repair (src/scenario/decision.py)
    resolved_category: str | None
    resolved_brand: str | None
    price_min: float | None
    price_max: float | None
    effective_price_min: float | None = None
    effective_price_max: float | None = None
    products: list[ProductOut]
    total_count: int
    zero_result: bool
    likely_out_of_catalog: bool = False
    blocked: bool = False  # true only for a rapid-repeat-blocked request
    recommendations: list[ProductOut] = Field(default_factory=list)  # Sprint 6
    # recommendation task: ML-generated (K=128 content-clustering) catalog-backed
    # ALTERNATIVES, distinct from `products` (the direct search-result set).
    # Populated only when action.recommendation_request is true AND real search
    # evidence + an active filter target exist; [] otherwise -- never a fallback
    # or a relaxed/looser result set. See src/recommendation/service.py.
    assistant_message: str = ""  # Task 3A: a natural, ALWAYS-populated bilingual
    # (EN/AR) conversational reply -- separate from `message` above, whose
    # existing (often-null, supplementary-note) meaning is unchanged. Built
    # deterministically from already-known signals only, never a catalog fact
    # the system doesn't actually have. See src/response/messages.py.
