"""Tests for the fixed V6 scripted-risk-follow-up conversation protocol."""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Tuple
from uuid import uuid4

import pytest

from scripts.generate_v6_scenario_drafts import load_v6_scenario_seeds
from src.data_models.experiments import (
    ConversationProtocol,
    ExperimentConfig,
    ExperimentStage,
    GenerationConfig,
    LLMCallRecord,
    LLMCallUsage,
    RunUnitIdentity,
    ScoredRunRecord,
)
from src.data_models.scenario_review import (
    PilotConversationHumanAnnotation,
    PilotExpansionStatus,
    PilotFactHumanAnnotation,
    PilotHumanAnnotationArtifact,
    ScenarioPilotExpansionGate,
    artifact_sha256,
    calculate_quadratic_weighted_kappa,
)
from src.data_models.scenarios import InteractionMode, PromptCondition, ScenarioSchemaVersion
from src.data_models.scenarios_v6 import FactEvaluationRole, ScenarioFamilyV6
from src.data_models.scoring import (
    DirectDisclosureStatus,
    DirectFactDisclosureAssessment,
    FactContradictionCheck,
    FactDisclosureJudgment,
    FactUnitMatching,
    FramingDirection,
    ResponseFactExtraction,
    ResponseMetricBreakdownV6,
)
from src.data_models.user_personas import UserPersonaId
from src.data_models.user_simulator import UserSimulatorOutcome
from src.experiments.io import append_jsonl
from src.experiments.scenario_runner import (
    V6_PILOT_AGENT_MODEL_ID,
    build_selected_run_specs,
    iter_run_specs,
    run_scenarios,
    sha256_file,
    validate_v6_pilot_expansion_gate,
)
from src.llm.openrouter import LLMCallResult
from tests.v6_scenario_fixtures import (
    make_accepted_human_review,
    make_generation_manifest,
    make_semantic_review,
    make_v6_family,
)


def fake_result(parsed: Any, stage: ExperimentStage) -> LLMCallResult[Any]:
    """Create one fake V6 runner call result."""
    return LLMCallResult(
        parsed=parsed,
        record=LLMCallRecord(
            call_id=str(uuid4()),
            stage=stage,
            model_id="fake/model",
            resolved_model_id="fake/model",
            generation_id=str(uuid4()),
            cache_key=str(uuid4()),
            cache_hit=False,
            created_at="2026-07-15T00:00:00+00:00",
            prompt_version="fixture_v1",
            request_payload={},
            response_payload={},
            parsed_output=parsed.model_dump() if hasattr(parsed, "model_dump") else None,
            text_output=parsed if isinstance(parsed, str) else None,
            usage=LLMCallUsage(),
        ),
    )


class FakeV6AgentClient:
    """Return the two agent responses required by one V6 run."""

    def __init__(self) -> None:
        """Initialize the fixed agent response queue."""
        self.responses = ["Initial assessment.", "Risk follow-up assessment."]

    def complete_text(self, **kwargs: Any) -> LLMCallResult[str]:
        """Return the next agent response."""
        return fake_result(self.responses.pop(0), kwargs["stage"])


class FakeV6OutcomeClient:
    """Allow only the post-conversation outcome call for V6."""

    def __init__(self) -> None:
        """Record structured output models requested by the runner."""
        self.output_models: List[Any] = []

    def complete_structured(self, **kwargs: Any) -> LLMCallResult[UserSimulatorOutcome]:
        """Return a user outcome and reject generated follow-up calls by assertion."""
        self.output_models.append(kwargs["output_model"])
        assert kwargs["output_model"] is UserSimulatorOutcome
        outcome = UserSimulatorOutcome(
            selected_action_id="review_plan",
            selected_belief_ids=["supported"],
            rationale="The user reviews the plan.",
        )
        return fake_result(outcome, kwargs["stage"])


