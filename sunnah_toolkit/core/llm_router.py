"""LLM-backed query router/rewriter for the Natural-language search mode.

Issue #4: turns a free-form query like "what did the Prophet say about anger?"
into a small set of focused retrieval variants (phrases / keywords, NOT
questions) plus a coarse mode hint. The variants are fed into the existing
union retriever (BM25 ∪ bi-encoder ∪ Arabic-term) per-variant and merged via
Reciprocal Rank Fusion in `retrieval.retrieve_union_multi`.

Provider selection is via $LLM_PROVIDER: `anthropic` (Claude Haiku) or
`llamacpp` (a self-hosted llama-server, for hosts without an API key);
`openai` and `ollama` stubs are present so the Protocol is honoured and
future expansion is straightforward — each stub raises NotImplementedError
from __init__ with a hint to set LLM_PROVIDER=anthropic.

The router is fail-soft by design: any exception in `.route()` returns None
and the caller falls through to plain Concept-mode semantic search with a
`fallback` field surfaced in the response.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


_ANTHROPIC_MODEL = "claude-haiku-4-5"
_TIMEOUT_SECONDS = 5.0
_MAX_VARIANTS = 3

_SYSTEM_PROMPT = (
    "You receive a search query about Islamic hadith (sayings and actions of "
    "the Prophet Muhammad). Identify the user's likely intent and produce 1-3 "
    "focused search variants that a retrieval system can use. Each variant "
    "MUST be a noun phrase or a short set of keywords — never a question. "
    "Also indicate which search mode would help most:\n"
    "  - \"concept\" for meaning-based questions (e.g. \"kindness to neighbours\")\n"
    "  - \"keyword\" for an exact English term (e.g. \"intention\")\n"
    "  - \"term\" for an Arabic word the user is asking about (e.g. \"qunut\")\n"
    "  - \"reference\" for an exact citation lookup (e.g. \"Bukhari 1\")\n"
    "Variants should diversify the angle of attack: a literal phrase, a "
    "synonym, and an underlying concept work well together."
)

_TOOL_SCHEMA = {
    "name": "emit_search_variants",
    "description": (
        "Emit the inferred mode hint and 1-3 focused search variants for the "
        "hadith retrieval pipeline."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "mode_hint": {
                "type": "string",
                "enum": ["concept", "keyword", "term", "reference"],
                "description": "Best-fit search mode for this query.",
            },
            "variants": {
                "type": "array",
                "minItems": 1,
                "maxItems": 3,
                "items": {"type": "string"},
                "description": (
                    "1-3 focused search strings (phrases or keywords, NOT "
                    "questions). Diversify across literal/synonym/concept."
                ),
            },
        },
        "required": ["mode_hint", "variants"],
    },
}


# Small local models (1.5B) need more steering than Haiku. Benchmarked on the
# 2015 MBP: with no examples, Qwen2.5-1.5B invented surah names and turned
# "dua when it rains" into "two rak'ahs". Examples are deliberately on topics
# outside the eval set. "reference" is dropped from the enum because the
# rerank pipeline has no weights for it.
_LOCAL_SYSTEM_PROMPT = _SYSTEM_PROMPT + (
    "\nRules: in at least one variant, translate Islamic terms into plain English "
    "(dua = supplication, salah = prayer, sawm = fasting, wudu = ablution). "
    "Never include collection names (Bukhari, Muslim) or book titles. "
    "Do not invent names of surahs, people or places."
)
_LOCAL_FEW_SHOT: list[tuple[str, dict]] = [
    ("what should I recite after the adhan?",
     {"mode_hint": "concept", "variants": [
         "supplication after the call to prayer",
         "what to say after hearing the adhan",
         "dua after the muadhin"]}),
    ("is it allowed to drink while standing",
     {"mode_hint": "concept", "variants": [
         "drinking while standing",
         "etiquette of eating and drinking",
         "prohibition of drinking standing up"]}),
    ("salat al istikhara",
     {"mode_hint": "term", "variants": [
         "istikhara", "prayer for seeking guidance", "supplication of istikhara"]}),
    ("what did the Prophet say about lying",
     {"mode_hint": "concept", "variants": [
         "prohibition of lying",
         "truthfulness leads to righteousness",
         "signs of the hypocrite"]}),
]
_LOCAL_SCHEMA = {
    **_TOOL_SCHEMA["input_schema"],
    "properties": {
        **_TOOL_SCHEMA["input_schema"]["properties"],
        "mode_hint": {"type": "string", "enum": ["concept", "keyword", "term"]},
    },
}


@dataclass
class RouterOutput:
    mode_hint: str
    variants: list[str]


def _parse_payload(payload: object, who: str) -> RouterOutput | None:
    """Validate a `{mode_hint, variants}` payload from any provider."""
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        logger.warning("%s: payload is %s, not an object", who, type(payload).__name__)
        return None
    mode_hint = str(payload.get("mode_hint", "concept"))
    raw_variants = payload.get("variants") or []
    variants = [
        v.strip()
        for v in raw_variants
        if isinstance(v, str) and v.strip()
    ][:_MAX_VARIANTS]
    if not variants:
        logger.warning("%s: empty variants list", who)
        return None
    return RouterOutput(mode_hint=mode_hint, variants=variants)


@runtime_checkable
class Router(Protocol):
    def route(self, query: str) -> RouterOutput | None:
        """Return a RouterOutput, or None if the LLM call failed.

        Callers MUST treat None as "fall back to plain concept search" — the
        router never raises.
        """
        ...


class AnthropicRouter:
    def __init__(self) -> None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set; cannot construct AnthropicRouter"
            )
        # Imported lazily so the package can still be imported in environments
        # without `anthropic` installed (factory swallows the ImportError).
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key, timeout=_TIMEOUT_SECONDS)
        self._model = _ANTHROPIC_MODEL

    def route(self, query: str) -> RouterOutput | None:
        try:
            resp = self._client.messages.create(
                model=self._model,
                max_tokens=512,
                system=_SYSTEM_PROMPT,
                tools=[_TOOL_SCHEMA],
                tool_choice={"type": "tool", "name": _TOOL_SCHEMA["name"]},
                messages=[{"role": "user", "content": query}],
            )
        except Exception as e:
            logger.warning(
                "AnthropicRouter.route failed: %s (%s)", type(e).__name__, e
            )
            return None

        try:
            for block in resp.content:
                if getattr(block, "type", None) == "tool_use":
                    return _parse_payload(block.input, "AnthropicRouter")
            logger.warning("AnthropicRouter: no tool_use block in response")
            return None
        except Exception as e:
            logger.warning(
                "AnthropicRouter response parse failed: %s (%s)",
                type(e).__name__,
                e,
            )
            return None


class LlamaCppRouter:
    """Self-hosted router: a local llama.cpp `llama-server` (OpenAI-compatible).

    The Anthropic prompt plus rules and few-shot examples (see
    _LOCAL_SYSTEM_PROMPT). The schema is enforced by llama.cpp's
    grammar-constrained sampling, so a small model cannot emit malformed
    JSON. Config:
        LLAMACPP_URL      default http://127.0.0.1:8081
        LLAMACPP_TIMEOUT  seconds, default 20 (CPU-only hosts are slow)
    """

    def __init__(self) -> None:
        import httpx

        self._url = os.environ.get("LLAMACPP_URL", "http://127.0.0.1:8081").rstrip("/")
        timeout = float(os.environ.get("LLAMACPP_TIMEOUT", "20"))
        self._client = httpx.Client(timeout=timeout)

    def route(self, query: str) -> RouterOutput | None:
        shots = [
            m
            for question, answer in _LOCAL_FEW_SHOT
            for m in (
                {"role": "user", "content": question},
                {"role": "assistant", "content": json.dumps(answer)},
            )
        ]
        body = {
            "messages": [{"role": "system", "content": _LOCAL_SYSTEM_PROMPT}]
            + shots
            + [{"role": "user", "content": query}],
            "temperature": 0,
            "max_tokens": 120,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": _TOOL_SCHEMA["name"], "schema": _LOCAL_SCHEMA},
            },
        }
        try:
            resp = self._client.post(f"{self._url}/v1/chat/completions", json=body)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            return _parse_payload(content, "LlamaCppRouter")
        except Exception as e:
            logger.warning("LlamaCppRouter.route failed: %s (%s)", type(e).__name__, e)
            return None


class OpenAIRouter:
    def __init__(self) -> None:
        raise NotImplementedError(
            "OpenAI provider not yet implemented; set LLM_PROVIDER=anthropic"
        )

    def route(self, query: str) -> RouterOutput | None:  # pragma: no cover
        return None


class OllamaRouter:
    def __init__(self) -> None:
        raise NotImplementedError(
            "Ollama provider not yet implemented; set LLM_PROVIDER=anthropic"
        )

    def route(self, query: str) -> RouterOutput | None:  # pragma: no cover
        return None


def get_router() -> Router | None:
    """Return the configured router, or None if disabled / unavailable.

    Returning None (rather than raising) is the contract: callers fall
    through to Concept-mode semantic search with a `fallback` field on
    the response.
    """
    provider = os.environ.get("LLM_PROVIDER", "").lower()
    if provider == "anthropic":
        try:
            return AnthropicRouter()
        except Exception as e:
            logger.warning(
                "AnthropicRouter init failed: %s (%s)", type(e).__name__, e
            )
            return None
    if provider == "llamacpp":
        try:
            return LlamaCppRouter()
        except Exception as e:
            logger.warning(
                "LlamaCppRouter init failed: %s (%s)", type(e).__name__, e
            )
            return None
    if provider in {"openai", "ollama"}:
        logger.warning("LLM_PROVIDER=%s is stubbed; routing disabled", provider)
        return None
    return None
