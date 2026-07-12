"""Tests for the shared OpenRouter client wrapper and cache."""

from __future__ import annotations

from typing import Any, Dict, List

from src.data_models.experiments import ExperimentStage, ExperimentUsageSummary, GenerationConfig
from src.data_models.scenarios import GeneratedScenarioInstance
from src.data_models.user_simulator import UserSimulatorTurnOutput
from src.llm.cache import LLMCallCache, build_cache_key
from src.llm.openrouter import OpenRouterStructuredClient, openrouter_response_format


class FakeChatCompletions:
    """Fake chat completions API that records requests and returns canned responses."""

    def __init__(self, responses: List[Dict[str, Any]]) -> None:
        """Store canned responses for later calls."""
        self.responses = list(responses)
        self.calls: List[Dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Dict[str, Any]:
        """Record one request and return the next response."""
        self.calls.append(kwargs)
        return self.responses.pop(0)


class FakeChat:
    """Fake chat namespace matching the OpenAI SDK shape."""

    def __init__(self, completions: FakeChatCompletions) -> None:
        """Attach fake completions to the chat namespace."""
        self.completions = completions


class FakeClient:
    """Fake OpenAI-compatible client with chat completions."""

    def __init__(self, responses: List[Dict[str, Any]]) -> None:
        """Create a fake client around canned responses."""
        self.completions = FakeChatCompletions(responses)
        self.chat = FakeChat(self.completions)


def make_response(content: str) -> Dict[str, Any]:
    """Create a minimal OpenRouter-style chat-completion response."""
    return {
        "id": "gen_123",
        "model": "openai/gpt-5.5",
        "choices": [{"message": {"content": content}}],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
            "completion_tokens_details": {"reasoning_tokens": 2},
            "prompt_tokens_details": {"cached_tokens": 3, "cache_write_tokens": 4},
            "cost": 0.25,
            "cost_details": {"upstream_inference_cost": 0.2},
        },
    }


def test_structured_call_parses_usage_and_response_format(tmp_path) -> None:
    """Verify structured calls include JSON schema response_format and parse usage."""
    fake_client = FakeClient(
        [make_response('{"should_continue": false, "rationale": "Enough detail."}')]
    )
    client = OpenRouterStructuredClient(
        client=fake_client,
        cache=LLMCallCache(tmp_path),
        max_retries=0,
    )

    result = client.complete_structured(
        stage=ExperimentStage.USER_SIMULATOR_TURN,
        model_id="openai/gpt-5.5",
        messages=[{"role": "user", "content": "Continue?"}],
        output_model=UserSimulatorTurnOutput,
        generation_config=GenerationConfig(),
        prompt_version="test_prompt_v1",
    )

    assert result.parsed.should_continue is False
    assert result.record.usage.total_tokens == 15
    assert result.record.usage.reasoning_tokens == 2
    assert fake_client.completions.calls[0]["response_format"]["type"] == "json_schema"


def test_cache_hit_returns_cached_record_without_second_api_call(tmp_path) -> None:
    """Verify identical calls are served from the local cache on repeat."""
    fake_client = FakeClient([make_response("Cached answer.")])
    client = OpenRouterStructuredClient(
        client=fake_client,
        cache=LLMCallCache(tmp_path),
        max_retries=0,
    )
    kwargs = {
        "stage": ExperimentStage.AGENT_RESPONSE,
        "model_id": "openai/gpt-5.5",
        "messages": [{"role": "user", "content": "Answer"}],
        "generation_config": GenerationConfig(),
        "prompt_version": "agent_prompt_v1",
    }

    first = client.complete_text(**kwargs)
    second = client.complete_text(**kwargs)

    assert first.record.cache_hit is False
    assert second.record.cache_hit is True
    assert second.parsed == "Cached answer."
    assert len(fake_client.completions.calls) == 1


def test_structured_call_retries_after_invalid_json(tmp_path) -> None:
    """Verify structured-output parse failures are retried."""
    fake_client = FakeClient(
        [
            make_response("not valid json"),
            make_response('{"should_continue": false, "rationale": "Valid retry."}'),
        ]
    )
    client = OpenRouterStructuredClient(
        client=fake_client,
        cache=LLMCallCache(tmp_path),
        max_retries=1,
    )

    result = client.complete_structured(
        stage=ExperimentStage.USER_SIMULATOR_TURN,
        model_id="openai/gpt-5.5",
        messages=[{"role": "user", "content": "Continue?"}],
        output_model=UserSimulatorTurnOutput,
        generation_config=GenerationConfig(),
        prompt_version="retry_prompt_v1",
    )

    assert result.parsed.rationale == "Valid retry."
    assert len(fake_client.completions.calls) == 2


def test_cache_key_is_stable_for_sorted_payloads() -> None:
    """Verify cache keys ignore dictionary insertion order."""
    assert build_cache_key({"b": 2, "a": 1}) == build_cache_key({"a": 1, "b": 2})


def test_response_format_requires_every_nested_property() -> None:
    """Verify Pydantic defaults are converted to strict structured-output requirements."""
    response_format = openrouter_response_format(GeneratedScenarioInstance)
    schema = response_format["json_schema"]["schema"]
    fact_unit_schema = schema["$defs"]["FactUnit"]

    assert set(fact_unit_schema["required"]) == set(fact_unit_schema["properties"])
    assert "specificity_markers" in fact_unit_schema["required"]
    assert "default" not in fact_unit_schema["properties"]["specificity_markers"]
    assert fact_unit_schema["additionalProperties"] is False
    assert "$ref" not in fact_unit_schema["properties"]["polarity"]


def test_session_id_is_nested_in_supported_metadata(tmp_path) -> None:
    """Verify session identifiers are not sent as unsupported top-level completion arguments."""
    fake_client = FakeClient([make_response("Metadata accepted.")])
    client = OpenRouterStructuredClient(
        client=fake_client,
        cache=LLMCallCache(tmp_path),
        max_retries=0,
    )

    client.complete_text(
        stage=ExperimentStage.AGENT_RESPONSE,
        model_id="openai/gpt-5.5",
        messages=[{"role": "user", "content": "Answer"}],
        generation_config=GenerationConfig(),
        prompt_version="metadata_prompt_v1",
        metadata={"session_id": "session-123", "stage": "agent_response"},
    )

    request = fake_client.completions.calls[0]
    assert request["metadata"]["session_id"] == "session-123"
    assert "session_id" not in request


def test_usage_summary_excludes_local_cache_hits_from_actual_spend(tmp_path) -> None:
    """Verify local cache hits are counted but not billed as new spend."""
    fake_client = FakeClient([make_response("Cached answer.")])
    client = OpenRouterStructuredClient(
        client=fake_client,
        cache=LLMCallCache(tmp_path),
        max_retries=0,
    )
    kwargs = {
        "stage": ExperimentStage.AGENT_RESPONSE,
        "model_id": "openai/gpt-5.5",
        "messages": [{"role": "user", "content": "Usage"}],
        "generation_config": GenerationConfig(),
        "prompt_version": "usage_prompt_v1",
    }
    first = client.complete_text(**kwargs)
    second = client.complete_text(**kwargs)
    summary = ExperimentUsageSummary()
    summary.add_call(first.record.usage, first.record.cache_hit)
    summary.add_call(second.record.usage, second.record.cache_hit)

    assert summary.api_call_count == 1
    assert summary.local_cache_hit_count == 1
    assert summary.cost_credits == 0.5
    assert summary.actual_cost_credits == 0.25
