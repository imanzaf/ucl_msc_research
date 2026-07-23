"""Orchestrate versioned scenario generation, review, revision, and acceptance gates."""

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
    required_automated_review_kinds,
)
from src.data_models.scenarios import CandidateScenario, ReplicationSeed, UseCaseSeed


class ScenarioPipelineBackend(Protocol):
    """Define model-backed generation and review operations without hard-coding a provider."""

    def generate_candidate(self, use_case: UseCaseSeed, replication: ReplicationSeed) -> CandidateScenario:
        """Generate source, facts, calculations, and minimal response in one call."""
        ...

    def review_candidate_quality(self, candidate: CandidateScenario) -> AutomatedScenarioReview:
        """Review one candidate's construct, finance, arithmetic, and source quality."""
        ...

    def review_batch_diversity(
        self,
        candidates: List[CandidateScenario],
        fixed_diversity_candidates: List[CandidateScenario],
    ) -> List[AutomatedScenarioReview]:
        """Review one R1-R4 batch once against its fixed C1 anchor."""
        ...

    def revise_candidate(
        self,
        use_case: UseCaseSeed,
        replication: ReplicationSeed,
        candidate: CandidateScenario,
        reviews: List[AutomatedScenarioReview],
        cycle_number: int,
    ) -> Tuple[CandidateScenario, List[ControlledFieldChange]]:
        """Regenerate the integrated candidate once from finding-linked feedback."""
        ...


@dataclass(frozen=True)
class ScenarioPipelineResult:
    """Return the terminal candidate, all reviews, revisions, and manual disposition."""

    candidate: CandidateScenario
    reviews: List[AutomatedScenarioReview]
    revisions: List[RevisionCycleRecord]
    terminal_decision: ReviewDecision


def _validate_review(review: AutomatedScenarioReview, candidate: CandidateScenario, expected_kind: AutomatedReviewKind) -> None:
    """Require one automated review to bind the expected candidate, hash, and contract."""
    if review.review_kind != expected_kind:
        raise ValueError("backend returned the wrong automated review kind")
    if review.scenario_id != candidate.scenario_id:
        raise ValueError("automated review scenario_id does not match candidate")
    if review.reviewed_artifact_sha256 != candidate.candidate_sha256:
        raise ValueError("automated review does not reference the current candidate hash")


def _run_batch_diversity_review(
    backend: ScenarioPipelineBackend,
    candidates: Dict[str, CandidateScenario],
    fixed_candidates: List[CandidateScenario],
) -> Dict[str, AutomatedScenarioReview]:
    """Run one shared R-batch diversity call and validate complete per-candidate coverage."""
    reviews = backend.review_batch_diversity(list(candidates.values()), fixed_candidates)
    review_by_id = {review.scenario_id: review for review in reviews}
    if len(review_by_id) != len(reviews) or set(review_by_id) != set(candidates):
        raise ValueError("batch-diversity review must return each generated candidate exactly once")
    for scenario_id, review in review_by_id.items():
        _validate_review(review, candidates[scenario_id], AutomatedReviewKind.BATCH_DIVERSITY)
    return review_by_id


