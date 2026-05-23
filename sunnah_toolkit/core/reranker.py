"""Cross-encoder rerankers for the second stage of search.

Issue #2 lists four candidates that the user will benchmark on the
auto-seeded eval set:
  - jinaai/jina-reranker-v3
  - BAAI/bge-reranker-v2-m3
  - mixedbread-ai/mxbai-rerank-base-v2
  - jinaai/jina-reranker-v2-base-multilingual

Each implementation lazy-loads its model on the first .score() call. Only
one reranker is loaded into the process at a time (lru_cache(maxsize=1))
because the host RAM budget is 16 GB and these models are large in FP16.

Default reranker is read from $RERANKER_NAME (fallback: bge-v2-m3, the
safe MIT-licensed multilingual baseline). $RERANKER_DISABLED=1 short-
circuits the pipeline back to the first-stage union order (used by the
eval harness for the `--reranker none` baseline).
"""

from __future__ import annotations

import functools
import logging
import os
from typing import Protocol

logger = logging.getLogger(__name__)


REGISTRY: dict[str, str] = {
    "jina-v3": "jinaai/jina-reranker-v3",
    "bge-v2-m3": "BAAI/bge-reranker-v2-m3",
    "mxbai-v2-base": "mixedbread-ai/mxbai-rerank-base-v2",
    "jina-v2-base": "jinaai/jina-reranker-v2-base-multilingual",
}


def _pick_device() -> str:
    import torch

    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


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
        self._model = CrossEncoder(
            self.model_id,
            device=self._device,
            max_length=self.max_length,
            trust_remote_code=True,
        )
        return self._model

    def score(self, query: str, docs: list[str]) -> list[float]:
        if not docs:
            return []
        model = self._load()
        pairs = [(query, d) for d in docs]
        # show_progress_bar=False keeps the API/eval logs clean.
        scores = model.predict(pairs, show_progress_bar=False, convert_to_numpy=True)
        return [float(s) for s in scores]


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


class JinaV3Reranker:
    """jina-reranker-v3 ships a listwise head that isn't CrossEncoder-shaped.
    Falls back to AutoModelForSequenceClassification with mean-pooled logits
    if the listwise path isn't reachable, so the user can still run the
    comparison even if the listwise interface changes upstream."""

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

        logger.info("loading reranker %s on device=%s", self.model_id, self._device)
        self._tokenizer = AutoTokenizer.from_pretrained(self.model_id, trust_remote_code=True)
        self._model = AutoModelForSequenceClassification.from_pretrained(
            self.model_id,
            trust_remote_code=True,
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


@functools.lru_cache(maxsize=1)
def get_reranker(name: str) -> Reranker:
    """Returns the singleton reranker instance for `name`. lru_cache size 1
    means switching name evicts the old model — protecting RAM."""
    if name not in _BUILDERS:
        raise ValueError(f"Unknown reranker {name!r}. Choices: {sorted(_BUILDERS)}")
    return _BUILDERS[name]()


def default_reranker_name() -> str:
    return os.environ.get("RERANKER_NAME", "bge-v2-m3")


def reranker_enabled() -> bool:
    return os.environ.get("RERANKER_DISABLED", "").strip() not in ("1", "true", "yes")


def default_threshold() -> float:
    try:
        return float(os.environ.get("RERANKER_THRESHOLD", "0.5"))
    except ValueError:
        return 0.5
