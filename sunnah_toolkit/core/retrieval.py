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


def retrieve_union_multi(
    variants: list[str],
    collection: str | None = None,
    k_per_retriever: int = 100,
    rrf_k: int = 60,
) -> list[Candidate]:
    """Run `retrieve_union` per variant and merge with Reciprocal Rank Fusion.

    For each variant's candidate list (already an unranked union of three
    retrievers), we assign a rank starting at 1 in the order returned. The
    RRF score per (variant, corpus_idx) is `1 / (rrf_k + rank)`. Scores are
    summed across variants and the final list is sorted descending.

    The returned `Candidate` for each corpus_idx carries the union of the
    per-variant `sources` and `matched_words`, plus the maximum per-signal
    score and normalised score observed across variants. The downstream
    cross-encoder is the source of the final ordering signal — RRF here
    just builds the candidate pool for the reranker.

    `rrf_k=60` is the canonical TREC default; small enough that high-ranked
    items dominate, large enough that mid-ranked items still contribute.
    """
    if not variants:
        return []

    per_variant_lists: list[list[Candidate]] = []
    for v in variants:
        per_variant_lists.append(
            retrieve_union(v, collection=collection, k_per_retriever=k_per_retriever)
        )

    rrf_scores: dict[int, float] = {}
    merged: dict[int, Candidate] = {}

    for cands in per_variant_lists:
        for rank, cand in enumerate(cands, start=1):
            idx = cand.corpus_idx
            rrf_scores[idx] = rrf_scores.get(idx, 0.0) + 1.0 / (rrf_k + rank)
            existing = merged.get(idx)
            if existing is None:
                merged[idx] = Candidate(
                    corpus_idx=idx,
                    hadith=cand.hadith,
                    sources=set(cand.sources),
                    bm25=cand.bm25,
                    semantic=cand.semantic,
                    term=cand.term,
                    bm25_norm=cand.bm25_norm,
                    semantic_norm=cand.semantic_norm,
                    term_norm=cand.term_norm,
                    matched_words=set(cand.matched_words),
                )
            else:
                existing.sources |= cand.sources
                existing.matched_words |= cand.matched_words
                # Per-variant retrieve_union already min-max-normalises within
                # that variant's hit list, so taking the max across variants
                # is the best per-signal aggregate available without re-running
                # the normaliser over the merged universe.
                existing.bm25 = max(existing.bm25, cand.bm25)
                existing.semantic = max(existing.semantic, cand.semantic)
                existing.term = max(existing.term, cand.term)
                existing.bm25_norm = max(existing.bm25_norm, cand.bm25_norm)
                existing.semantic_norm = max(existing.semantic_norm, cand.semantic_norm)
                existing.term_norm = max(existing.term_norm, cand.term_norm)

    ordered = sorted(
        merged.values(),
        key=lambda c: rrf_scores.get(c.corpus_idx, 0.0),
        reverse=True,
    )
    logger.debug(
        "retrieve_union_multi: %d variants -> %d unique candidates",
        len(variants), len(ordered),
    )
    return ordered
