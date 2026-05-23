"""Semantic search over hadith embeddings.

Loads pre-built embeddings from data/embeddings.npy on first call and keeps
them resident. Query workflow: embed the query with the same model, cosine
similarity (dot product since vectors are L2-normalized) against the whole
matrix, top-K results.
"""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock

import numpy as np

from .data import COLLECTION_TIER, Hadith, load

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
EMBEDDINGS_PATH = DATA_DIR / "embeddings.npy"
META_PATH = DATA_DIR / "embeddings_meta.json"


class _Engine:
    def __init__(self) -> None:
        self.model = None
        self.vectors: np.ndarray | None = None
        self.meta: dict | None = None
        self.content_mask: np.ndarray | None = None


_engine = _Engine()
_lock = Lock()


def _pick_device() -> str:
    import torch

    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def _ensure_loaded() -> None:
    if _engine.vectors is not None:
        return
    with _lock:
        if _engine.vectors is not None:
            return
        if not EMBEDDINGS_PATH.exists() or not META_PATH.exists():
            raise FileNotFoundError(
                "Embeddings not built. Run: python -m scripts.build_embeddings"
            )
        meta = json.loads(META_PATH.read_text())
        vectors = np.load(EMBEDDINGS_PATH)

        library = load()
        if vectors.shape[0] != len(library.bm25_corpus):
            raise RuntimeError(
                f"Embeddings shape {vectors.shape[0]} != corpus size {len(library.bm25_corpus)}. "
                "Rebuild: python -m scripts.build_embeddings"
            )

        from sentence_transformers import SentenceTransformer

        device = _pick_device()
        model = SentenceTransformer(meta["model_id"], device=device)

        content_mask = np.array(
            [bool((h.english_narrator + h.english_text).strip()) for h in library.bm25_corpus]
        )

        _engine.model = model
        _engine.vectors = vectors
        _engine.meta = meta
        _engine.content_mask = content_mask


def search(
    query: str,
    collection: str | None = None,
    limit: int = 10,
) -> list[tuple[Hadith, float]]:
    """Embed `query`, cosine-similarity rank against the corpus, return top-N."""
    if not query.strip():
        return []

    _ensure_loaded()
    assert _engine.model is not None
    assert _engine.vectors is not None

    library = load()
    corpus = library.bm25_corpus

    q = _engine.model.encode(
        [query],
        normalize_embeddings=True,
        convert_to_numpy=True,
    )[0].astype(np.float32)

    scores = _engine.vectors @ q
    scores = np.where(_engine.content_mask, scores, -np.inf)

    if collection is not None:
        mask = np.array([h.collection == collection for h in corpus])
        scores = np.where(mask, scores, -np.inf)

    # Enlarge the candidate pool so the tier reorder below has room to
    # surface a high-tier hit that ranked, say, 50th on raw cosine.
    pool = min(max(limit * 20, 200), scores.size)
    top_idx = np.argpartition(-scores, range(pool))[:pool]
    top_idx = top_idx[np.argsort(-scores[top_idx])]

    candidates = [
        (corpus[int(i)], float(scores[int(i)]))
        for i in top_idx
        if scores[int(i)] > -np.inf
    ]
    candidates.sort(key=lambda pair: (
        COLLECTION_TIER[pair[0].collection],
        pair[0].grade_tier,
        -pair[1],
    ))
    return candidates[:limit]
