"""v2 semantic retrieval — dual-language, chapter-aware bi-encoder.

Loads the artifacts built by `scripts/build_embeddings_v2.py`:

    data/emb/<tag>/en.npy   float16 [N, dim]
    data/emb/<tag>/ar.npy   float16 [N, dim]
    data/emb/<tag>/meta.json

Every hadith carries two vectors — one over `chapter_title + english_text`,
one over `chapter_title + arabic_matn`. A query is encoded once and scored
against both, combined per `$SEMANTIC_V2_COMBINE` (default `max`). That means
an Arabic query matches Arabic text directly instead of being forced through
the transliteration-skeleton path, and an English query still matches the
English side, with no language detection anywhere.

This module is **not wired into the default search path**. `core/semantic.py`
(v1 MiniLM) remains what `retrieval.retrieve_union` calls. v2 exists so the
eval harness can measure the two head-to-head once expert labels land; the
switch happens on evidence, not vibes.

Config:
    SEMANTIC_V2_TAG       artifact dir under data/emb  (default: bge-m3)
    SEMANTIC_V2_COMBINE   max | mean | en | ar         (default: max)
"""

from __future__ import annotations

import json
import logging
import os
from collections import OrderedDict
from pathlib import Path
from threading import Lock

import numpy as np

from ._device import pick_device as _pick_device
from .data import Hadith, load

logger = logging.getLogger(__name__)

EMB_ROOT = Path(__file__).resolve().parent.parent.parent / "data" / "emb"


def default_tag() -> str:
    return os.environ.get("SEMANTIC_V2_TAG", "bge-m3")


def default_combine() -> str:
    return os.environ.get("SEMANTIC_V2_COMBINE", "max").lower()


class _Engine:
    def __init__(self) -> None:
        self.tag: str | None = None
        self.model = None
        self.en: np.ndarray | None = None
        self.ar: np.ndarray | None = None
        self.meta: dict | None = None
        self.content_mask: np.ndarray | None = None
        self.collection_ids: np.ndarray | None = None
        self.collection_index: dict[str, int] = {}


_engine = _Engine()
_lock = Lock()
# Mirrors core/semantic.py: SentenceTransformer.encode mutates shared module
# state, and retrieve_union calls us from a worker thread.
_encode_lock = Lock()


def artifact_dir(tag: str | None = None) -> Path:
    return EMB_ROOT / (tag or default_tag())


def available(tag: str | None = None) -> bool:
    d = artifact_dir(tag)
    return (d / "meta.json").exists() and (d / "en.npy").exists()


def _ensure_loaded(tag: str | None = None) -> None:
    tag = tag or default_tag()
    if _engine.en is not None and _engine.tag == tag:
        return
    with _lock:
        if _engine.en is not None and _engine.tag == tag:
            return

        d = artifact_dir(tag)
        meta_path = d / "meta.json"
        if not meta_path.exists():
            raise FileNotFoundError(
                f"v2 embeddings not built for tag {tag!r}. Run: "
                f"python -m scripts.build_embeddings_v2 --model {tag}"
            )
        meta = json.loads(meta_path.read_text())
        if meta.get("partial"):
            raise RuntimeError(
                f"{d} was built with --limit (partial={meta['vector_count']} "
                f"vectors) and is not usable for retrieval. Rebuild without --limit."
            )

        library = load()
        corpus = library.bm25_corpus
        n = len(corpus)

        # Stored fp16 to halve disk; cast to fp32 once here because numpy has
        # no fp16 BLAS path -- a fp16 matmul would silently upcast the whole
        # matrix on every single query. ~184 MB per language resident.
        def _load(name: str) -> np.ndarray | None:
            p = d / f"{name}.npy"
            if not p.exists():
                return None
            arr = np.load(p).astype(np.float32)
            if arr.shape[0] != n:
                raise RuntimeError(
                    f"{p} has {arr.shape[0]} vectors but the corpus has {n}. "
                    f"Rebuild: python -m scripts.build_embeddings_v2 --model {tag}"
                )
            return arr

        en = _load("en")
        ar = _load("ar")
        if en is None and ar is None:
            raise FileNotFoundError(f"No en.npy or ar.npy under {d}")

        from sentence_transformers import SentenceTransformer

        device = _pick_device()
        model = SentenceTransformer(meta["model_id"], device=device)
        model.max_seq_length = meta.get("max_seq", 512)

        content_mask = np.array(
            [bool((h.english_narrator + h.english_text).strip()) or bool(h.arabic.strip())
             for h in corpus]
        )
        col_index: dict[str, int] = {}
        col_ids = np.empty(n, dtype=np.int32)
        for i, h in enumerate(corpus):
            cid = col_index.setdefault(h.collection, len(col_index))
            col_ids[i] = cid

        _engine.tag = tag
        _engine.model = model
        _engine.en = en
        _engine.ar = ar
        _engine.meta = meta
        _engine.content_mask = content_mask
        _engine.collection_ids = col_ids
        _engine.collection_index = col_index
        logger.info(
            "semantic_v2 loaded tag=%s model=%s dim=%s en=%s ar=%s",
            tag, meta["model_id"], meta.get("dim"),
            en is not None, ar is not None,
        )


