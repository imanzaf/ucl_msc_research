"""Deterministic arithmetic, exact spans, rebuild reviews, and revision-cap tests."""

from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

import pytest

from src.data_models.common import artifact_sha256, utc_now
from src.data_models.scenario_review import (
    AutomatedReviewKind,
    AutomatedScenarioReview,
    ControlledFieldChange,
    FindingSeverity,
    ReviewDecision,
    ReviewFinding,
)
from src.data_models.scenarios import (
    ArtifactProvenance,
    CandidateScenario,
    FactBlueprint,
    FactValence,
    NeutralFactBlueprint,
    NumericCalculation,
    NumericInput,
    NumericOperation,
    NumericRegistry,
    ReplicationSeed,
    ScenarioBlueprint,
    ScenarioStage,
    UseCaseSeed,
)
from src.scenarios.numeric_engine import compute_numeric_registry
from src.scenarios.pipeline import default_revision_record_factory, run_scenario_batch_pipeline
from src.scenarios.seed_validation import load_and_validate_seed
from src.scenarios.source_rendering import validate_evidence_span
from tests.factories import ZERO_HASH, make_accepted_scenario, make_candidate_scenario

REPO_ROOT = Path(__file__).resolve().parents[1]


def make_blueprint() -> ScenarioBlueprint:
    """Build one valid typed blueprint for pipeline orchestration tests."""
    material = [
        FactBlueprint(
            fact_id=f"CF001_R1_F{index}",
            pair_id=f"CF001_R1_P{1 if index < 3 else 2}",
            valence=FactValence.ADVERSE if index in {1, 3} else FactValence.FAVOURABLE,
            proposition_template=f"Fact {index}",
            materiality_rationale="Decision material.",
            numeric_value_ids=[],
            intended_source_section=f"section_{index}",
        )
        for index in range(1, 5)
    ]
    neutral = [
        NeutralFactBlueprint(
            fact_id=f"CF001_R1_N{index}",
            proposition_template=f"Neutral {index}",
            neutral_status_rationale="Lower priority.",
            numeric_value_ids=[],
            intended_source_section=f"neutral_{index}",
        )
        for index in range(1, 3)
    ]
    return ScenarioBlueprint(
        schema_version="1.0.0",
        scenario_id="CF001_R1",
        use_case_id="CF001",
        study_stage=ScenarioStage.EVALUATION,
        fictional_entities=["Example Bank"],
        time_period="August 2026",
        customer_decision_context="Compare two fictional options.",
        variation_summary="Initial",
        material_facts=material,
        neutral_facts=neutral,
        numeric_inputs=[],
        numeric_calculations=[],
        source_section_order=["section_1", "section_2"],
        provenance=ArtifactProvenance(created_at=utc_now(), created_by="test"),
    )


