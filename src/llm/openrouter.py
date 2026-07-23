"""Small OpenRouter adapter for exact text requests and structured scoring."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Generic, List, Optional, Type, TypeVar, cast

from openai import OpenAI
from openai.lib._pydantic import to_strict_json_schema
from pydantic import BaseModel, Field, field_validator, model_validator

from src.data_models.common import VersionedImmutableModel, artifact_sha256, canonical_json_bytes, sha256_bytes, utc_now, validate_sha256
from src.data_models.experiments import CompletionFinishReason, provider_request_sha256
from src.settings.api_settings import APISettings, OpenRouterCredentialRole
from src.settings.model_settings import ModelSettings
from src.storage import atomic_write_bytes

StructuredT = TypeVar("StructuredT", bound=BaseModel)


def _strip_schema_defaults(value: Any) -> Any:
    """Remove default keywords that strict provider JSON Schema rejects."""
    if isinstance(value, dict):
        return {key: _strip_schema_defaults(child) for key, child in value.items() if key != "default"}
    if isinstance(value, list):
        return [_strip_schema_defaults(child) for child in value]
    return value


class ProviderTextResponse(VersionedImmutableModel):
    """Return provider text and audit metadata without mutating the request."""

    schema_version: str = Field(default="2.0.0", pattern=r"^2\.0\.0$")
    text: str = Field(min_length=1)
    provider_request_id: str = Field(min_length=1)
    returned_model_version: str = Field(min_length=1)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    finish_reason: CompletionFinishReason


class ProviderStructuredResponse(VersionedImmutableModel, Generic[StructuredT]):
    """Return validated structured output with complete provider-call provenance."""

    schema_version: str = Field(default="2.0.0", pattern=r"^2\.0\.0$")
    output: StructuredT
    provider_request_id: str = Field(min_length=1)
    returned_model_version: str = Field(min_length=1)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    finish_reason: CompletionFinishReason
    request_sha256: str
    response_sha256: str

    @field_validator("request_sha256", "response_sha256")
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        """Validate exact structured request and response digests."""
        return validate_sha256(value)


class ProviderTextCacheRecord(VersionedImmutableModel):
    """Persist one exact-request text response in the local provider cache."""

    schema_version: str = Field(default="2.0.0", pattern=r"^2\.0\.0$")
    request_sha256: str
    response: ProviderTextResponse
    response_sha256: str
    cached_at: datetime
    record_sha256: str

    @field_validator("request_sha256", "response_sha256", "record_sha256")
    @classmethod
    def validate_request_hash(cls, value: str) -> str:
        """Validate every cached request, response, and record digest."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_cache_record(self) -> "ProviderTextCacheRecord":
        """Bind the cache record to the exact response text and canonical record content."""
        if self.response_sha256 != sha256_bytes(self.response.text.encode("utf-8")):
            raise ValueError("OpenRouter cache response hash does not match response text")
        expected = artifact_sha256(self.model_dump(mode="json", exclude={"record_sha256"}))
        if self.record_sha256 != expected:
            raise ValueError("OpenRouter cache record hash does not match canonical content")
        return self


