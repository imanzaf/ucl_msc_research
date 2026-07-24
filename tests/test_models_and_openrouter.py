"""Test role credentials, model freeze, independent judges, exact requests, and caching."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest
from pydantic import Field

from src.data_models.common import VersionedImmutableModel
from src.data_models.experiments import provider_request_sha256
from src.data_models.manifests import FreezeStatus
from src.experiments.model_catalog import load_model_catalog, resolve_evaluated_model_ids
from src.llm.openrouter import OpenRouterClient, _strip_schema_defaults
from src.settings.api_settings import APISettings, OpenRouterCredentialRole
from src.settings.model_settings import ModelSettings


class StructuredFixture(VersionedImmutableModel):
    """Provide one strict structured-output fixture."""

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    answer: str


class FakeCompletions:
    """Record provider calls and return canned OpenRouter dictionaries."""

    def __init__(self, responses: List[Dict[str, Any]]) -> None:
        """Store responses and initialise a call log."""
        self.responses = list(responses)
        self.calls: List[Dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Dict[str, Any]:
        """Return the next response after recording request fields."""
        self.calls.append(kwargs)
        return self.responses.pop(0)


class FakeClient:
    """Expose the nested chat.completions API shape."""

    def __init__(self, responses: List[Dict[str, Any]]) -> None:
        """Create fake chat completions."""
        self.completions = FakeCompletions(responses)
        self.chat = type("Chat", (), {"completions": self.completions})()


def response(content: str) -> Dict[str, Any]:
    """Return a minimal provider response dictionary."""
    return {
        "id": "request-1",
        "model": "provider/model@frozen",
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


def api_values() -> Dict[str, str]:
    """Return complete settings without any removed simulator credential."""
    return {
        "OPENAI_API_KEY_CITATION_VALIDATOR": "citation",
        "ANTHROPIC_API_KEY_TEX_REVIEWER": "review",
        "ANTHROPIC_API_KEY_ACADEMIC_AUTHOR": "author",
        "OPENAI_API_KEY_RESEARCH_AUDITOR": "audit",
        "OPENROUTER_API_KEY_SCENARIO_GENERATION": "generation",
        "OPENROUTER_API_KEY_AGENT": "agent",
        "OPENROUTER_API_KEY_SCORING": "scoring",
    }


def test_api_roles_exclude_user_simulator_and_remain_separate() -> None:
    """Remove simulator credentials while preserving generation/agent/scoring isolation."""
    settings = APISettings(**api_values())
    assert set(OpenRouterCredentialRole) == {
        OpenRouterCredentialRole.SCENARIO_GENERATION,
        OpenRouterCredentialRole.AGENT,
        OpenRouterCredentialRole.SCORING,
    }
    assert settings.openrouter_api_key_for(OpenRouterCredentialRole.AGENT) == "agent"
    assert "openrouter_api_key_user_simulator" not in APISettings.model_fields


def test_ci_paid_call_switch_fails_before_client_construction() -> None:
    """Make the CI environment flag an enforced network boundary rather than documentation."""
    settings = APISettings(**{**api_values(), "CI_PAID_API_CALLS_DISABLED": "true"})
    with pytest.raises(PermissionError, match="disabled"):
        OpenRouterClient.from_settings(settings, ModelSettings(), OpenRouterCredentialRole.AGENT)


def test_model_catalog_is_deliberately_draft_and_blocked_before_calibration() -> None:
    """Require exactly three diverse candidates but prevent use until snapshots freeze."""
    catalog = load_model_catalog()
    assert catalog.schema_version == "2.0.0"
    assert catalog.freeze_status == FreezeStatus.DRAFT
    assert len(catalog.evaluated_models) == 3
    assert len({model.provider for model in catalog.evaluated_models}) >= 2
    assert any(model.weight_type.value == "open" for model in catalog.evaluated_models)
    assert catalog.scenario_generator_model.model_id != catalog.scenario_reviewer_model.model_id
    assert any(model.model_id not in {item.model_id for item in catalog.evaluated_models} for model in catalog.scoring_models)
    with pytest.raises(ValueError, match="must be frozen"):
        resolve_evaluated_model_ids(catalog, None)


def test_text_requests_cache_by_exact_bytes_and_do_not_repeat_provider_call(tmp_path: Path) -> None:
    """Reuse a matching local response only for the same exact request hash."""
    fake = FakeClient([response("A complete response.")])
    client = OpenRouterClient(fake, cache_dir=tmp_path)
    messages = [{"role": "user", "content": "Exact request."}]
    first = client.complete_text("provider/model", messages, temperature=0.0, max_tokens=500, seed=7)
    second = client.complete_text("provider/model", messages, temperature=0.0, max_tokens=500, seed=7)

    assert first == second
    assert len(fake.completions.calls) == 1
    cache_path = tmp_path / f"{provider_request_sha256(messages, 'provider/model', 0.0, 500, 7)}.json"
    assert cache_path.exists()
    cache_record = json.loads(cache_path.read_text(encoding="utf-8"))
    assert set(cache_record) == {
        "schema_version",
        "request_sha256",
        "response",
        "response_sha256",
        "cached_at",
        "record_sha256",
    }
    assert provider_request_sha256(messages, "provider/model", 0.0, 500, 7) != provider_request_sha256(messages, "provider/model", 0.0, 501, 7)


def test_structured_request_uses_strict_json_schema() -> None:
    """Require provider structured output to pass the Pydantic boundary."""
    fake = FakeClient([response('{"schema_version":"1.0.0","answer":"ok"}')])
    client = OpenRouterClient(fake)
    parsed = client.complete_structured(
        "judge/model",
        [{"role": "user", "content": "Return JSON."}],
        StructuredFixture,
        temperature=0.0,
        max_tokens=100,
        seed=7,
    )
    assert parsed.answer == "ok"
    assert fake.completions.calls[0]["response_format"]["type"] == "json_schema"
    assert fake.completions.calls[0]["response_format"]["json_schema"]["strict"] is True


def test_provider_schema_removes_unsupported_array_bounds_only() -> None:
    """Let provider endpoints accept the schema while local Pydantic keeps list bounds."""
    schema = {
        "type": "array",
        "minItems": 1,
        "maxItems": 4,
        "items": {"type": "string", "minLength": 1},
    }
    assert _strip_schema_defaults(schema) == {
        "type": "array",
        "items": {"type": "string", "minLength": 1},
    }


def test_structured_request_preserves_returned_snapshot_usage_finish_and_hashes() -> None:
    """Retain complete provider provenance for every automated scoring contract."""
    payload = response('{"schema_version":"1.0.0","answer":"ok"}')
    payload["choices"][0]["finish_reason"] = "stop"
    result = OpenRouterClient(FakeClient([payload])).complete_structured_with_provenance(
        "judge/model",
        [{"role": "user", "content": "Return JSON."}],
        StructuredFixture,
        temperature=0.0,
        max_tokens=100,
        seed=7,
    )
    assert result.returned_model_version == "provider/model@frozen"
    assert result.provider_request_id == "request-1"
    assert result.input_tokens == 10 and result.output_tokens == 5
    assert result.finish_reason.value == "stop"
    assert len(result.request_sha256) == len(result.response_sha256) == 64


def test_structured_request_can_require_support_and_enable_response_healing() -> None:
    """Route scenario calls only to supporting endpoints and repair malformed JSON syntax."""
    fake = FakeClient([response('{"schema_version":"1.0.0","answer":"ok"}')])
    OpenRouterClient(fake).complete_structured_with_provenance(
        "judge/model",
        [{"role": "user", "content": "Return JSON."}],
        StructuredFixture,
        temperature=0.0,
        max_tokens=100,
        seed=7,
        enable_response_healing=True,
        require_supported_parameters=True,
    )
    assert fake.completions.calls[0]["extra_body"] == {
        "plugins": [{"id": "response-healing"}],
        "provider": {"require_parameters": True},
    }


def test_structured_request_omits_unsupported_sampling_parameters() -> None:
    """Allow strict provider routing with role-specific temperature and seed support."""
    fake = FakeClient([response('{"schema_version":"1.0.0","answer":"ok"}')])
    OpenRouterClient(fake).complete_structured_with_provenance(
        "judge/model",
        [{"role": "user", "content": "Return JSON."}],
        StructuredFixture,
        temperature=None,
        max_tokens=100,
        seed=None,
    )
    assert "temperature" not in fake.completions.calls[0]
    assert "seed" not in fake.completions.calls[0]


def test_structured_request_repairs_json_syntax_before_strict_validation() -> None:
    """Repair malformed JSON locally while retaining an explicit provenance flag."""
    fake = FakeClient([response('{"schema_version":"1.0.0","answer":"ok"')])
    result = OpenRouterClient(fake).complete_structured_with_provenance(
        "judge/model",
        [{"role": "user", "content": "Return JSON."}],
        StructuredFixture,
        temperature=0.0,
        max_tokens=100,
        seed=7,
    )
    assert result.output.answer == "ok"
    assert result.response_repaired is True


def test_structured_attempt_log_keeps_raw_failed_response(tmp_path: Path) -> None:
    """Persist raw provider content and the exact local validation error."""
    raw_response = '{"schema_version":"1.0.0"}'
    fake = FakeClient([response(raw_response)])
    with pytest.raises(ValueError):
        OpenRouterClient(fake, structured_log_dir=tmp_path).complete_structured_with_provenance(
            "judge/model",
            [{"role": "user", "content": "Return JSON."}],
            StructuredFixture,
            temperature=0.0,
            max_tokens=100,
            seed=7,
        )
    attempt_paths = list(tmp_path.glob("*.json"))
    assert len(attempt_paths) == 1
    attempt = json.loads(attempt_paths[0].read_text(encoding="utf-8"))
    assert attempt["response_text"] == raw_response
    assert attempt["validation_succeeded"] is False
    assert attempt["validation_error_type"] == "ValidationError"