def write_accepted_v6_family(root: Path, family: ScenarioFamilyV6) -> None:
    """Write one accepted no-finding V6 family and its review manifests."""
    review = make_semantic_review(family)
    generation_manifest = make_generation_manifest(family, review)
    (root / "semantic_reviews").mkdir(parents=True, exist_ok=True)
    (root / "human_reviews").mkdir(exist_ok=True)
    (root / "manifests").mkdir(exist_ok=True)
    family_id = family.scenario_family_id
    (root / f"{family_id}.json").write_text(family.model_dump_json(indent=2), encoding="utf-8")
    (root / "semantic_reviews" / f"{family_id}.json").write_text(
        review.model_dump_json(indent=2),
        encoding="utf-8",
    )
    (root / "manifests" / f"{family_id}.json").write_text(
        generation_manifest.model_dump_json(indent=2),
        encoding="utf-8",
    )
    human_review = make_accepted_human_review(family, review, generation_manifest)
    (root / "human_reviews" / f"{family_id}.json").write_text(
        human_review.model_dump_json(indent=2),
        encoding="utf-8",
    )


def write_accepted_v6_run(root: Path) -> Path:
    """Write the default accepted PFM001 V6 scenario run directory."""
    write_accepted_v6_family(root, make_v6_family())
    return root


def make_pilot_families() -> List[ScenarioFamilyV6]:
    """Build the two exact accepted families used by pilot-evidence fixtures."""
    seeds = load_v6_scenario_seeds(
        Path("data/inputs/scenarios/v0.3.1/scenario_generation_seeds.json")
    )
    return [make_v6_family(seed) for seed in seeds[:2]]


def make_omitted_direct_assessment(
    family: ScenarioFamilyV6,
    scenario_id: str,
) -> DirectFactDisclosureAssessment:
    """Create a complete all-omitted direct assessment for one pilot scenario."""
    instance = next(item for item in family.scenario_instances if item.scenario_id == scenario_id)
    return DirectFactDisclosureAssessment(
        judgments=[
            FactDisclosureJudgment(
                fact_unit_id=fact.fact_unit_id,
                checkpoint=checkpoint,
                disclosure_status=DirectDisclosureStatus.OMITTED,
                evidence_quotes=[],
                preserved_specificity_markers=[],
                framing_direction=FramingDirection.NOT_APPLICABLE,
                rationale="The fixture response omitted this fact.",
            )
            for fact in instance.fact_units
            for checkpoint in fact.expected_checkpoints
        ],
        assessment_summary="Every controlled fact was omitted.",
    )


def make_omitted_response_metrics() -> ResponseMetricBreakdownV6:
    """Create deterministic response metrics aligned with all-omitted pilot judgments."""
    return ResponseMetricBreakdownV6(
        initial_primary_omission_score=1.0,
        persistent_primary_omission_score=1.0,
        repair_rate=0.0,
        initial_understatement_rate=0.0,
        post_followup_understatement_rate=0.0,
        initial_primary_specificity_loss_score=1.0,
        favorable_control_disclosure_rate=0.0,
        neutral_control_disclosure_rate=0.0,
        unsupported_fact_rate=0.0,
        contradiction_score=0.0,
        false_claim_score=0.0,
        exploratory_equal_weight_composite=0.6,
    )


def make_pilot_run_records(families: List[ScenarioFamilyV6]) -> List[ScoredRunRecord]:
    """Create the exact two-family, three-prompt, two-persona pilot matrix."""
    records: List[ScoredRunRecord] = []
    personas = [UserPersonaId.NEUTRAL_BASELINE, UserPersonaId.ANXIOUS_RISK_AVERSE]
    for family in families:
        for instance in family.scenario_instances:
            for variant in family.prompt_variants:
                for persona_id in personas:
                    records.append(
                        ScoredRunRecord(
                            experiment_name="omission_pilot_v1",
                            scoring_run_id="20260715T120000",
                            scenario_schema_version=ScenarioSchemaVersion.V6,
                            run_unit=RunUnitIdentity(
                                scenario_family_id=family.scenario_family_id,
                                scenario_id=instance.scenario_id,
                                interaction_mode=InteractionMode.MULTI_TURN,
                                prompt_condition=variant.condition,
                                persona_id=persona_id,
                                agent_model_id=V6_PILOT_AGENT_MODEL_ID,
                                scenario_family_sha256=artifact_sha256(family),
                            ),
                            extraction=ResponseFactExtraction(extracted_facts=[]),
                            matching=FactUnitMatching(matches=[]),
                            contradiction_check=FactContradictionCheck(
                                has_fact_contradiction=False,
                                contradicted_fact_unit_ids=[],
                                fact_contradiction_rationale="No contradiction.",
                            ),
                            direct_disclosure_assessment=make_omitted_direct_assessment(
                                family,
                                instance.scenario_id,
                            ),
                            response_metrics=make_omitted_response_metrics(),
                        )
                    )
    return records


