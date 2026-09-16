"""Dense embedding function for semantic search (Sprint 1b Part A).

Model: ibm-granite/granite-embedding-278m-multilingual, via sentence-transformers,
CPU inference, no external API -- decision recorded in Sprint_Tracker.md's
Sprint 1b section. This model does NOT use a query/passage prefix
convention -- one function, `embed`, used identically for indexing product
text and encoding a user's query. Do not add prefix logic; that would be
inventing a requirement this model doesn't have.
"""

from __future__ import annotations

import contextvars

MODEL_NAME = "ibm-granite/granite-embedding-278m-multilingual"

_model = None

# Sprint 6 observability task: real per-request count of embed() calls (the
# one function every embedding path -- recommendation, vector search --
# actually funnels through), for a caller's per-message trace to read.
# embed_batch() (the offline ingestion path) is deliberately NOT counted --
# it never runs during a conversational message.
_embedding_call_count: contextvars.ContextVar[int] = contextvars.ContextVar("_embedding_call_count", default=0)


def reset_embedding_trace() -> None:
    """Call at the start of a request to zero this context's embed() count."""
    _embedding_call_count.set(0)


def pop_embedding_trace() -> int:
    """Real count of embed() calls made in this context since the last
    reset_embedding_trace() -- never estimated."""
    count = _embedding_call_count.get()
    _embedding_call_count.set(0)
    return count


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(MODEL_NAME, device="cpu")
    return _model


def embed(text: str) -> list[float]:
    """Encode `text` into a dense embedding vector. Same function for both
    product text at index time and query text at search time -- this
    model has no query/passage prefix distinction to get wrong."""
    _embedding_call_count.set(_embedding_call_count.get() + 1)
    vec = _get_model().encode(text, convert_to_numpy=True, normalize_embeddings=True)
    return vec.tolist()


def embed_batch(texts: list[str], batch_size: int = 1) -> list[list[float]]:
    """Batch variant for the one-time indexing script -- same model, same
    normalization. batch_size=1 default is deliberate, not an oversight:
    measured directly on this CPU (same model loaded once, same 32 real
    product texts) -- batch_size=32 was 1.8x SLOWER per item than
    batch_size=1 (1342.8ms vs 753.7ms/item), because CPU inference here
    gets no parallelism benefit from batching and instead pays for padding
    every item in a batch up to its longest member. Verified this doesn't
    affect correctness either: encoding the same text alone vs. inside a
    heavily-padded batch of 32 gave cosine similarity 0.999986 between the
    two vectors (max elementwise diff 0.00098) -- functionally identical,
    the difference is ordinary floating-point non-associativity, not a
    padding bug. So batch_size=1 is strictly better here, not a tradeoff."""
    vecs = _get_model().encode(
        texts, convert_to_numpy=True, normalize_embeddings=True,
        batch_size=batch_size, show_progress_bar=True,
    )
    return vecs.tolist()