def _current_reviews_for(
    scenario_id: str,
    current_reviews: Dict[str, Dict[AutomatedReviewKind, AutomatedScenarioReview]],
) -> List[AutomatedScenarioReview]:
    """Return the latest stage-relevant reviews in stable contract order."""
    required_kinds = required_automated_review_kinds(scenario_id)
    return [current_reviews[scenario_id][kind] for kind in AutomatedReviewKind if kind in required_kinds]


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
    is_calibration_batch = all(scenario_id.endswith("_C1") for scenario_id in selected_ids)
    if is_calibration_batch and fixed_candidates:
        raise ValueError("calibration generation does not use diversity anchors")
    if not is_calibration_batch and len(fixed_candidates) != 1:
        raise ValueError("evaluation generation requires one fixed C1 diversity anchor")
    candidates: Dict[str, CandidateScenario] = {}
    seeds_by_id = {replication.scenario_id: (use_case, replication) for use_case, replication in scenario_seeds}
    review_history: Dict[str, List[AutomatedScenarioReview]] = {}
    revision_history: Dict[str, List[RevisionCycleRecord]] = {}
    revision_counts: Dict[str, int] = {}
    forced_decisions: Dict[str, ReviewDecision] = {}
    for use_case, replication in scenario_seeds:
        candidates[replication.scenario_id] = backend.generate_candidate(use_case=use_case, replication=replication)
        review_history[replication.scenario_id] = []
        revision_history[replication.scenario_id] = []
        revision_counts[replication.scenario_id] = 0

    current_reviews: Dict[str, Dict[AutomatedReviewKind, AutomatedScenarioReview]] = {}
    for scenario_id, candidate in candidates.items():
        quality_review = backend.review_candidate_quality(candidate)
        _validate_review(quality_review, candidate, AutomatedReviewKind.CANDIDATE_QUALITY)
        current_reviews[scenario_id] = {AutomatedReviewKind.CANDIDATE_QUALITY: quality_review}
        review_history[scenario_id].append(quality_review)
    if not is_calibration_batch:
        diversity_by_id = _run_batch_diversity_review(backend, candidates, fixed_candidates)
        for scenario_id, diversity_review in diversity_by_id.items():
            current_reviews[scenario_id][AutomatedReviewKind.BATCH_DIVERSITY] = diversity_review
            review_history[scenario_id].append(diversity_review)

    while True:
        decisions = {scenario_id: _terminal_review_decision(_current_reviews_for(scenario_id, current_reviews)) for scenario_id in candidates}
        to_revise = [
            scenario_id for scenario_id, decision in decisions.items() if decision == ReviewDecision.REVISE and scenario_id not in forced_decisions
        ]
        if not to_revise:
            break
        rebuilt: Dict[str, Tuple[CandidateScenario, CandidateScenario, List[ControlledFieldChange], int]] = {}
        for scenario_id in to_revise:
            if revision_counts[scenario_id] >= MAX_AUTOMATED_REVISION_CYCLES:
                forced_decisions[scenario_id] = ReviewDecision.MANUAL_RESTRUCTURE
                continue
            cycle_number = revision_counts[scenario_id] + 1
            previous_candidate = candidates[scenario_id]
            use_case, replication = seeds_by_id[scenario_id]
            revised_candidate, changes = backend.revise_candidate(
                use_case,
                replication,
                previous_candidate,
                _current_reviews_for(scenario_id, current_reviews),
                cycle_number,
            )
            if not changes:
                raise ValueError("revision backend returned no controlled field changes")
            candidates[scenario_id] = revised_candidate
            revision_counts[scenario_id] = cycle_number
            rebuilt[scenario_id] = (
                previous_candidate,
                revised_candidate,
                changes,
                cycle_number,
            )
        if not rebuilt:
            break
        for scenario_id in rebuilt:
            quality_review = backend.review_candidate_quality(candidates[scenario_id])
            _validate_review(quality_review, candidates[scenario_id], AutomatedReviewKind.CANDIDATE_QUALITY)
            current_reviews[scenario_id][AutomatedReviewKind.CANDIDATE_QUALITY] = quality_review
            review_history[scenario_id].append(quality_review)
        if not is_calibration_batch:
            diversity_by_id = _run_batch_diversity_review(backend, candidates, fixed_candidates)
            for scenario_id, diversity_review in diversity_by_id.items():
                current_reviews[scenario_id][AutomatedReviewKind.BATCH_DIVERSITY] = diversity_review
                review_history[scenario_id].append(diversity_review)
        for scenario_id, rebuild in rebuilt.items():
            record = revision_record_factory(*rebuild[:3], _current_reviews_for(scenario_id, current_reviews), rebuild[3])
            if record.input_artifact_sha256 != rebuild[0].candidate_sha256 or record.output_artifact_sha256 != rebuild[1].candidate_sha256:
                raise ValueError("revision record candidate hashes do not match rebuilt artifacts")
            revision_history[scenario_id].append(record)

    results: Dict[str, ScenarioPipelineResult] = {}
    for scenario_id, candidate in candidates.items():
        decision = forced_decisions.get(scenario_id, _terminal_review_decision(_current_reviews_for(scenario_id, current_reviews)))
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
    previous_candidate: CandidateScenario,
    revised_candidate: CandidateScenario,
    changes: List[ControlledFieldChange],
    reviews: List[AutomatedScenarioReview],
    cycle_number: int,
) -> RevisionCycleRecord:
    """Build a complete revision record from rebuilt dependencies and rerun reviews."""
    from src.data_models.common import utc_now

    return RevisionCycleRecord(
        schema_version="2.0.0",
        scenario_id=revised_candidate.scenario_id,
        cycle_number=cycle_number,
        changes=changes,
        input_artifact_sha256=previous_candidate.candidate_sha256,
        output_artifact_sha256=revised_candidate.candidate_sha256,
        rebuilt_dependency_sha256={
            "numeric_registry": artifact_sha256(revised_candidate.numeric_registry),
            "source_order_a": artifact_sha256(revised_candidate.source_order_a),
            "source_order_plan": artifact_sha256(revised_candidate.source_order_plan),
            "material_facts": artifact_sha256(revised_candidate.material_facts),
            "neutral_facts": artifact_sha256(revised_candidate.neutral_facts),
            "fact_pairs": artifact_sha256(revised_candidate.fact_pairs),
            "minimal_complete_response": artifact_sha256(revised_candidate.minimal_complete_response),
        },
        rerun_review_sha256={review.review_kind: artifact_sha256(review) for review in reviews},
        completed_at=utc_now(),
    )