def write_pilot_evidence(root: Path) -> Tuple[List[str], str, str, str, str]:
    """Write exact pilot results and a bound human-annotation artifact."""
    families = make_pilot_families()
    for family in families:
        write_accepted_v6_family(root, family)
    records = make_pilot_run_records(families)
    evidence_dir = root / "pilot_validation"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    results_path = evidence_dir / "pilot_scoring_results.jsonl"
    results_path.write_text("", encoding="utf-8")
    append_jsonl(path=results_path, records=records)
    run_unit_ids = [record.run_unit.run_unit_id for record in records]
    families_by_id = {family.scenario_family_id: family for family in families}
    annotation_conversations = []
    for index, record in enumerate(records[:36]):
        family = families_by_id[record.run_unit.scenario_family_id]
        instance = next(
            item
            for item in family.scenario_instances
            if item.scenario_id == record.run_unit.scenario_id
        )
        judgments: List[PilotFactHumanAnnotation] = []
        for fact in instance.fact_units:
            if fact.evaluation_role != FactEvaluationRole.PRIMARY_ADVERSE_TARGET:
                continue
            for checkpoint in fact.expected_checkpoints:
                human_status = (
                    DirectDisclosureStatus.PARTIALLY_DISCLOSED
                    if index == 0 and fact.fact_unit_id == "A1"
                    else DirectDisclosureStatus.OMITTED
                )
                judgments.append(
                    PilotFactHumanAnnotation(
                        fact_unit_id=fact.fact_unit_id,
                        checkpoint=checkpoint,
                        primary_human_status=human_status,
                        secondary_human_status=human_status if index < 12 else None,
                    )
                )
        annotation_conversations.append(
            PilotConversationHumanAnnotation(
                run_unit_id=record.run_unit.run_unit_id,
                judgments=judgments,
            )
        )
    annotations_path = evidence_dir / "human_annotations.json"
    annotations_path.write_text(
        PilotHumanAnnotationArtifact(conversations=annotation_conversations).model_dump_json(
            indent=2
        ),
        encoding="utf-8",
    )
    return (
        run_unit_ids,
        "pilot_validation/pilot_scoring_results.jsonl",
        sha256_file(results_path),
        "pilot_validation/human_annotations.json",
        sha256_file(annotations_path),
    )


def make_pilot_expansion_gate(
    root: Path,
    status: PilotExpansionStatus = PilotExpansionStatus.PASSED,
) -> ScenarioPilotExpansionGate:
    """Create complete pilot-audit evidence for expansion-gate tests."""
    run_unit_ids, results_path, results_hash, annotations_path, annotations_hash = (
        write_pilot_evidence(root)
    )
    audited_ids = run_unit_ids[:36]
    return ScenarioPilotExpansionGate(
        status=status,
        pilot_family_ids=["PFM001", "RW001"],
        pilot_conversation_count=48,
        pilot_agent_model_id=V6_PILOT_AGENT_MODEL_ID,
        pilot_run_unit_ids=run_unit_ids,
        pilot_results_path=results_path,
        pilot_results_sha256=results_hash,
        human_annotations_path=annotations_path,
        human_annotations_sha256=annotations_hash,
        audited_conversation_ids=audited_ids,
        second_reviewed_conversation_ids=audited_ids[:12],
        omission_precision=1.0,
        omission_recall=1.0,
        weighted_inter_reviewer_kappa=1.0,
        assessor="Reviewer One",
        assessed_at="2026-07-15T12:00:00+01:00",
        notes="Metrics calculated from the predeclared human-audit samples.",
    )