class OpenRouterClient:
    """Make one-attempt OpenAI-compatible requests; retry policy belongs to callers."""

    def __init__(self, client: Any, cache_dir: Optional[Path] = None, paid_calls_disabled: bool = False) -> None:
        """Wrap an OpenAI-compatible client with an optional exact-request cache."""
        self.client = client
        self.cache_dir = cache_dir
        self.paid_calls_disabled = paid_calls_disabled

    @classmethod
    def from_settings(
        cls,
        api_settings: APISettings,
        model_settings: ModelSettings,
        credential_role: OpenRouterCredentialRole,
        cache_dir: Optional[Path] = None,
    ) -> "OpenRouterClient":
        """Construct a role-scoped OpenRouter client from Pydantic settings."""
        if api_settings.paid_api_calls_disabled:
            raise PermissionError("external paid API clients are disabled by CI_PAID_API_CALLS_DISABLED")
        default_headers: Dict[str, str] = {}
        if api_settings.openrouter_http_referer:
            default_headers["HTTP-Referer"] = api_settings.openrouter_http_referer
        if api_settings.openrouter_app_title:
            default_headers["X-OpenRouter-Title"] = api_settings.openrouter_app_title
        client = OpenAI(
            api_key=api_settings.openrouter_api_key_for(credential_role),
            base_url=api_settings.openrouter_base_url,
            timeout=model_settings.openrouter_request_timeout_seconds,
            default_headers=default_headers or None,
        )
        return cls(client=client, cache_dir=cache_dir, paid_calls_disabled=api_settings.paid_api_calls_disabled)

    def complete_text(
        self,
        model_id: str,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        seed: int,
    ) -> ProviderTextResponse:
        """Complete one exact text request, reusing a matching local cache record."""
        if self.paid_calls_disabled:
            raise PermissionError("external paid API calls are disabled")
        request_hash = provider_request_sha256(messages, model_id, temperature, max_tokens, seed)
        cached = self.read_cached_text_response(request_hash)
        if cached is not None:
            return cached
        response = self.client.chat.completions.create(
            model=model_id,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            seed=seed,
        )
        payload = response.model_dump(mode="json") if hasattr(response, "model_dump") else cast(Dict[str, Any], response)
        choices = payload.get("choices", [])
        if not choices or not isinstance(choices[0].get("message", {}).get("content"), str):
            raise ValueError("OpenRouter response did not contain assistant text")
        text = choices[0]["message"]["content"]
        if not text.strip():
            raise ValueError("OpenRouter response contained blank assistant text")
        usage = payload.get("usage") or {}
        raw_finish_reason = str(choices[0].get("finish_reason") or "unknown")
        try:
            finish_reason = CompletionFinishReason(raw_finish_reason)
        except ValueError:
            finish_reason = CompletionFinishReason.UNKNOWN
        result = ProviderTextResponse(
            text=text,
            provider_request_id=str(payload.get("id") or "unknown"),
            returned_model_version=str(payload.get("model") or model_id),
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
            finish_reason=finish_reason,
        )
        self._write_cache(request_hash, result)
        return result

    def complete_structured(
        self,
        model_id: str,
        messages: List[Dict[str, str]],
        output_model: Type[StructuredT],
        temperature: float,
        max_tokens: int,
        seed: int,
    ) -> StructuredT:
        """Request strict JSON Schema output and validate it as a Pydantic model."""
        return self.complete_structured_with_provenance(
            model_id,
            messages,
            output_model,
            temperature,
            max_tokens,
            seed,
        ).output

    def complete_structured_with_provenance(
        self,
        model_id: str,
        messages: List[Dict[str, str]],
        output_model: Type[StructuredT],
        temperature: float,
        max_tokens: int,
        seed: int,
    ) -> ProviderStructuredResponse[StructuredT]:
        """Request strict JSON and retain returned identity, usage, finish, and exact hashes."""
        if self.paid_calls_disabled:
            raise PermissionError("external paid API calls are disabled")
        schema = _strip_schema_defaults(to_strict_json_schema(output_model))
        response_format = {
            "type": "json_schema",
            "json_schema": {"name": output_model.__name__, "strict": True, "schema": schema},
        }
        request_digest = artifact_sha256(
            {
                "model": model_id,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "seed": seed,
                "response_format": response_format,
            }
        )
        response = self.client.chat.completions.create(
            model=model_id,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            seed=seed,
            response_format=response_format,
        )
        payload = response.model_dump(mode="json") if hasattr(response, "model_dump") else cast(Dict[str, Any], response)
        choices = payload.get("choices", [])
        if not choices:
            raise ValueError("OpenRouter structured response did not contain choices")
        content = choices[0].get("message", {}).get("content")
        if not isinstance(content, str):
            raise ValueError("OpenRouter structured response did not contain JSON text")
        usage = payload.get("usage") or {}
        raw_finish_reason = str(choices[0].get("finish_reason") or "unknown")
        try:
            finish_reason = CompletionFinishReason(raw_finish_reason)
        except ValueError:
            finish_reason = CompletionFinishReason.UNKNOWN
        return ProviderStructuredResponse(
            output=output_model.model_validate_json(content),
            provider_request_id=str(payload.get("id") or "unknown"),
            returned_model_version=str(payload.get("model") or model_id),
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
            finish_reason=finish_reason,
            request_sha256=request_digest,
            response_sha256=sha256_bytes(content.encode("utf-8")),
        )

    def _cache_path(self, request_hash: str) -> Optional[Path]:
        """Return the cache path for one exact request hash."""
        return self.cache_dir / f"{request_hash}.json" if self.cache_dir is not None else None

    def read_cached_text_response(self, request_hash: str) -> Optional[ProviderTextResponse]:
        """Read a successful exact-request response without making a provider call."""
        path = self._cache_path(request_hash)
        if path is None or not path.exists():
            return None
        record = ProviderTextCacheRecord.model_validate_json(path.read_text(encoding="utf-8"))
        if record.request_sha256 != request_hash:
            raise ValueError("OpenRouter cache key does not match cached request hash")
        return record.response

    def _write_cache(self, request_hash: str, result: ProviderTextResponse) -> None:
        """Atomically cache a successful provider response by exact request hash."""
        path = self._cache_path(request_hash)
        if path is None:
            return
        payload = {
            "schema_version": "2.0.0",
            "request_sha256": request_hash,
            "response": result,
            "response_sha256": sha256_bytes(result.text.encode("utf-8")),
            "cached_at": utc_now(),
        }
        record = ProviderTextCacheRecord.model_validate({**payload, "record_sha256": artifact_sha256(payload)})
        atomic_write_bytes(path, canonical_json_bytes(record) + b"\n")
