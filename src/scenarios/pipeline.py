"""Orchestrate the staged V0.5.1 generation, review, revision, and acceptance gates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Protocol, Tuple

from src.data_models.common import artifact_sha256
from src.data_models.scenario_review import (
    MAX_AUTOMATED_REVISION_CYCLES,
    AutomatedReviewKind,
    AutomatedScenarioReview,
    ControlledFieldChange,
    ReviewDecision,
    RevisionCycleRecord,
)
from src.data_models.scenarios import CandidateScenario, NumericRegistry, ReplicationSeed, ScenarioBlueprint, UseCaseSeed
from src.scenarios.numeric_engine import compute_numeric_registry


class ScenarioPipelineBackend(Protocol):
    """Define model-backed generation and review operations without hard-coding a provider."""

    def generate_blueprint(self, use_case: UseCaseSeed, replication: ReplicationSeed) -> ScenarioBlueprint:
        """Generate one typed scenario blueprint."""
        ...

    def build_candidate(self, blueprint: ScenarioBlueprint, numeric_registry: NumericRegistry) -> CandidateScenario:
        """Render sources, manifests, and the minimal complete response from a blueprint."""
        ...

    def review_candidate(
        self,
        candidate: CandidateScenario,
        review_kind: AutomatedReviewKind,
        use_case_batch: List[CandidateScenario],
    ) -> AutomatedScenarioReview:
        """Run one independent typed automated review contract."""
        ...

    def revise_blueprint(
        self,
        blueprint: ScenarioBlueprint,
        candidate: CandidateScenario,
        reviews: List[AutomatedScenarioReview],
        cycle_number: int,
    ) -> Tuple[ScenarioBlueprint, List[ControlledFieldChange]]:
        """Apply only finding-linked field-level revisions to the blueprint."""
        ...


@dataclass(frozen=True)
class ScenarioPipelineResult:
    """Return the terminal candidate, all reviews, revisions, and manual disposition."""

    candidate: CandidateScenario
    reviews: List[AutomatedScenarioReview]
    revisions: List[RevisionCycleRecord]
    terminal_decision: ReviewDecision


def _run_all_reviews(
    backend: ScenarioPipelineBackend,
    candidate: CandidateScenario,
    use_case_batch: List[CandidateScenario],
) -> List[AutomatedScenarioReview]:
    """Run construct, finance/arithmetic, and batch-diversity reviews independently."""
    reviews = [backend.review_candidate(candidate, review_kind, use_case_batch) for review_kind in AutomatedReviewKind]
    if {review.review_kind for review in reviews} != set(AutomatedReviewKind):
        raise ValueError("backend did not return every required review kind")
    if any(review.scenario_id != candidate.scenario_id for review in reviews):
        raise ValueError("automated review scenario_id does not match candidate")
    if any(review.reviewed_artifact_sha256 != candidate.candidate_sha256 for review in reviews):
        raise ValueError("automated review does not reference the current candidate hash")
    return reviews


def _terminal_review_decision(reviews: List[AutomatedScenarioReview]) -> ReviewDecision:
    """Combine independent reviews conservatively without averaging blockers away."""
    decisions = {review.decision for review in reviews}
    if ReviewDecision.REJECT in decisions:
        return ReviewDecision.REJECT
    if ReviewDecision.MANUAL_RESTRUCTURE in decisions:
        return ReviewDecision.MANUAL_RESTRUCTURE
    if ReviewDecision.REVISE in decisions:
        return ReviewDecision.REVISE
    return ReviewDecision.ACCEPT


def run_scenario_batch_pipeline(
    scenario_seeds: List[Tuple[UseCaseSeed, ReplicationSeed]],
    backend: ScenarioPipelineBackend,
    revision_record_factory: Callable[
        [
            ScenarioBlueprint,
            ScenarioBlueprint,
            CandidateScenario,
            CandidateScenario,
            List[ControlledFieldChange],
            List[AutomatedScenarioReview],
            int,
        ],
        RevisionCycleRecord,
    ],
    fixed_diversity_candidates: Optional[List[CandidateScenario]] = None,
) -> Dict[str, ScenarioPipelineResult]:
    """Generate one lifecycle-stage batch while retaining any frozen C1 diversity anchors.

    Args:
        scenario_seeds: Researcher-owned use-case and replication pairs for one lifecycle stage.
        backend: Typed generation, review, and controlled-revision implementation.
        revision_record_factory: Builder for complete dependency-rebuild audit records.
        fixed_diversity_candidates: Frozen C1 anchors included only in evaluation diversity review.
    """
    if not scenario_seeds:
        raise ValueError("scenario batch cannot be empty")
    fixed_candidates = fixed_diversity_candidates or []
    selected_ids = [replication.scenario_id for _, replication in scenario_seeds]
    if len(selected_ids) != len(set(selected_ids)):
        raise ValueError("scenario batch contains duplicate identifiers")
    if set(selected_ids) & {candidate.scenario_id for candidate in fixed_candidates}:
        raise ValueError("fixed diversity candidates cannot also be regenerated")
    blueprints: Dict[str, ScenarioBlueprint] = {}
    candidates: Dict[str, CandidateScenario] = {}
    review_history: Dict[str, List[AutomatedScenarioReview]] = {}
    revision_history: Dict[str, List[RevisionCycleRecord]] = {}
    revision_counts: Dict[str, int] = {}
    forced_decisions: Dict[str, ReviewDecision] = {}
    for use_case, replication in scenario_seeds:
        blueprint = backend.generate_blueprint(use_case=use_case, replication=replication)
        numeric_registry = compute_numeric_registry(blueprint.numeric_inputs, blueprint.numeric_calculations)
        blueprints[replication.scenario_id] = blueprint
        candidates[replication.scenario_id] = backend.build_candidate(blueprint, numeric_registry)
        review_history[replication.scenario_id] = []
        revision_history[replication.scenario_id] = []
        revision_counts[replication.scenario_id] = 0

    batch = [*fixed_candidates, *candidates.values()]
    current_reviews = {scenario_id: _run_all_reviews(backend, candidate, batch) for scenario_id, candidate in candidates.items()}
    for scenario_id, reviews in current_reviews.items():
        review_history[scenario_id].extend(reviews)

    while True:
        decisions = {scenario_id: _terminal_review_decision(reviews) for scenario_id, reviews in current_reviews.items()}
        to_revise = [
            scenario_id for scenario_id, decision in decisions.items() if decision == ReviewDecision.REVISE and scenario_id not in forced_decisions
        ]
        if not to_revise:
            break
        rebuilt: Dict[
            str,
            Tuple[ScenarioBlueprint, ScenarioBlueprint, CandidateScenario, CandidateScenario, List[ControlledFieldChange], int],
        ] = {}
        for scenario_id in to_revise:
            if revision_counts[scenario_id] >= MAX_AUTOMATED_REVISION_CYCLES:
                forced_decisions[scenario_id] = ReviewDecision.MANUAL_RESTRUCTURE
                continue
            cycle_number = revision_counts[scenario_id] + 1
            previous_blueprint = blueprints[scenario_id]
            previous_candidate = candidates[scenario_id]
            revised_blueprint, changes = backend.revise_blueprint(
                previous_blueprint,
                previous_candidate,
                current_reviews[scenario_id],
                cycle_number,
            )
            if not changes:
                raise ValueError("revision backend returned no controlled field changes")
            numeric_registry = compute_numeric_registry(revised_blueprint.numeric_inputs, revised_blueprint.numeric_calculations)
            revised_candidate = backend.build_candidate(revised_blueprint, numeric_registry)
            blueprints[scenario_id] = revised_blueprint
            candidates[scenario_id] = revised_candidate
            revision_counts[scenario_id] = cycle_number
            rebuilt[scenario_id] = (
                previous_blueprint,
                revised_blueprint,
                previous_candidate,
                revised_candidate,
                changes,
                cycle_number,
            )
        if not rebuilt:
            break
        batch = [*fixed_candidates, *candidates.values()]
        current_reviews = {scenario_id: _run_all_reviews(backend, candidate, batch) for scenario_id, candidate in candidates.items()}
        for scenario_id, reviews in current_reviews.items():
            review_history[scenario_id].extend(reviews)
        for scenario_id, rebuild in rebuilt.items():
            record = revision_record_factory(*rebuild[:5], current_reviews[scenario_id], rebuild[5])
            if record.input_artifact_sha256 != rebuild[2].candidate_sha256 or record.output_artifact_sha256 != rebuild[3].candidate_sha256:
                raise ValueError("revision record candidate hashes do not match rebuilt artifacts")
            revision_history[scenario_id].append(record)

    results: Dict[str, ScenarioPipelineResult] = {}
    for scenario_id, candidate in candidates.items():
        decision = forced_decisions.get(scenario_id, _terminal_review_decision(current_reviews[scenario_id]))
        if decision == ReviewDecision.REVISE:
            decision = ReviewDecision.MANUAL_RESTRUCTURE
        results[scenario_id] = ScenarioPipelineResult(
            candidate=candidate,
            reviews=review_history[scenario_id],
            revisions=revision_history[scenario_id],
            terminal_decision=decision,
        )
    return results


def default_revision_record_factory(
    previous_blueprint: ScenarioBlueprint,
    revised_blueprint: ScenarioBlueprint,
    previous_candidate: CandidateScenario,
    revised_candidate: CandidateScenario,
    changes: List[ControlledFieldChange],
    reviews: List[AutomatedScenarioReview],
    cycle_number: int,
) -> RevisionCycleRecord:
    """Build a complete revision record from rebuilt dependencies and rerun reviews."""
    from src.data_models.common import utc_now

    return RevisionCycleRecord(
        schema_version="1.0.0",
        scenario_id=revised_candidate.scenario_id,
        cycle_number=cycle_number,
        changes=changes,
        input_artifact_sha256=previous_candidate.candidate_sha256,
        output_artifact_sha256=revised_candidate.candidate_sha256,
        rebuilt_dependency_sha256={
            "blueprint": artifact_sha256(revised_blueprint),
            "numeric_registry": artifact_sha256(revised_candidate.numeric_registry),
            "source_order_a": artifact_sha256(revised_candidate.source_order_a),
            "source_order_b": artifact_sha256(revised_candidate.source_order_b),
            "material_facts": artifact_sha256(revised_candidate.material_facts),
            "neutral_facts": artifact_sha256(revised_candidate.neutral_facts),
            "minimal_complete_response": artifact_sha256(revised_candidate.minimal_complete_response),
        },
        rerun_review_sha256={review.review_kind: artifact_sha256(review) for review in reviews},
        completed_at=utc_now(),
    )