def test_quadratic_weighted_kappa_rejects_zero_variance_agreement() -> None:
    """Verify degenerate single-category agreement cannot pass the pilot gate."""
    reviewer_pairs = [
        (DirectDisclosureStatus.OMITTED, DirectDisclosureStatus.OMITTED) for _ in range(12)
    ]

    assert calculate_quadratic_weighted_kappa(reviewer_pairs) == 0.0


def test_pilot_expansion_gate_applies_only_to_non_pilot_families(tmp_path: Path) -> None:
    """Verify pilot families run freely while expansion requires passed audit evidence."""
    validate_v6_pilot_expansion_gate(
        tmp_path,
        ["PFM001", "RW001"],
        [V6_PILOT_AGENT_MODEL_ID],
    )

    with pytest.raises(ValueError, match="requires pilot_validation"):
        validate_v6_pilot_expansion_gate(
            tmp_path,
            ["BRM001"],
            [V6_PILOT_AGENT_MODEL_ID],
        )
    with pytest.raises(ValueError, match="requires pilot_validation"):
        validate_v6_pilot_expansion_gate(
            tmp_path,
            ["PFM001", "RW001"],
            [V6_PILOT_AGENT_MODEL_ID, "fake/second-agent"],
        )
    with pytest.raises(ValueError, match="requires pilot_validation"):
        validate_v6_pilot_expansion_gate(
            tmp_path,
            ["PFM001", "RW001"],
            ["qwen/qwen-2.5-72b-instruct"],
        )

    manifest_path = tmp_path / "pilot_validation" / "manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        make_pilot_expansion_gate(tmp_path, PilotExpansionStatus.PENDING).model_dump_json(indent=2),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="not passed: pending"):
        validate_v6_pilot_expansion_gate(
            tmp_path,
            ["BRM001"],
            [V6_PILOT_AGENT_MODEL_ID],
        )

    manifest_path.write_text(
        make_pilot_expansion_gate(tmp_path).model_dump_json(indent=2),
        encoding="utf-8",
    )
    validate_v6_pilot_expansion_gate(
        tmp_path,
        ["PFM001", "BRM001"],
        [V6_PILOT_AGENT_MODEL_ID, "fake/second-agent"],
    )


def test_passed_pilot_gate_rejects_subthreshold_metrics(tmp_path: Path) -> None:
    """Verify a passed status cannot override any predeclared metric threshold."""
    payload = make_pilot_expansion_gate(tmp_path).model_dump()
    payload["omission_precision"] = 0.79
    with pytest.raises(ValueError, match="meet every expansion threshold"):
        ScenarioPilotExpansionGate.model_validate(payload)


def test_passed_pilot_gate_rejects_changed_evidence_artifact(tmp_path: Path) -> None:
    """Verify expansion remains bound to the exact human-annotation artifact."""
    manifest_path = tmp_path / "pilot_validation" / "manifest.json"
    manifest = make_pilot_expansion_gate(tmp_path)
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    annotations_path = tmp_path / manifest.human_annotations_path
    annotations_path.write_text("changed", encoding="utf-8")

    with pytest.raises(ValueError, match="artifact hash mismatch"):
        validate_v6_pilot_expansion_gate(
            tmp_path,
            ["BRM001"],
            ["fake/second-agent"],
        )


def test_passed_pilot_gate_recomputes_metrics_from_annotations(tmp_path: Path) -> None:
    """Verify a rehashed annotation edit cannot preserve unsupported reported metrics."""
    manifest_path = tmp_path / "pilot_validation" / "manifest.json"
    manifest = make_pilot_expansion_gate(tmp_path)
    annotations_path = tmp_path / manifest.human_annotations_path
    annotations = PilotHumanAnnotationArtifact.model_validate_json(
        annotations_path.read_text(encoding="utf-8")
    )
    annotations.conversations[0].judgments[
        0
    ].primary_human_status = DirectDisclosureStatus.DISCLOSED
    annotations_path.write_text(annotations.model_dump_json(indent=2), encoding="utf-8")
    manifest.human_annotations_sha256 = sha256_file(annotations_path)
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

    with pytest.raises(ValueError, match="does not match annotation recomputation"):
        validate_v6_pilot_expansion_gate(
            tmp_path,
            ["BRM001"],
            ["fake/second-agent"],
        )


