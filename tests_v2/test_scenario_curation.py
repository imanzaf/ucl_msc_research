"""Researcher-approved corpus curation and provenance tests."""

from __future__ import annotations

import pytest

from srcv2.common import artifact_sha256, utc_now
from srcv2.models.scenarios import AcceptedScenario
from srcv2.models.seeds import ScenarioSeedSet
from srcv2.paths import SCENARIO_ROOT
from srcv2.scenarios.curation import assemble_curated_pending_corpus, build_curation_approval
from srcv2.scenarios.generation import GeneratedScenarioOutput, GenerationRequest
from srcv2.scenarios.validation import audit_accepted_scenarios
from srcv2.storage import read_json, read_jsonl


def _source_artifacts() -> tuple[ScenarioSeedSet, list[GeneratedScenarioOutput], list[GenerationRequest], dict[str, object]]:
    """Load the exact source artifacts and approved manual-review proposal."""
    seed_set = ScenarioSeedSet.model_validate(read_json(SCENARIO_ROOT / "scenario_generation_seeds.json"))
    outputs = [GeneratedScenarioOutput.model_validate(record) for record in read_jsonl(SCENARIO_ROOT / "generated_outputs.jsonl")]
    requests = [GenerationRequest.model_validate(record) for record in read_jsonl(SCENARIO_ROOT / "generation_requests.jsonl")]
    audit = read_json(SCENARIO_ROOT / "manual_review_audit.json")
    return seed_set, outputs, requests, audit


def test_approved_curation_applies_exact_edits_and_preserves_generation_hashes() -> None:
    """Apply all approved edits while retaining original generation-request provenance."""
    seed_set, outputs, requests, audit = _source_artifacts()
    approval = build_curation_approval(seed_set, outputs, requests, audit, "test researcher", "approve reviewed corrections", utc_now())
    assert len(approval.fact_text_edits) == 27
    assert len(approval.context_edits) == 1
    assert len(approval.brief_edits) == 5
    assert len(approval.anchor_edits) == 1
    curated_seed_set, curated_outputs, scenarios = assemble_curated_pending_corpus(seed_set, outputs, requests, approval)
    assert len(curated_outputs) == 30
    assert audit_accepted_scenarios(scenarios).passed
    assert "3% of each month’s opening balance or £5" in curated_seed_set.use_cases[1].replications[0].decision_context
    expected_hashes = {request.scenario_id: request.request_sha256 for request in requests}
    assert all(scenario.generation_request_sha256 == expected_hashes[scenario.scenario_id] for scenario in scenarios)
    by_scenario: dict[str, AcceptedScenario] = {scenario.scenario_id: scenario for scenario in scenarios}
    assert "£95,005" in next(fact.text for fact in by_scenario["CF101_R4"].facts if fact.fact_id == "CF101_R4_F6")
    assert next(fact.anchor for fact in by_scenario["CF106_R1"].facts if fact.fact_id == "CF106_R1_F6") == "£237.50 lower charges"


def test_curation_rejects_a_changed_source_output() -> None:
    """Refuse to apply approved edits after any source generated output changes."""
    seed_set, outputs, requests, audit = _source_artifacts()
    approval = build_curation_approval(seed_set, outputs, requests, audit, "test researcher", "approve reviewed corrections", utc_now())
    changed = outputs.copy()
    changed_fact = changed[0].facts[0].model_copy(update={"text": f"{changed[0].facts[0].text} Altered."})
    changed[0] = changed[0].model_copy(update={"facts": [changed_fact, *changed[0].facts[1:]]})
    with pytest.raises(ValueError, match="different generated outputs"):
        assemble_curated_pending_corpus(seed_set, changed, requests, approval)
    assert artifact_sha256(seed_set) == approval.source_seed_sha256