class AlwaysReviseBackend:
    """Fake backend that proves all reviews rerun until the three-cycle cap."""

    def __init__(self) -> None:
        """Create a backend with a stable accepted-scenario-derived candidate."""
        self.candidate = make_candidate_scenario()

    def generate_blueprint(self, use_case: UseCaseSeed, replication: ReplicationSeed) -> ScenarioBlueprint:
        """Return the fixture blueprint."""
        return make_blueprint()

    def build_candidate(self, blueprint: ScenarioBlueprint, numeric_registry: NumericRegistry) -> CandidateScenario:
        """Return the rebuilt fixture candidate."""
        payload = self.candidate.model_dump(mode="json", exclude={"candidate_sha256"})
        payload["numeric_registry"] = numeric_registry.model_dump(mode="json")
        return CandidateScenario.model_validate({**payload, "candidate_sha256": artifact_sha256(payload)})

    def review_candidate(
        self,
        candidate: CandidateScenario,
        review_kind: AutomatedReviewKind,
        use_case_batch: List[CandidateScenario],
    ) -> AutomatedScenarioReview:
        """Return one finding so every review requests another revision."""
        finding = ReviewFinding(
            finding_id=f"{review_kind.value.upper()}_1",
            severity=FindingSeverity.MAJOR,
            artifact_path="candidate.json",
            field_path="variation_summary",
            message="Needs revision.",
            evidence="Fixture evidence.",
            suggested_action="Revise the field.",
        )
        return AutomatedScenarioReview(
            schema_version="1.0.0",
            scenario_id=candidate.scenario_id,
            review_kind=review_kind,
            decision=ReviewDecision.REVISE,
            findings=[finding],
            reviewed_artifact_sha256=candidate.candidate_sha256,
            reviewer_model_id="independent/reviewer",
            reviewer_prompt_sha256=ZERO_HASH,
            reviewed_at=utc_now(),
        )

    def revise_blueprint(
        self,
        blueprint: ScenarioBlueprint,
        candidate: CandidateScenario,
        reviews: List[AutomatedScenarioReview],
        cycle_number: int,
    ) -> Tuple[ScenarioBlueprint, List[ControlledFieldChange]]:
        """Change one field and return a controlled revision record input."""
        revised = blueprint.model_copy(update={"variation_summary": f"Revision {cycle_number}"})
        return revised, [
            ControlledFieldChange(
                field_path="variation_summary",
                previous_value_sha256=ZERO_HASH,
                revised_value_sha256=ZERO_HASH,
                reason="Resolve all fixture findings.",
                finding_ids=[finding.finding_id for review in reviews for finding in review.findings],
            )
        ]


class BatchAcceptBackend:
    """Accept candidates while recording the batch shown to every diversity review."""

    def __init__(self) -> None:
        """Initialise observed batch membership."""
        self.observed_batches: List[List[str]] = []

    def generate_blueprint(self, use_case: UseCaseSeed, replication: ReplicationSeed) -> ScenarioBlueprint:
        """Return a lightweight blueprint carrying the requested replication identity."""
        stage = ScenarioStage.CALIBRATION if replication.scenario_id.endswith("_C1") else ScenarioStage.EVALUATION
        return make_blueprint().model_copy(update={"scenario_id": replication.scenario_id, "use_case_id": use_case.use_case_id, "study_stage": stage})

    def build_candidate(self, blueprint: ScenarioBlueprint, numeric_registry: NumericRegistry) -> CandidateScenario:
        """Build a valid candidate for the requested replication."""
        return make_candidate_scenario(blueprint.scenario_id)

    def review_candidate(
        self,
        candidate: CandidateScenario,
        review_kind: AutomatedReviewKind,
        use_case_batch: List[CandidateScenario],
    ) -> AutomatedScenarioReview:
        """Record the complete comparison batch and accept the candidate."""
        if review_kind == AutomatedReviewKind.BATCH_DIVERSITY:
            self.observed_batches.append(sorted(item.scenario_id for item in use_case_batch))
        return AutomatedScenarioReview(
            schema_version="1.0.0",
            scenario_id=candidate.scenario_id,
            review_kind=review_kind,
            decision=ReviewDecision.ACCEPT,
            findings=[],
            reviewed_artifact_sha256=candidate.candidate_sha256,
            reviewer_model_id="independent/reviewer",
            reviewer_prompt_sha256=ZERO_HASH,
            reviewed_at=utc_now(),
        )

    def revise_blueprint(
        self,
        blueprint: ScenarioBlueprint,
        candidate: CandidateScenario,
        reviews: List[AutomatedScenarioReview],
        cycle_number: int,
    ) -> Tuple[ScenarioBlueprint, List[ControlledFieldChange]]:
        """Reject an impossible revision call in this accepting fixture."""
        raise AssertionError("accepted candidates must not enter revision")


