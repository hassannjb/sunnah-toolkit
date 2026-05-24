"""LLM-backed query router/rewriter for the Natural-language search mode.

Issue #4: turns a free-form query like "what did the Prophet say about anger?"
into a small set of focused retrieval variants (phrases / keywords, NOT
questions) plus a coarse mode hint. The variants are fed into the existing
union retriever (BM25 ∪ bi-encoder ∪ Arabic-term) per-variant and merged via
Reciprocal Rank Fusion in `retrieval.retrieve_union_multi`.

Provider selection is via $LLM_PROVIDER. Only `anthropic` is implemented;
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


@dataclass
class RouterOutput:
    mode_hint: str
    variants: list[str]


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
                    payload = block.input
                    if isinstance(payload, str):
                        payload = json.loads(payload)
                    mode_hint = str(payload.get("mode_hint", "concept"))
                    raw_variants = payload.get("variants") or []
                    variants = [
                        v.strip()
                        for v in raw_variants
                        if isinstance(v, str) and v.strip()
                    ][:_MAX_VARIANTS]
                    if not variants:
                        logger.warning("AnthropicRouter: empty variants list")
                        return None
                    return RouterOutput(mode_hint=mode_hint, variants=variants)
            logger.warning("AnthropicRouter: no tool_use block in response")
            return None
        except Exception as e:
            logger.warning(
                "AnthropicRouter response parse failed: %s (%s)",
                type(e).__name__,
                e,
            )
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
    if provider in {"openai", "ollama"}:
        logger.warning("LLM_PROVIDER=%s is stubbed; routing disabled", provider)
        return None
    return None
