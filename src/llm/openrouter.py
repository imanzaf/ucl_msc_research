"""OpenRouter chat-completion client with structured-output parsing and caching."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generic, List, Optional, Tuple, Type, TypeVar, Union, cast
from uuid import uuid4

from openai import OpenAI
from openai.lib._pydantic import to_strict_json_schema
from pydantic import BaseModel

from configs.api_settings import APISettings, OpenRouterCredentialRole
from configs.model_settings import ModelSettings
from src.data_models.experiments import (
    ExperimentStage,
    GenerationConfig,
    LLMCallFailureAttempt,
    LLMCallFailureRecord,
    LLMCallRecord,
    LLMCallUsage,
)
from src.llm.cache import LLMCallCache, build_cache_key

ParsedT = TypeVar("ParsedT", bound=Union[str, BaseModel])
StructuredOutputT = TypeVar("StructuredOutputT", bound=BaseModel)


class LLMCallResult(BaseModel, Generic[ParsedT]):
    """Return the parsed output together with the persisted call record."""

    parsed: ParsedT
    record: LLMCallRecord


class OpenRouterAttemptsExhausted(Exception):
    """Carry every failed OpenRouter attempt to the audit persistence boundary."""

    def __init__(self, attempts: List[LLMCallFailureAttempt]) -> None:
        """Store failed attempts and initialize the terminal exception."""
        super().__init__("OpenRouter request attempts exhausted")
        self.attempts = attempts


def utc_now_iso() -> str:
    """Return an ISO-8601 UTC timestamp for persisted call metadata."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def model_schema_name(output_model: Type[BaseModel]) -> str:
    """Return a stable JSON-schema name for a Pydantic model."""
    return output_model.__name__


def model_schema_hash(output_model: Optional[Type[BaseModel]]) -> str:
    """Return a stable hash for a structured-output schema."""
    if output_model is None:
        return "text"
    schema_payload = output_model.model_json_schema()
    return build_cache_key(schema_payload)


def strip_json_schema_defaults(schema: Any) -> Any:
    """Return a JSON-schema-compatible object with default keywords removed."""
    if isinstance(schema, dict):
        return {
            key: strip_json_schema_defaults(value)
            for key, value in schema.items()
            if key != "default"
        }
    if isinstance(schema, list):
        return [strip_json_schema_defaults(item) for item in schema]
    return schema


def openrouter_response_format(output_model: Type[BaseModel]) -> Dict[str, Any]:
    """Build the OpenRouter JSON-schema response_format payload."""
    return {
        "type": "json_schema",
        "json_schema": {
            "name": model_schema_name(output_model),
            "strict": True,
            "schema": strip_json_schema_defaults(to_strict_json_schema(output_model)),
        },
    }


def response_to_dict(response: Any) -> Dict[str, Any]:
    """Convert an OpenAI SDK response object or fake response into a dictionary."""
    if isinstance(response, dict):
        return response
    if hasattr(response, "model_dump"):
        return response.model_dump(mode="json")
    if hasattr(response, "to_dict"):
        return response.to_dict()
    raise TypeError(f"unsupported OpenRouter response object: {type(response)!r}")


def extract_text_output(response_payload: Dict[str, Any]) -> str:
    """Extract the first assistant message content from a chat-completion response."""
    choices = response_payload.get("choices", [])
    if not choices:
        raise ValueError("OpenRouter response did not include choices")
    message = choices[0].get("message", {})
    content = message.get("content", "")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("OpenRouter response did not include text content")
    return content


def parse_usage(usage_payload: Optional[Dict[str, Any]]) -> LLMCallUsage:
    """Parse OpenRouter usage details into a typed usage record."""
    if not usage_payload:
        return LLMCallUsage()
    completion_details = usage_payload.get("completion_tokens_details") or {}
    prompt_details = usage_payload.get("prompt_tokens_details") or {}
    cost_details = usage_payload.get("cost_details") or {}
    return LLMCallUsage(
        prompt_tokens=int(usage_payload.get("prompt_tokens") or 0),
        completion_tokens=int(usage_payload.get("completion_tokens") or 0),
        total_tokens=int(usage_payload.get("total_tokens") or 0),
        reasoning_tokens=int(completion_details.get("reasoning_tokens") or 0),
        cached_prompt_tokens=int(prompt_details.get("cached_tokens") or 0),
        cache_write_tokens=int(prompt_details.get("cache_write_tokens") or 0),
        cost_credits=float(usage_payload.get("cost") or 0.0),
        upstream_inference_cost=(
            float(cost_details["upstream_inference_cost"])
            if cost_details.get("upstream_inference_cost") is not None
            else None
        ),
    )