def test_numeric_engine_uses_decimal_and_rejects_division_by_zero() -> None:
    """Compute registered arithmetic once and fail loudly on invalid operations."""
    inputs = [
        NumericInput(value_id="OLD", value="100", unit="GBP", source_note="fixture"),
        NumericInput(value_id="NEW", value="125", unit="GBP", source_note="fixture"),
    ]
    calculation = NumericCalculation(
        output_value_id="CHANGE",
        operation=NumericOperation.PERCENTAGE_CHANGE,
        operand_value_ids=["OLD", "NEW"],
        decimal_places=1,
        expected_unit="percent",
    )
    registry = compute_numeric_registry(inputs, [calculation])
    assert str(registry.computed_values[0].value) == "25.0"
    zero = NumericInput(value_id="ZERO", value="0", unit="GBP", source_note="fixture")
    divide = NumericCalculation(
        output_value_id="BAD",
        operation=NumericOperation.DIVIDE,
        operand_value_ids=["OLD", "ZERO"],
        expected_unit="ratio",
    )
    with pytest.raises(ValueError, match="division by zero"):
        compute_numeric_registry([inputs[0], zero], [divide])


def test_exact_source_span_validation() -> None:
    """Reject a support span whose character bounds do not reproduce exact text."""
    scenario = make_accepted_scenario()
    item_by_id = {item.source_item_id: item for item in scenario.source_order_a.items}
    valid = scenario.material_facts[0].source_support[0]
    validate_evidence_span(valid, item_by_id)
    invalid = valid.model_copy(update={"exact_text": "wrong text", "end_char": len("wrong text")})
    with pytest.raises(ValueError, match="invalid exact evidence span"):
        validate_evidence_span(invalid, item_by_id)


def test_pipeline_reruns_all_reviews_and_caps_revision_at_three() -> None:
    """Stop unresolved automation after three complete rebuild/review cycles."""
    seed_root = REPO_ROOT / "data/inputs/scenarios/v0.5.1"
    seed = load_and_validate_seed(seed_root / "scenario_generation_seeds.json", seed_root / "scenario_generation_seed_schema.json")
    use_case = seed.use_cases[0]
    replication = next(item for item in use_case.replications if item.scenario_id == "CF001_R1")
    result = run_scenario_batch_pipeline(
        [(use_case, replication)],
        AlwaysReviseBackend(),
        default_revision_record_factory,
    )[replication.scenario_id]

    assert result.terminal_decision == ReviewDecision.MANUAL_RESTRUCTURE
    assert len(result.revisions) == 3
    assert len(result.reviews) == 12
    assert all(set(record.rerun_review_sha256) == set(AutomatedReviewKind) for record in result.revisions)


def test_batch_diversity_review_receives_all_five_use_case_candidates() -> None:
    """Make the diversity contract compare C1 and R1-R4 together, never one candidate alone."""
    seed_root = REPO_ROOT / "data/inputs/scenarios/v0.5.1"
    seed = load_and_validate_seed(seed_root / "scenario_generation_seeds.json", seed_root / "scenario_generation_seed_schema.json")
    backend = BatchAcceptBackend()
    use_case = seed.use_cases[0]
    calibration_seed = next(item for item in use_case.replications if item.scenario_id.endswith("_C1"))
    calibration_blueprint = backend.generate_blueprint(use_case, calibration_seed)
    calibration_candidate = backend.build_candidate(
        calibration_blueprint,
        compute_numeric_registry(calibration_blueprint.numeric_inputs, calibration_blueprint.numeric_calculations),
    )
    evaluation_seeds = [(use_case, item) for item in use_case.replications if not item.scenario_id.endswith("_C1")]
    results = run_scenario_batch_pipeline(
        evaluation_seeds,
        backend,
        default_revision_record_factory,
        fixed_diversity_candidates=[calibration_candidate],
    )
    expected_ids = {"CF001_C1", "CF001_R1", "CF001_R2", "CF001_R3", "CF001_R4"}
    assert set(results) == expected_ids - {"CF001_C1"}
    assert len(backend.observed_batches) == 4
    assert all(set(batch) == expected_ids for batch in backend.observed_batches)
