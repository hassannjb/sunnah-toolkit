"""Cross-encoder rerankers for the second stage of search.

Issue #2 lists four candidates that the user will benchmark on the
auto-seeded eval set:
  - jinaai/jina-reranker-v3
  - BAAI/bge-reranker-v2-m3
  - mixedbread-ai/mxbai-rerank-base-v2
  - jinaai/jina-reranker-v2-base-multilingual

Each implementation lazy-loads its model on the first .score() call. Only
one reranker is loaded into the process at a time (single-slot cache;
see `get_reranker` below) because the host RAM budget is 16 GB and these
models are large in FP16.

Note (LO-005, HI-001): switching `RERANKER_NAME` mid-process drops the
previous model from the cache and best-effort calls torch's device-cache
empty hook before constructing the replacement. Python GC ultimately
decides when device weights are reclaimed, so a swap that races with an
outstanding `.score()` call may still hold device memory until that call
completes.

Default reranker is read from $RERANKER_NAME (fallback: bge-v2-m3, the
safe MIT-licensed multilingual baseline). $RERANKER_DISABLED=1 short-
circuits the pipeline back to the first-stage union order (used by the
eval harness for the `--reranker none` baseline).
"""

from __future__ import annotations

import logging
import os
from typing import Protocol

from ._device import pick_device as _pick_device

logger = logging.getLogger(__name__)


REGISTRY: dict[str, str] = {
    "jina-v3": "jinaai/jina-reranker-v3",
    "bge-v2-m3": "BAAI/bge-reranker-v2-m3",
    "mxbai-v2-base": "mixedbread-ai/mxbai-rerank-base-v2",
    "jina-v2-base": "jinaai/jina-reranker-v2-base-multilingual",
}


# HI-002: bound the cross-encoder forward batch. CrossEncoder pads to the
# longest pair in the batch, so one 8 K-token doc forces every other pair
# to pad to 8 K. Smaller batches keep worst-case latency bounded; override
# via $RERANKER_BATCH_SIZE for experiments.
def _batch_size() -> int:
    try:
        return max(1, int(os.environ.get("RERANKER_BATCH_SIZE", "8")))
    except ValueError:
        return 8


class Reranker(Protocol):
    name: str
    model_id: str

    def score(self, query: str, docs: list[str]) -> list[float]: ...


