"""Pinned-provider OpenRouter transport with transport-only retries."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from openai import APIConnectionError, APITimeoutError, InternalServerError, OpenAI, RateLimitError
from pydantic import Field

from srcv2.common import ImmutableModel, utc_now
from srcv2.models.experiments import GenerationControls, ProviderSnapshot
from srcv2.settings.api_settings import APISettings, CredentialRole
from srcv2.settings.model_settings import ModelSettings


class TransportFailure(RuntimeError):
    """Indicate that every allowed attempt failed before semantic output arrived."""


class ProviderReply(ImmutableModel):
    """Return semantic text and provider metadata without parsing or regeneration."""

    text: str
    provider_request_id: str
    provider_name: Optional[str] = None
    returned_model_version: str
    finish_reason: Optional[str]
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    billed_cost: Optional[Decimal] = Field(default=None, ge=0)
    received_at: datetime
    attempts: int = Field(ge=1)


class OpenRouterClient:
    """Make preflighted OpenRouter requests without semantic retries."""

    def __init__(self, client: Any, settings: ModelSettings) -> None:
        """Wrap an OpenAI-compatible client and explicit transport policy."""
        self.client = client
        self.settings = settings

    @classmethod
    def from_settings(cls, api_settings: APISettings, model_settings: ModelSettings, role: CredentialRole) -> "OpenRouterClient":
        """Construct a zero-SDK-retry client after enforcing the paid-call kill switch."""
        if api_settings.paid_api_calls_disabled:
            raise PermissionError("paid API calls are disabled")
        headers: Dict[str, str] = {}
        if api_settings.openrouter_http_referer:
            headers["HTTP-Referer"] = api_settings.openrouter_http_referer
        if api_settings.openrouter_app_title:
            headers["X-OpenRouter-Title"] = api_settings.openrouter_app_title
        client = OpenAI(
            api_key=api_settings.key_for(role),
            base_url=api_settings.openrouter_base_url.rstrip("/"),
            timeout=model_settings.request_timeout_seconds,
            max_retries=0,
            default_headers=headers or None,
        )
        return cls(client, model_settings)

    def complete(self, model: ProviderSnapshot, controls: GenerationControls, messages: List[Dict[str, str]]) -> ProviderReply:
        """Retry only provider transport failures that returned no semantic response."""
        if not model.preflight_passed:
            raise PermissionError("model/provider snapshot has not passed operational preflight")
        retryable = (APIConnectionError, APITimeoutError, InternalServerError, RateLimitError)
        last_error: Optional[Exception] = None
        for attempt in range(1, self.settings.transport_retry_limit + 2):
            try:
                payload = self._request(model, controls, messages)
                return self._reply(payload, attempt)
            except retryable as error:
                last_error = error
        raise TransportFailure(f"provider transport failed after {self.settings.transport_retry_limit + 1} attempts") from last_error

    def _request(self, model: ProviderSnapshot, controls: GenerationControls, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        """Send one request under the frozen routing policy and supported controls."""
        if model.routing_policy == "one_provider_only_no_fallback":
            provider: Dict[str, Any] = {
                "only": [model.provider_name],
                "allow_fallbacks": False,
                "require_parameters": True,
            }
        elif model.routing_policy == "openrouter_default_require_parameters":
            provider = {"require_parameters": True}
        else:
            raise ValueError(f"unsupported routing policy: {model.routing_policy}")
        extra_body: Dict[str, Any] = {"provider": provider, **controls.extra_parameters}
        arguments: Dict[str, Any] = {
            "model": model.model_slug,
            "messages": messages,
            "max_tokens": controls.max_output_tokens,
            "extra_body": extra_body,
        }
        if controls.temperature is not None:
            arguments["temperature"] = controls.temperature
        if controls.seed is not None:
            arguments["seed"] = controls.seed
        if controls.reasoning_effort is not None:
            arguments["reasoning_effort"] = controls.reasoning_effort
        response = self.client.chat.completions.create(**arguments)
        return response.model_dump(mode="json") if hasattr(response, "model_dump") else dict(response)

    @staticmethod
    def _reply(payload: Dict[str, Any], attempt: int) -> ProviderReply:
        """Preserve provider-returned text, including an empty or truncated completion."""
        choices = payload.get("choices") or []
        content = choices[0].get("message", {}).get("content") if choices else None
        text = content if isinstance(content, str) else ""
        usage = payload.get("usage") or {}
        cost = usage.get("cost")
        return ProviderReply(
            text=text,
            provider_request_id=str(payload.get("id") or "missing_provider_request_id"),
            provider_name=str(payload["provider"]) if payload.get("provider") else None,
            returned_model_version=str(payload.get("model") or "missing_returned_model_version"),
            finish_reason=choices[0].get("finish_reason") if choices else None,
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
            billed_cost=Decimal(str(cost)) if cost is not None else None,
            received_at=utc_now(),
            attempts=attempt,
        )