# One bge-m3 forward pass is ~0.3-0.5 s on the 2015 MBP, and a single
# search encodes the same query for both the hadith leg and the chapter leg.
_QUERY_CACHE: OrderedDict[str, np.ndarray] = OrderedDict()
_QUERY_CACHE_MAX = 256


def encode_query(query: str) -> np.ndarray:
    _ensure_loaded()
    assert _engine.model is not None and _engine.meta is not None
    with _encode_lock:
        cached = _QUERY_CACHE.get(query)
        if cached is not None:
            _QUERY_CACHE.move_to_end(query)
            return cached.copy()
        prefix = _engine.meta.get("query_prefix", "")
        v = _engine.model.encode(
            [prefix + query],
            normalize_embeddings=True,
            convert_to_numpy=True,
        )[0].astype(np.float32)
        _QUERY_CACHE[query] = v
        if len(_QUERY_CACHE) > _QUERY_CACHE_MAX:
            _QUERY_CACHE.popitem(last=False)
    return v.copy()


def doc_scores(q: np.ndarray, indices: list[int]) -> np.ndarray:
    """Similarity of query vector `q` to specific hadiths, combined like `retrieve`."""
    _ensure_loaded()
    idx = np.asarray(indices, dtype=np.int64)
    en, ar = _engine.en, _engine.ar
    if en is None:
        return ar[idx] @ q
    if ar is None:
        return en[idx] @ q
    return np.maximum(en[idx] @ q, ar[idx] @ q)


def neighbors(
    seeds: list[int],
    k: int = 5,
    min_sim: float = 0.85,
    collection: str | None = None,
) -> list[tuple[int, float]]:
    """Hadiths whose vectors sit closest to any seed hadith.

    The same report often appears in several collections with different
    wording (Bukhari, Muslim, Riyad as-Salihin, Hisn al-Muslim); finding one
    should pull in the others. English vectors only: the Arabic side of two
    narrations of one hadith is near-identical anyway, and one matmul per
    seed keeps this to tens of milliseconds.
    """
    _ensure_loaded()
    mat = _engine.en if _engine.en is not None else _engine.ar
    best: dict[int, float] = {}
    seed_set = set(seeds)
    for s_idx in seeds:
        sims = mat @ mat[s_idx]
        sims = np.where(_engine.content_mask, sims, -np.inf)
        if collection is not None:
            cid = _engine.collection_index.get(collection)
            if cid is None:
                return []
            sims = np.where(_engine.collection_ids == cid, sims, -np.inf)
        top = np.argpartition(-sims, k + 1)[: k + 1]
        for i in top:
            i = int(i)
            sim = float(sims[i])
            if i in seed_set or not np.isfinite(sim) or sim < min_sim:
                continue
            if sim > best.get(i, -1.0):
                best[i] = sim
    return sorted(best.items(), key=lambda p: p[1], reverse=True)


def retrieve(
    query: str,
    collection: str | None = None,
    limit: int = 100,
    combine: str | None = None,
) -> list[tuple[int, float]]:
    """Return (corpus_idx, score) top-N. Interface-compatible with semantic.retrieve."""
    if not query.strip():
        return []

    _ensure_loaded()
    combine = (combine or default_combine()).lower()
    q = encode_query(query)

    en, ar = _engine.en, _engine.ar
    if combine == "en" or ar is None:
        scores = en @ q
    elif combine == "ar" or en is None:
        scores = ar @ q
    elif combine == "mean":
        scores = (en @ q + ar @ q) * 0.5
    else:  # "max" -- best-matching language wins, no language detection needed
        scores = np.maximum(en @ q, ar @ q)

    scores = np.where(_engine.content_mask, scores, -np.inf)

    if collection is not None:
        cid = _engine.collection_index.get(collection)
        if cid is None:
            return []
        scores = np.where(_engine.collection_ids == cid, scores, -np.inf)

    k = min(limit, scores.size)
    top_idx = np.argpartition(-scores, range(k))[:k]
    top_idx = top_idx[np.argsort(-scores[top_idx])]
    return [
        (int(i), float(scores[int(i)]))
        for i in top_idx
        if np.isfinite(scores[int(i)])
    ]


def search(
    query: str, collection: str | None = None, limit: int = 10
) -> list[tuple[Hadith, float]]:
    """Resolve `retrieve` indices to Hadith records. No tier sort applied —
    ordering policy (Sahihayn banding) belongs to the presentation layer."""
    corpus = load().bm25_corpus
    return [(corpus[i], s) for i, s in retrieve(query, collection, limit)]


def info() -> dict:
    """Artifact metadata for /healthz and the eval harness."""
    tag = default_tag()
    if not available(tag):
        return {"available": False, "tag": tag}
    meta = json.loads((artifact_dir(tag) / "meta.json").read_text())
    return {
        "available": True,
        "tag": tag,
        "combine": default_combine(),
        "loaded": _engine.en is not None,
        **{k: meta.get(k) for k in
           ("model_id", "dim", "vector_count", "languages", "built", "partial")},
    }