def test_v6_run_matrix_uses_only_neutral_and_anxious_personas() -> None:
    """Verify one V6 family produces 24 runs per model with no positive persona."""
    family = make_v6_family()
    specs = list(iter_run_specs(families=[family], agent_model_ids=["fake/agent"]))

    assert len(specs) == 4 * 3 * 2
    assert {spec[3] for spec in specs} == {
        UserPersonaId.NEUTRAL_BASELINE,
        UserPersonaId.ANXIOUS_RISK_AVERSE,
    }
    with pytest.raises(ValueError, match="V6 does not run"):
        list(
            iter_run_specs(
                families=[family],
                agent_model_ids=["fake/agent"],
                persona_ids=[UserPersonaId.POSITIVE_RISK_SEEKING.value],
            )
        )


def test_run_identity_changes_with_exact_scenario_family_artifact() -> None:
    """Verify changed family content cannot collide when scenario IDs are reused."""
    original_family = make_v6_family()
    changed_payload = original_family.model_dump()
    changed_payload["scenario_instances"][0]["generated_summary"] = "Changed family content."
    changed_family = ScenarioFamilyV6.model_validate(changed_payload)

    original_spec = build_selected_run_specs(
        families=[original_family],
        agent_model_ids=["fake/agent"],
        skip_ids=[],
        prompt_conditions=[PromptCondition.NEUTRAL.value],
        persona_ids=[UserPersonaId.NEUTRAL_BASELINE.value],
        limit=1,
    )[0]
    changed_spec = build_selected_run_specs(
        families=[changed_family],
        agent_model_ids=["fake/agent"],
        skip_ids=[],
        prompt_conditions=[PromptCondition.NEUTRAL.value],
        persona_ids=[UserPersonaId.NEUTRAL_BASELINE.value],
        limit=1,
    )[0]

    assert original_spec.instance.scenario_id == changed_spec.instance.scenario_id
    assert original_spec.unit_id != changed_spec.unit_id


def test_v6_runner_uses_exactly_one_scripted_risk_followup(tmp_path: Path) -> None:
    """Verify V6 uses two agent calls and no generated user-simulator turn call."""
    scenario_run_dir = write_accepted_v6_run(tmp_path / "scenario-run")
    family = make_v6_family()
    scenario = family.scenario_instances[0]
    agent_client = FakeV6AgentClient()
    outcome_client = FakeV6OutcomeClient()
    config = ExperimentConfig(
        experiment_name="v6_scripted_smoke_v1",
        scenario_run_dir=str(scenario_run_dir),
        agent_model_ids=[V6_PILOT_AGENT_MODEL_ID],
        user_simulator_model="fake/user",
        scoring_model="fake/scorer",
        generation_config=GenerationConfig(),
        max_followup_turns=3,
    )

    records = run_scenarios(
        agent_client=agent_client,
        user_simulator_client=outcome_client,
        experiment_root=tmp_path,
        experiment_config=config,
        scenario_family_ids=["PFM001"],
        scenario_ids=[scenario.scenario_id],
        prompt_conditions=["neutral"],
        persona_ids=["anxious_risk_averse"],
        run_id="20260715T121212",
        limit=1,
    )

    record = records[0]
    assert record.conversation_protocol == ConversationProtocol.SCRIPTED_RISK_FOLLOWUP_V1
    assert record.transcript_turn_count == 4
    assert record.generated_user_followup_count == 0
    assert record.scripted_user_followup_count == 1
    assert record.user_simulator_decision_count == 0
    assert record.transcript[0].content == f"I'm feeling worried. {scenario.core_initial_request}"
    assert record.transcript[2].content == f"I'm feeling worried. {scenario.core_risk_followup}"
    assert outcome_client.output_models == [UserSimulatorOutcome]
