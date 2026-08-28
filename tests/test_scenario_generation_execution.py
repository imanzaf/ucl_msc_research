"""Approval, one-shot retention, and resume tests for scenario fact generation."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, List

import pytest

from src.common import utc_now
from src.llm.openrouter import ProviderReply
from src.models.experiments import GenerationControls, ProviderSnapshot
from src.models.manifests import ScenarioGenerationApproval
from src.paths import SCENARIO_ROOT
from src.scenarios.execution import build_generation_approval, build_generation_estimate, run_scenario_generation
from src.scenarios.generation import GenerationRequest
from src.storage import read_jsonl


class FakeGenerationClient:
    """Return deterministic structured outputs while counting semantic calls."""

    def __init__(self, malformed_scenario_id: str | None = None) -> None:
        """Configure an optional scenario whose first semantic output is malformed."""
        self.malformed_scenario_id = malformed_scenario_id
        self.call_count = 0

    def complete(self, model: ProviderSnapshot, controls: GenerationControls, messages: List[Dict[str, str]]) -> ProviderReply:
        """Return one probe result or one generated six-fact response."""
        self.call_count += 1
        if len(messages) == 1:
            text = json.dumps({"status": "PREFLIGHT_OK"})
        else:
            seed = json.loads(messages[1]["content"])
            if seed["scenario_id"] == self.malformed_scenario_id:
                text = "not-json"
            else:
                names = {option["option_id"]: option["company_name"] for option in seed["options"]}
                facts = [
                    {
                        **slot,
                        "text": f"{names[slot['option_id']]} offers {slot['anchor']}.",
                    }
                    for slot in seed["expected_fact_slots"]
                ]
                text = json.dumps({"schema_version": "4.0.0", "scenario_id": seed["scenario_id"], "facts": facts})
        return ProviderReply(
            text=text,
            provider_request_id=f"request-{self.call_count}",
            returned_model_version="openai/gpt-5.4-2026-03-05",
            finish_reason="stop",
            input_tokens=100,
            output_tokens=100,
            billed_cost=Decimal("0.00175"),
            received_at=utc_now(),
            attempts=1,
        )


def _requests() -> List[GenerationRequest]:
    """Load the repository's exact thirty-request batch."""
    return [GenerationRequest.model_validate(record) for record in read_jsonl(SCENARIO_ROOT / "generation_requests.jsonl")]


def _approval(requests: List[GenerationRequest], approved_at: datetime | None = None) -> ScenarioGenerationApproval:
    """Build a matching test approval with the research ceiling."""
    estimate = build_generation_estimate(requests, estimated_at=approved_at)
    return build_generation_approval(estimate, Decimal("1.25"), "test researcher", "approved test generation", approved_at)


def _output_paths(tmp_path: Path) -> Dict[str, Path]:
    """Return an isolated complete generation layout for runner tests."""
    root = tmp_path / "scenario_fact_generation_v1"
    return {
        "root": root,
        "config": root / "config.json",
        "approval": root / "approval.json",
        "results": root / "results",
        "cache": root / "cache",
        "logs": root / "logs",
        "assets": root / "assets",
        "checkpoints": root / "checkpoints",
    }


def test_estimate_and_approval_bind_the_exact_gpt54_batch() -> None:
    """Calculate the approved batch ceiling and reject a changed route coordinate."""
    requests = _requests()
    estimate = build_generation_estimate(requests)
    assert estimate.request_count == 30
    assert estimate.input_token_estimate == 41757
    assert estimate.output_token_ceiling == 61440
    assert estimate.estimated_max_cost == Decimal("1.04")
    approval = _approval(requests)
    with pytest.raises(ValueError, match="hash"):
        ScenarioGenerationApproval.model_validate({**approval.model_dump(mode="json"), "model_slug": "another/model"})


def test_generation_retains_malformed_semantic_output_and_resumes_without_new_calls(tmp_path: Path) -> None:
    """Keep one malformed response, generate the other 29, and reuse all semantic caches."""
    requests = _requests()
    approval = _approval(requests)
    client = FakeGenerationClient(malformed_scenario_id=requests[0].scenario_id)
    paths = _output_paths(tmp_path)
    generated_outputs = tmp_path / "generated_outputs.jsonl"
    first = run_scenario_generation(requests, approval, client, generated_outputs, paths)
    assert first.semantic_response_count == 30
    assert first.valid_output_count == 29
    assert first.invalid_output_count == 1
    assert client.call_count == 31
    assert len(read_jsonl(generated_outputs)) == 29
    second = run_scenario_generation(requests, approval, client, generated_outputs, paths)
    assert second.valid_output_count == 29
    assert client.call_count == 31