class OpenRouterStructuredClient:
    """Make cached OpenRouter chat-completion calls for text and Pydantic outputs."""

    def __init__(
        self,
        client: Any,
        cache: LLMCallCache,
        default_headers: Optional[Dict[str, str]] = None,
        max_retries: int = 2,
    ) -> None:
        """Create a client wrapper around an OpenAI-compatible chat-completions client."""
        self.client = client
        self.cache = cache
        self.default_headers = default_headers or {}
        self.max_retries = max_retries

    @classmethod
    def from_settings(
        cls,
        api_settings: APISettings,
        model_settings: ModelSettings,
        credential_role: OpenRouterCredentialRole,
        cache_dir: Path,
        cache_enabled: bool = True,
        refresh_cache: bool = False,
    ) -> "OpenRouterStructuredClient":
        """Create an OpenRouter client using the key assigned to one pipeline role."""
        headers: Dict[str, str] = {}
        if api_settings.openrouter_http_referer:
            headers["HTTP-Referer"] = api_settings.openrouter_http_referer
        if api_settings.openrouter_app_title:
            headers["X-OpenRouter-Title"] = api_settings.openrouter_app_title

        openai_client = OpenAI(
            api_key=api_settings.openrouter_api_key_for(credential_role),
            base_url=api_settings.openrouter_base_url,
            timeout=model_settings.openrouter_request_timeout_seconds,
            default_headers=headers or None,
        )
        return cls(
            client=openai_client,
            cache=LLMCallCache(cache_dir=cache_dir, enabled=cache_enabled, refresh=refresh_cache),
            default_headers=headers,
            max_retries=model_settings.max_generation_retries,
        )

    def complete_text(
        self,
        stage: ExperimentStage,
        model_id: str,
        messages: List[Dict[str, str]],
        generation_config: GenerationConfig,
        prompt_version: str,
        metadata: Optional[Dict[str, str]] = None,
    ) -> LLMCallResult[str]:
        """Request a text chat completion with local caching."""
        return self._complete(
            stage=stage,
            model_id=model_id,
            messages=messages,
            generation_config=generation_config,
            prompt_version=prompt_version,
            output_model=None,
            metadata=metadata,
        )

    def complete_structured(
        self,
        stage: ExperimentStage,
        model_id: str,
        messages: List[Dict[str, str]],
        output_model: Type[StructuredOutputT],
        generation_config: GenerationConfig,
        prompt_version: str,
        metadata: Optional[Dict[str, str]] = None,
        require_supported_parameters: bool = False,
    ) -> LLMCallResult[StructuredOutputT]:
        """Request a structured chat completion parsed as a Pydantic model."""
        return cast(
            LLMCallResult[StructuredOutputT],
            self._complete(
                stage=stage,
                model_id=model_id,
                messages=messages,
                generation_config=generation_config,
                prompt_version=prompt_version,
                output_model=output_model,
                metadata=metadata,
                require_supported_parameters=require_supported_parameters,
            ),
        )

    def _complete(
        self,
        stage: ExperimentStage,
        model_id: str,
        messages: List[Dict[str, str]],
        generation_config: GenerationConfig,
        prompt_version: str,
        output_model: Optional[Type[BaseModel]],
        metadata: Optional[Dict[str, str]],
        require_supported_parameters: bool = False,
    ) -> LLMCallResult[Any]:
        """Run a cached text or structured OpenRouter call."""
        request_payload = self._build_request_payload(
            model_id=model_id,
            messages=messages,
            generation_config=generation_config,
            output_model=output_model,
            metadata=metadata,
            require_supported_parameters=require_supported_parameters,
        )
        cache_payload = {
            "provider": "openrouter",
            "stage": stage.value,
            "prompt_version": prompt_version,
            "schema_hash": model_schema_hash(output_model),
            "request_payload": request_payload,
        }
        cache_key = build_cache_key(cache_payload)
        cached_record = self.cache.get(cache_key)
        if cached_record is not None:
            cached_output = self._parsed_from_record(cached_record, output_model)
            return LLMCallResult(
                parsed=cached_output,
                record=cached_record.model_copy(update={"cache_hit": True}),
            )

        try:
            response_payload, text_output, parsed_output = self._request_and_parse_with_retries(
                request_payload=request_payload,
                output_model=output_model,
            )
        except OpenRouterAttemptsExhausted as exc:
            self.cache.set_failure(
                LLMCallFailureRecord(
                    failure_id=str(uuid4()),
                    stage=stage,
                    model_id=model_id,
                    cache_key=cache_key,
                    created_at=utc_now_iso(),
                    prompt_version=prompt_version,
                    request_payload=request_payload,
                    attempts=exc.attempts,
                )
            )
            raise RuntimeError("OpenRouter request failed after retries") from exc

        usage = parse_usage(response_payload.get("usage"))
        record = LLMCallRecord(
            call_id=str(uuid4()),
            stage=stage,
            model_id=model_id,
            resolved_model_id=str(response_payload.get("model") or ""),
            generation_id=str(response_payload.get("id") or ""),
            cache_key=cache_key,
            cache_hit=False,
            created_at=utc_now_iso(),
            prompt_version=prompt_version,
            request_payload=request_payload,
            response_payload=response_payload,
            parsed_output=parsed_output.model_dump() if parsed_output is not None else None,
            text_output=None if parsed_output is not None else text_output,
            usage=usage,
        )
        self.cache.set(record)
        return LLMCallResult(
            parsed=parsed_output if parsed_output is not None else text_output, record=record
        )

    def _build_request_payload(
        self,
        model_id: str,
        messages: List[Dict[str, str]],
        generation_config: GenerationConfig,
        output_model: Optional[Type[BaseModel]],
        metadata: Optional[Dict[str, str]],
        require_supported_parameters: bool = False,
    ) -> Dict[str, Any]:
        """Build the JSON-compatible request payload for OpenRouter."""
        payload: Dict[str, Any] = {
            "model": model_id,
            "messages": messages,
            **generation_config.to_request_params(),
        }
        if metadata:
            payload["metadata"] = metadata
        if output_model is not None:
            payload["response_format"] = openrouter_response_format(output_model)
        if require_supported_parameters:
            payload["provider"] = {"require_parameters": True}
        return payload

    def _request_and_parse_with_retries(
        self,
        request_payload: Dict[str, Any],
        output_model: Optional[Type[BaseModel]],
    ) -> Tuple[Dict[str, Any], str, Optional[BaseModel]]:
        """Send a chat-completions request, retrying API and structured-parse failures."""
        attempts: List[LLMCallFailureAttempt] = []
        for attempt in range(1, self.max_retries + 2):
            response_payload: Dict[str, Any] = {}
            try:
                response = self.client.chat.completions.create(**request_payload)
                response_payload = response_to_dict(response)
                text_output = extract_text_output(response_payload)
                parsed_output = (
                    output_model.model_validate_json(text_output)
                    if output_model is not None
                    else None
                )
                return response_payload, text_output, parsed_output
            except Exception as exc:  # noqa: BLE001
                attempts.append(
                    LLMCallFailureAttempt(
                        attempt=attempt,
                        error_type=type(exc).__name__,
                        error_message=str(exc) or repr(exc),
                        response_payload=response_payload,
                    )
                )
        raise OpenRouterAttemptsExhausted(attempts)

    def _parsed_from_record(
        self,
        record: LLMCallRecord,
        output_model: Optional[Type[BaseModel]],
    ) -> Any:
        """Recover parsed output from a cached call record."""
        if output_model is None:
            if record.text_output is None:
                raise ValueError("cached text call is missing text_output")
            return record.text_output
        if record.parsed_output is None:
            if record.text_output is None:
                raise ValueError("cached structured call is missing parsed output")
            return output_model.model_validate(json.loads(record.text_output))
        return output_model.model_validate(record.parsed_output)
