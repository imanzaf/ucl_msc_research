"""Small OpenRouter adapter for exact text requests and structured scoring."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Generic, List, Optional, Tuple, Type, TypeVar, cast

from json_repair import repair_json
from openai import OpenAI
from openai.lib._pydantic import to_strict_json_schema
from pydantic import BaseModel, Field, field_validator, model_validator

from src.data_models.common import VersionedImmutableModel, artifact_sha256, canonical_json_bytes, sha256_bytes, utc_now, validate_sha256
from src.data_models.experiments import CompletionFinishReason, ProviderRouting, TokenUsage, provider_request_sha256
from src.settings.api_settings import APISettings, OpenRouterCredentialRole
from src.settings.model_settings import ModelSettings
from src.storage import atomic_write_bytes, write_model_json_atomic

StructuredT = TypeVar("StructuredT", bound=BaseModel)


def _strip_schema_defaults(value: Any) -> Any:
    """Remove JSON Schema keywords unsupported by configured provider endpoints."""
    if isinstance(value, dict):
        unsupported_keywords = {"default", "minItems", "maxItems"}
        return {key: _strip_schema_defaults(child) for key, child in value.items() if key not in unsupported_keywords}
    if isinstance(value, list):
        return [_strip_schema_defaults(child) for child in value]
    return value


def _optional_decimal(value: Any) -> Optional[Decimal]:
    """Parse an optional provider-reported monetary value without binary-float rounding."""
    return None if value is None else Decimal(str(value))


def _usage_costs(usage: Dict[str, Any]) -> Tuple[Optional[Decimal], Optional[Decimal]]:
    """Extract OpenRouter billed and upstream costs when the provider returns them."""
    cost_details = usage.get("cost_details") or {}
    if not isinstance(cost_details, dict):
        cost_details = {}
    return _optional_decimal(usage.get("cost")), _optional_decimal(cost_details.get("upstream_inference_cost"))


class ProviderTextResponse(VersionedImmutableModel):
    """Return provider text and audit metadata without mutating the request."""

    schema_version: str = Field(default="2.0.0", pattern=r"^2\.0\.0$")
    text: str = Field(min_length=1)
    provider_request_id: str = Field(min_length=1)
    returned_model_version: str = Field(min_length=1)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_credits: Optional[Decimal] = Field(default=None, ge=0)
    upstream_inference_cost: Optional[Decimal] = Field(default=None, ge=0)
    finish_reason: CompletionFinishReason


class ProviderStructuredResponse(VersionedImmutableModel, Generic[StructuredT]):
    """Return validated structured output with complete provider-call provenance."""

    schema_version: str = Field(default="2.0.0", pattern=r"^2\.0\.0$")
    output: StructuredT
    provider_request_id: str = Field(min_length=1)
    returned_model_version: str = Field(min_length=1)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_credits: Optional[Decimal] = Field(default=None, ge=0)
    upstream_inference_cost: Optional[Decimal] = Field(default=None, ge=0)
    finish_reason: CompletionFinishReason
    request_sha256: str
    response_sha256: str
    response_repaired: bool = False

    @field_validator("request_sha256", "response_sha256")
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        """Validate exact structured request and response digests."""
        return validate_sha256(value)


class ProviderStructuredAttemptRecord(VersionedImmutableModel):
    """Persist one raw structured response and its local validation outcome."""

    schema_version: str = Field(default="2.0.0", pattern=r"^2\.0\.0$")
    output_model_name: str = Field(min_length=1)
    requested_model_id: str = Field(min_length=1)
    returned_model_version: str = Field(min_length=1)
    provider_request_id: str = Field(min_length=1)
    finish_reason: CompletionFinishReason
    usage: TokenUsage
    request_sha256: str
    response_text: str
    response_sha256: str
    response_repaired: bool
    validation_succeeded: bool
    validation_error_type: Optional[str] = Field(default=None, min_length=1)
    validation_error_message: Optional[str] = Field(default=None, min_length=1)
    captured_at: datetime
    record_sha256: str

    @field_validator("request_sha256", "response_sha256", "record_sha256")
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        """Validate request, response, and record hashes."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_attempt(self) -> "ProviderStructuredAttemptRecord":
        """Bind raw bytes and require error details only after failed validation."""
        if self.response_sha256 != sha256_bytes(self.response_text.encode("utf-8")):
            raise ValueError("structured-attempt response hash does not match raw response text")
        has_complete_error = self.validation_error_type is not None and self.validation_error_message is not None
        has_partial_error = (self.validation_error_type is None) != (self.validation_error_message is None)
        if has_partial_error or self.validation_succeeded == has_complete_error:
            raise ValueError("structured-attempt validation outcome and error fields disagree")
        expected_hash = artifact_sha256(self.model_dump(mode="json", exclude={"record_sha256"}))
        if self.record_sha256 != expected_hash:
            raise ValueError("structured-attempt record hash does not match canonical content")
        return self


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

    def __init__(
        self,
        client: Any,
        cache_dir: Optional[Path] = None,
        paid_calls_disabled: bool = False,
        structured_log_dir: Optional[Path] = None,
        provider_routing: Optional[ProviderRouting] = None,
    ) -> None:
        """Wrap an OpenAI-compatible client with an optional exact-request cache."""
        self.client = client
        self.cache_dir = cache_dir
        self.paid_calls_disabled = paid_calls_disabled
        self.structured_log_dir = structured_log_dir
        self.provider_routing = provider_routing

    @classmethod
    def from_settings(
        cls,
        api_settings: APISettings,
        model_settings: ModelSettings,
        credential_role: OpenRouterCredentialRole,
        cache_dir: Optional[Path] = None,
        structured_log_dir: Optional[Path] = None,
        provider_routing: Optional[ProviderRouting] = None,
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
        return cls(
            client=client,
            cache_dir=cache_dir,
            paid_calls_disabled=api_settings.paid_api_calls_disabled,
            structured_log_dir=structured_log_dir,
            provider_routing=provider_routing,
        )

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
        request_hash = provider_request_sha256(messages, model_id, temperature, max_tokens, seed, self.provider_routing)
        cached = self.read_cached_text_response(request_hash)
        if cached is not None:
            return cached
        request_arguments: Dict[str, Any] = {
            "model": model_id,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "seed": seed,
        }
        if self.provider_routing is not None:
            request_arguments["extra_body"] = {"provider": self.provider_routing.model_dump(mode="json")}
        response = self.client.chat.completions.create(
            **request_arguments,
        )
        payload = response.model_dump(mode="json") if hasattr(response, "model_dump") else cast(Dict[str, Any], response)
        choices = payload.get("choices", [])
        if not choices or not isinstance(choices[0].get("message", {}).get("content"), str):
            raise ValueError("OpenRouter response did not contain assistant text")
        text = choices[0]["message"]["content"]
        if not text.strip():
            raise ValueError("OpenRouter response contained blank assistant text")
        usage = payload.get("usage") or {}
        if not isinstance(usage, dict):
            usage = {}
        cost_credits, upstream_inference_cost = _usage_costs(usage)
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
            cost_credits=cost_credits,
            upstream_inference_cost=upstream_inference_cost,
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
        temperature: Optional[float],
        max_tokens: int,
        seed: Optional[int],
        enable_response_healing: bool = False,
        require_supported_parameters: bool = False,
    ) -> ProviderStructuredResponse[StructuredT]:
        """Request strict JSON and retain returned identity, usage, finish, and exact hashes."""
        if self.paid_calls_disabled:
            raise PermissionError("external paid API calls are disabled")
        schema = _strip_schema_defaults(to_strict_json_schema(output_model))
        response_format = {
            "type": "json_schema",
            "json_schema": {"name": output_model.__name__, "strict": True, "schema": schema},
        }
        extra_body: Dict[str, Any] = {}
        if enable_response_healing:
            extra_body["plugins"] = [{"id": "response-healing"}]
        if require_supported_parameters:
            extra_body["provider"] = {"require_parameters": True}
        request_digest = artifact_sha256(
            {
                "model": model_id,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "seed": seed,
                "response_format": response_format,
                "extra_body": extra_body,
            }
        )
        request_arguments = {
            "model": model_id,
            "messages": messages,
            "max_tokens": max_tokens,
            "response_format": response_format,
        }
        if temperature is not None:
            request_arguments["temperature"] = temperature
        if seed is not None:
            request_arguments["seed"] = seed
        if extra_body:
            request_arguments["extra_body"] = extra_body
        response = self.client.chat.completions.create(**request_arguments)
        payload = response.model_dump(mode="json") if hasattr(response, "model_dump") else cast(Dict[str, Any], response)
        choices = payload.get("choices", [])
        if not choices:
            raise ValueError("OpenRouter structured response did not contain choices")
        content = choices[0].get("message", {}).get("content")
        if not isinstance(content, str):
            raise ValueError("OpenRouter structured response did not contain JSON text")
        usage = payload.get("usage") or {}
        if not isinstance(usage, dict):
            usage = {}
        cost_credits, upstream_inference_cost = _usage_costs(usage)
        raw_finish_reason = str(choices[0].get("finish_reason") or "unknown")
        try:
            finish_reason = CompletionFinishReason(raw_finish_reason)
        except ValueError:
            finish_reason = CompletionFinishReason.UNKNOWN
        provider_request_id = str(payload.get("id") or "unknown")
        returned_model_version = str(payload.get("model") or model_id)
        input_tokens = int(usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or 0)
        response_digest = sha256_bytes(content.encode("utf-8"))
        response_repaired = False
        try:
            try:
                parsed_content = json.loads(content)
            except json.JSONDecodeError:
                parsed_content = repair_json(content, return_objects=True)
                response_repaired = True
            output = output_model.model_validate(parsed_content)
        except Exception as error:
            self._write_structured_attempt(
                output_model_name=output_model.__name__,
                requested_model_id=model_id,
                returned_model_version=returned_model_version,
                provider_request_id=provider_request_id,
                finish_reason=finish_reason,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_credits=cost_credits,
                upstream_inference_cost=upstream_inference_cost,
                request_digest=request_digest,
                response_text=content,
                response_digest=response_digest,
                response_repaired=response_repaired,
                validation_error=error,
            )
            raise
        self._write_structured_attempt(
            output_model_name=output_model.__name__,
            requested_model_id=model_id,
            returned_model_version=returned_model_version,
            provider_request_id=provider_request_id,
            finish_reason=finish_reason,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_credits=cost_credits,
            upstream_inference_cost=upstream_inference_cost,
            request_digest=request_digest,
            response_text=content,
            response_digest=response_digest,
            response_repaired=response_repaired,
        )
        return ProviderStructuredResponse(
            output=output,
            provider_request_id=provider_request_id,
            returned_model_version=returned_model_version,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_credits=cost_credits,
            upstream_inference_cost=upstream_inference_cost,
            finish_reason=finish_reason,
            request_sha256=request_digest,
            response_sha256=response_digest,
            response_repaired=response_repaired,
        )

    def _write_structured_attempt(
        self,
        output_model_name: str,
        requested_model_id: str,
        returned_model_version: str,
        provider_request_id: str,
        finish_reason: CompletionFinishReason,
        input_tokens: int,
        output_tokens: int,
        cost_credits: Optional[Decimal],
        upstream_inference_cost: Optional[Decimal],
        request_digest: str,
        response_text: str,
        response_digest: str,
        response_repaired: bool,
        validation_error: Optional[Exception] = None,
    ) -> None:
        """Persist one raw response and whether its local structured validation passed."""
        if self.structured_log_dir is None:
            return
        payload = {
            "schema_version": "2.0.0",
            "output_model_name": output_model_name,
            "requested_model_id": requested_model_id,
            "returned_model_version": returned_model_version,
            "provider_request_id": provider_request_id,
            "finish_reason": finish_reason,
            "usage": TokenUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                cost_credits=cost_credits,
                upstream_inference_cost=upstream_inference_cost,
            ),
            "request_sha256": request_digest,
            "response_text": response_text,
            "response_sha256": response_digest,
            "response_repaired": response_repaired,
            "validation_succeeded": validation_error is None,
            "validation_error_type": type(validation_error).__name__ if validation_error is not None else None,
            "validation_error_message": str(validation_error) if validation_error is not None else None,
            "captured_at": utc_now(),
        }
        record = ProviderStructuredAttemptRecord.model_validate({**payload, "record_sha256": artifact_sha256(payload)})
        request_id_digest = sha256_bytes(provider_request_id.encode("utf-8"))[:16]
        write_model_json_atomic(self.structured_log_dir / f"{request_digest}_{request_id_digest}.json", record)

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
