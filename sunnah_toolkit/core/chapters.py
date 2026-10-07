"""Chapter-title retrieval: match the query against bab titles, return members.

Hadith collections are organised by topic, and the compilers' own chapter
titles ("Supplication When Going To Sleep", "The Qunut During Witr") are the
best topical labels the corpus has. The v2 hadith vectors already embed the
title, but a hadith whose own text is short or oblique still ranks poorly.
Matching the title directly and then taking the whole chapter recovers those.

Artifacts, built offline by `scripts/build_chapter_embeddings.py` next to
the v2 hadith vectors (same model, so one query vector serves both):

    data/emb/<tag>/chapters_en.npy   float16 [C, dim]
    data/emb/<tag>/chapters_ar.npy   float16 [C, dim]
    data/emb/<tag>/chapters.json     chapter keys, in row order

Config:
    RETRIEVAL_CHAPTERS=1         enable the leg in retrieval.retrieve_union
    CHAPTERS_TOP=8               chapters taken per query
    CHAPTERS_MIN_SIM=0.55        title similarity floor
    CHAPTERS_MAX_MEMBERS=15      members kept per chapter (best by own similarity)
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections import defaultdict
from threading import Lock

import numpy as np

from . import semantic_v2
from .data import Hadith, load

logger = logging.getLogger(__name__)

# Titles that say nothing about the topic. Matching them would pull in
# arbitrary hadiths.
_GENERIC = re.compile(
    r"^(chapter|another (kind|version|chain|narration)|something else about that"
    r"|the same|section \d+)?[\s.:\-\d]*$",
    re.IGNORECASE,
)
_SECTION_SUFFIX = re.compile(r"\s*-\s*Section\s+\d+\s*$", re.IGNORECASE)

ChapterKey = tuple[str, int, str]  # (collection, chapter_id, english title)


def enabled() -> bool:
    return os.environ.get("RETRIEVAL_CHAPTERS", "").strip() in ("1", "true", "yes")


def clean_title(title: str) -> str:
    """Mishkat splits chapters into "... - Section 1/2/3"; the topic is the same."""
    return _SECTION_SUFFIX.sub("", title.strip())


def is_generic(title: str) -> bool:
    return not title.strip() or bool(_GENERIC.match(title.strip()))


def group_chapters(corpus: list[Hadith]) -> tuple[list[ChapterKey], list[list[int]], list[str]]:
    """Chapters with a topical title, their member corpus indices, and Arabic titles.

    Keyed on (collection, chapter_id, title) because chapter_id alone is
    truncated from a REAL babID in the dump and collides within a collection.
    Shared by the build script and the runtime so row order always matches.
    """
    members: dict[ChapterKey, list[int]] = defaultdict(list)
    arabic: dict[ChapterKey, str] = {}
    for i, h in enumerate(corpus):
        title = h.english_bab_name.strip()
        if is_generic(title):
            continue
        key = (h.collection, h.chapter_id if h.chapter_id is not None else -1, title)
        members[key].append(i)
        arabic.setdefault(key, h.arabic_bab_name.strip())
    keys = sorted(members)
    return keys, [members[k] for k in keys], [arabic[k] for k in keys]


class _Index:
    def __init__(self) -> None:
        self.tag: str | None = None
        self.keys: list[ChapterKey] = []
        self.members: list[list[int]] = []
        self.en: np.ndarray | None = None
        self.ar: np.ndarray | None = None
        self.collections: np.ndarray | None = None


_index = _Index()
_lock = Lock()


def _ensure_loaded() -> None:
    tag = semantic_v2.default_tag()
    if _index.en is not None and _index.tag == tag:
        return
    with _lock:
        if _index.en is not None and _index.tag == tag:
            return
        d = semantic_v2.artifact_dir(tag)
        meta_path = d / "chapters.json"
        if not meta_path.exists():
            raise FileNotFoundError(
                f"chapter vectors not built for tag {tag!r}. Run: "
                f"python -m scripts.build_chapter_embeddings"
            )
        stored = [tuple(k) for k in json.loads(meta_path.read_text())["keys"]]
        keys, members, _ = group_chapters(load().bm25_corpus)
        if stored != keys:
            raise RuntimeError(
                f"{meta_path} does not match the loaded corpus "
                f"({len(stored)} vs {len(keys)} chapters). Rebuild: "
                f"python -m scripts.build_chapter_embeddings"
            )
        en = np.load(d / "chapters_en.npy").astype(np.float32)
        ar_path = d / "chapters_ar.npy"
        ar = np.load(ar_path).astype(np.float32) if ar_path.exists() else None
        _index.tag = tag
        _index.keys = keys
        _index.members = members
        _index.en = en
        _index.ar = ar
        _index.collections = np.array([k[0] for k in keys])
        logger.info("chapters loaded: %d chapters, tag=%s", len(keys), tag)


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def retrieve(query: str, collection: str | None = None) -> list[tuple[int, float]]:
    """(corpus_idx, chapter similarity) for members of the best-matching chapters."""
    if not query.strip():
        return []
    _ensure_loaded()
    q = semantic_v2.encode_query(query)
    scores = _index.en @ q
    if _index.ar is not None:
        scores = np.maximum(scores, _index.ar @ q)
    if collection is not None:
        scores = np.where(_index.collections == collection, scores, -np.inf)

    top_n = _int_env("CHAPTERS_TOP", 8)
    min_sim = _float_env("CHAPTERS_MIN_SIM", 0.55)
    max_members = _int_env("CHAPTERS_MAX_MEMBERS", 15)

    k = min(top_n, scores.size)
    top = np.argpartition(-scores, k - 1)[:k]
    out: dict[int, float] = {}
    for c in sorted(top, key=lambda i: -scores[i]):
        sim = float(scores[c])
        if not np.isfinite(sim) or sim < min_sim:
            continue
        mem = _index.members[c]
        if len(mem) > max_members:
            own = semantic_v2.doc_scores(q, mem)
            mem = [mem[i] for i in np.argsort(-own)[:max_members]]
        for idx in mem:
            if sim > out.get(idx, -1.0):
                out[idx] = sim
    return sorted(out.items(), key=lambda p: p[1], reverse=True)


def info() -> dict:
    return {
        "enabled": enabled(),
        "loaded": _index.en is not None,
        "chapters": len(_index.keys),
    }
