"""Union-of-three first-stage retrieval.

Runs BM25 keyword, bi-encoder semantic, and Arabic-skeleton term retrievers
in parallel, deduplicates by corpus index, and returns a list of Candidate
records. Each candidate carries the per-retriever raw score AND a [0,1]
min-max normalised score so the diagnostics in the UI / eval logs are
comparable across retrievers (the cross-encoder reranker, when wired in
Phase C, supersedes these as the final ordering signal).
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from . import semantic
from .data import Hadith, load

logger = logging.getLogger(__name__)


@dataclass
class Candidate:
    corpus_idx: int
    hadith: Hadith
    sources: set[str] = field(default_factory=set)
    bm25: float = 0.0
    semantic: float = 0.0
    term: float = 0.0
    bm25_norm: float = 0.0
    semantic_norm: float = 0.0
    term_norm: float = 0.0
    matched_words: set[str] = field(default_factory=set)


def _minmax(values: list[float]) -> list[float]:
    if not values:
        return values
    lo = min(values)
    hi = max(values)
    if hi - lo < 1e-12:
        return [1.0 if v > 0 else 0.0 for v in values]
    return [(v - lo) / (hi - lo) for v in values]


def retrieve_union(
    query: str,
    collection: str | None = None,
    k_per_retriever: int = 100,
) -> list[Candidate]:
    """Returns deduplicated union of (bm25 ∪ semantic ∪ term) top-K each.

    Order of the returned list is NOT a final ranking — it's stable but
    arbitrary (insertion order of the merge). The cross-encoder reranker
    is responsible for producing the user-facing order.
    """
    if not query.strip():
        return []

    library = load()
    corpus = library.bm25_corpus

    def _bm25():
        t0 = time.perf_counter()
        out = library.retrieve_keyword(query, collection=collection, limit=k_per_retriever)
        logger.debug("retrieve_union: bm25 %d hits in %.1f ms", len(out), (time.perf_counter() - t0) * 1000)
        return out

    def _sem():
        t0 = time.perf_counter()
        try:
            out = semantic.retrieve(query, collection=collection, limit=k_per_retriever)
        except FileNotFoundError:
            logger.warning("retrieve_union: semantic embeddings unavailable; skipping")
            out = []
        logger.debug("retrieve_union: semantic %d hits in %.1f ms", len(out), (time.perf_counter() - t0) * 1000)
        return out

    def _term():
        t0 = time.perf_counter()
        out, _word_freq = library.retrieve_term(query, collection=collection, limit=k_per_retriever)
        logger.debug("retrieve_union: term %d hits in %.1f ms", len(out), (time.perf_counter() - t0) * 1000)
        return out

    t_total = time.perf_counter()
    # max_workers=3 — one per retriever. The bi-encoder is the slow leg; BM25
    # and term are CPU-cheap. ThreadPoolExecutor is fine here: the bi-encoder
    # releases the GIL inside torch ops, and BM25 / term spend most time in
    # numpy / dict ops which also release.
    with ThreadPoolExecutor(max_workers=3) as pool:
        f_bm25 = pool.submit(_bm25)
        f_sem = pool.submit(_sem)
        f_term = pool.submit(_term)
        bm25_hits = f_bm25.result()
        sem_hits = f_sem.result()
        term_hits = f_term.result()

    bm25_norms = dict(zip(
        [idx for idx, _ in bm25_hits],
        _minmax([s for _, s in bm25_hits]),
    ))
    sem_norms = dict(zip(
        [idx for idx, _ in sem_hits],
        _minmax([s for _, s in sem_hits]),
    ))
    term_norms = dict(zip(
        [idx for idx, _, _ in term_hits],
        _minmax([s for _, s, _ in term_hits]),
    ))

    merged: dict[int, Candidate] = {}

    def _get(idx: int) -> Candidate:
        c = merged.get(idx)
        if c is None:
            c = Candidate(corpus_idx=idx, hadith=corpus[idx])
            merged[idx] = c
        return c

    for idx, score in bm25_hits:
        c = _get(idx)
        c.sources.add("bm25")
        c.bm25 = score
        c.bm25_norm = bm25_norms.get(idx, 0.0)
    for idx, score in sem_hits:
        c = _get(idx)
        c.sources.add("semantic")
        c.semantic = score
        c.semantic_norm = sem_norms.get(idx, 0.0)
    for idx, score, matched in term_hits:
        c = _get(idx)
        c.sources.add("term")
        c.term = score
        c.term_norm = term_norms.get(idx, 0.0)
        c.matched_words |= matched

    total_ms = (time.perf_counter() - t_total) * 1000.0
    logger.debug(
        "retrieve_union: %d unique candidates in %.1f ms (bm25=%d sem=%d term=%d)",
        len(merged), total_ms, len(bm25_hits), len(sem_hits), len(term_hits),
    )
    return list(merged.values())