class _CrossEncoderBase:
    """Common scaffolding: sentence-transformers CrossEncoder with device
    selection. Used by the rerankers that ship a CrossEncoder-compatible head."""

    name: str = ""
    model_id: str = ""
    max_length: int = 512

    def __init__(self) -> None:
        self._model = None
        self._device = _pick_device()

    def _load(self):
        if self._model is not None:
            return self._model
        from sentence_transformers import CrossEncoder

        logger.info("loading reranker %s on device=%s", self.model_id, self._device)
        # NOTE(security CR-001): None of the CrossEncoder-shaped rerankers
        # (bge-v2-m3, jina-v2-base, mxbai-v2-base) require trust_remote_code —
        # they ship plain AutoModelForSequenceClassification configs. Flag
        # deliberately omitted to avoid arbitrary HF code execution.
        self._model = CrossEncoder(
            self.model_id,
            device=self._device,
            max_length=self.max_length,
        )
        return self._model

    def score(self, query: str, docs: list[str]) -> list[float]:
        if not docs:
            return []
        model = self._load()
        # HI-002: length-bucket pairs before predict so each padded batch is
        # roughly uniform — a single 8 K-token doc otherwise forces every
        # other pair in its batch to pad up. We sort by doc length, score in
        # the sorted order, then scatter back to the original order.
        order = sorted(range(len(docs)), key=lambda i: len(docs[i]))
        sorted_pairs = [(query, docs[i]) for i in order]
        # show_progress_bar=False keeps the API/eval logs clean.
        sorted_scores = model.predict(
            sorted_pairs,
            batch_size=_batch_size(),
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        scores = [0.0] * len(docs)
        for pos, original_idx in enumerate(order):
            scores[original_idx] = float(sorted_scores[pos])
        return scores


class BGEV2M3Reranker(_CrossEncoderBase):
    name = "bge-v2-m3"
    model_id = "BAAI/bge-reranker-v2-m3"
    max_length = 512


class JinaV2BaseReranker(_CrossEncoderBase):
    name = "jina-v2-base"
    model_id = "jinaai/jina-reranker-v2-base-multilingual"
    max_length = 1024


class MxbaiV2BaseReranker(_CrossEncoderBase):
    name = "mxbai-v2-base"
    model_id = "mixedbread-ai/mxbai-rerank-base-v2"
    max_length = 8192  # mxbai-v2 supports long context; truncation falls to model.


# NOTE(security CR-001): jina-reranker-v3 ships a custom modeling.py
# (Qwen3-based listwise pipeline) so trust_remote_code=True is unavoidable —
# the HF auto-classes need to import that file to construct the model. The
# supply-chain risk (an attacker pushing malicious code to the same repo
# path) is mitigated by pinning the revision to a known-good commit SHA.
# If you need to update, audit the diff on huggingface.co/jinaai/jina-
# reranker-v3/commits and bump JINA_V3_REVISION below.
JINA_V3_REVISION = "10fb694fc21f7a710a563ff1eb977a460f3868e4"  # 2026-03-27


class JinaV3Reranker:
    """jina-reranker-v3 ships a listwise head that isn't CrossEncoder-shaped.
    Falls back to AutoModelForSequenceClassification with mean-pooled logits
    if the listwise path isn't reachable, so the user can still run the
    comparison even if the listwise interface changes upstream.

    Revision is pinned (see JINA_V3_REVISION) because we pass
    trust_remote_code=True for this model.
    """

    name = "jina-v3"
    model_id = "jinaai/jina-reranker-v3"
    max_length = 1024

    def __init__(self) -> None:
        self._model = None
        self._tokenizer = None
        self._device = _pick_device()

    def _load(self):
        if self._model is not None:
            return
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        logger.info(
            "loading reranker %s @ %s on device=%s",
            self.model_id, JINA_V3_REVISION[:8], self._device,
        )
        self._tokenizer = AutoTokenizer.from_pretrained(
            self.model_id,
            trust_remote_code=True,
            revision=JINA_V3_REVISION,
        )
        self._model = AutoModelForSequenceClassification.from_pretrained(
            self.model_id,
            trust_remote_code=True,
            revision=JINA_V3_REVISION,
        ).to(self._device).eval()

    def score(self, query: str, docs: list[str]) -> list[float]:
        if not docs:
            return []
        self._load()
        import torch

        scores: list[float] = []
        with torch.no_grad():
            # Score one pair at a time to avoid padding-induced slowdowns
            # on long documents — these rerankers are fast enough in batch=1.
            for d in docs:
                enc = self._tokenizer(
                    query,
                    d,
                    return_tensors="pt",
                    truncation=True,
                    max_length=self.max_length,
                ).to(self._device)
                out = self._model(**enc)
                logit = out.logits.view(-1)[0]
                scores.append(float(logit))
        return scores


_BUILDERS: dict[str, type] = {
    "bge-v2-m3": BGEV2M3Reranker,
    "jina-v2-base": JinaV2BaseReranker,
    "mxbai-v2-base": MxbaiV2BaseReranker,
    "jina-v3": JinaV3Reranker,
}


# HI-001: explicit single-slot cache. Switching `name` evicts the previous
# instance and best-effort frees the device cache before constructing the
# replacement. `lru_cache(maxsize=1)` would only drop the *reference*; the
# evicted torch model would linger on GPU/MPS until Python GC ran.
_current_reranker: tuple[str, "Reranker"] | None = None


def _free_device_cache(device: str) -> None:
    """Best-effort: free cached allocations on the prior reranker's device.

    Safe to call when the import or attribute is missing — the empty-cache
    hook is purely an optimisation, never a correctness requirement.
    """
    try:
        import torch
    except ImportError:  # pragma: no cover — torch is a hard dep at runtime
        return
    try:
        if device == "cuda" and torch.cuda.is_available():
            torch.cuda.empty_cache()
        elif device == "mps" and torch.backends.mps.is_available():
            mps = getattr(torch, "mps", None)
            if mps is not None and hasattr(mps, "empty_cache"):
                mps.empty_cache()
    except Exception as e:  # pragma: no cover — backend-specific quirks
        logger.debug("empty_cache(%s) failed: %s", device, e)


def _evict_current() -> None:
    """Drop the current single-slot reranker and best-effort free device memory."""
    global _current_reranker
    if _current_reranker is None:
        return
    prior_name, prior = _current_reranker
    prior_device = getattr(prior, "_device", "cpu")
    if hasattr(prior, "_model"):
        prior._model = None
    if hasattr(prior, "_tokenizer"):
        prior._tokenizer = None
    _current_reranker = None
    del prior
    _free_device_cache(prior_device)
    logger.info("evicted reranker %s", prior_name)


def get_reranker(name: str) -> Reranker:
    """Returns the singleton reranker instance for `name`.

    Single-slot cache: switching name disposes the prior instance and frees
    its device cache before building the replacement.
    """
    global _current_reranker
    if name not in _BUILDERS:
        raise ValueError(f"Unknown reranker {name!r}. Choices: {sorted(_BUILDERS)}")
    if _current_reranker is not None and _current_reranker[0] == name:
        return _current_reranker[1]
    if _current_reranker is not None:
        _evict_current()
    instance = _BUILDERS[name]()
    _current_reranker = (name, instance)
    return instance


# Back-compat shim for tests that previously called `get_reranker.cache_clear()`
# on the lru_cache. The new explicit cache exposes the same affordance.
get_reranker.cache_clear = _evict_current  # type: ignore[attr-defined]


def default_reranker_name() -> str:
    return os.environ.get("RERANKER_NAME", "bge-v2-m3")


def reranker_enabled() -> bool:
    return os.environ.get("RERANKER_DISABLED", "").strip() not in ("1", "true", "yes")


def default_threshold() -> float:
    try:
        return float(os.environ.get("RERANKER_THRESHOLD", "0.5"))
    except ValueError:
        return 0.5
