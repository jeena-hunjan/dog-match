"""Provider-agnostic LLM client: one method that returns JSON matching a schema.

Callers depend on the `LLMClient` protocol, so tests can pass a fake and the provider can
change without touching them. `AnthropicClient` is the current implementation; it uses
structured outputs (`output_config.format`), so the reply is always valid JSON for the
schema. Never call a real LLM in CI.
"""

import json
import os
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import anthropic
from anthropic.types import OutputConfigParam

Effort = Literal["low", "medium", "high", "xhigh", "max"]


class LLMError(RuntimeError):
    """The model did not return a usable answer (refusal, truncation, API failure)."""


@dataclass
class Usage:
    """Running token totals, for cost reporting."""

    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class LLMClient(Protocol):
    model: str
    usage: Usage

    def complete_json(
        self, *, system: str, user: str, schema: dict[str, Any], max_tokens: int = 4096
    ) -> dict[str, Any]: ...


@dataclass
class AnthropicClient:
    """Claude via the Anthropic SDK.

    Claude Haiku 5.5 rejects non-default sampling parameters, so there is no temperature
    setting; reproducibility comes from caching and committing the outputs instead.
    """

    model: str
    api_key: str
    effort: Effort = "low"
    timeout_s: float = 120.0
    max_retries: int = 4  # the SDK retries 408/409/429/5xx and connection errors
    usage: Usage = field(default_factory=Usage)

    def __post_init__(self) -> None:
        self._client = anthropic.Anthropic(
            api_key=self.api_key, timeout=self.timeout_s, max_retries=self.max_retries
        )

    def complete_json(
        self, *, system: str, user: str, schema: dict[str, Any], max_tokens: int = 4096
    ) -> dict[str, Any]:
        output_config: OutputConfigParam = {
            "format": {"type": "json_schema", "schema": schema},
            "effort": self.effort,
        }
        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config=output_config,
            )
        except anthropic.APIError as e:
            raise LLMError(f"{type(e).__name__}: {e}") from e

        self.usage.requests += 1
        self.usage.input_tokens += response.usage.input_tokens
        self.usage.output_tokens += response.usage.output_tokens
        if response.stop_reason == "refusal":
            raise LLMError(f"model refused: {response.stop_details}")
        if response.stop_reason == "max_tokens":
            raise LLMError(f"reply truncated at max_tokens={max_tokens}")
        text = next((b.text for b in response.content if b.type == "text"), None)
        if text is None:
            raise LLMError("reply had no text block")
        result: dict[str, Any] = json.loads(text)
        return result


def client_from_env(effort: Effort = "low") -> AnthropicClient:
    """Build the client from LLM_API_KEY and LLM_MODEL (see .env.example)."""
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    model = os.environ.get("LLM_MODEL", "").strip()
    if not api_key or not model:
        raise LLMError("LLM_API_KEY and LLM_MODEL must be set (see .env.example)")
    return AnthropicClient(model=model, api_key=api_key, effort=effort)
