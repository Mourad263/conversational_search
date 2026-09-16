"""Sprint 6 observability task: one lightweight, server-side-only trace per
conversational message (src/scenario/orchestrator.py's handle_message()).
Observation only -- never influences routing/behavior, never reaches the
customer-facing API response (src/api/schemas.py's SessionMessageResponse
has no trace fields). No OpenTelemetry/Prometheus/DB -- one dataclass, one
structured log line via the existing `logging` module.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class RequestTrace:
    session_id: str
    route: str = "unknown"  # the actual branch handle_message took, e.g.
    # shopping_search/recommendation/memory_recall/off_topic/reset/blocked/error
    total_latency_ms: float | None = None

    llm_calls: int = 0  # incremented only when understand_fn is actually invoked
    llm_input_tokens: int | None = None  # real usage.prompt_tokens, never estimated
    llm_output_tokens: int | None = None  # real usage.completion_tokens
    llm_total_tokens: int | None = None  # real usage.total_tokens

    validation_calls: int = 0  # validate() actually called
    search_calls: int = 0  # search_fn actually called (direct search + any
    # embedded in recommendation evidence-gathering)
    recommendation_calls: int = 0  # RecommendationService.recommend() actually called
    embedding_calls: int | None = None  # real embed() count for this request

    def to_log_dict(self) -> dict:
        return asdict(self)
