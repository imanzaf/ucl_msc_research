"""Run lifecycle-ordered C1 or C1-anchored R1-R2 scenario generation."""

from __future__ import annotations

import argparse
import importlib
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple, cast

from src.data_models.common import artifact_sha256, sha256_bytes, utc_now, validate_model_self_hash
from src.data_models.manifests import FreezeStatus, TightLimitManifest
from src.data_models.scenario_review import (
    AutomatedReviewKind,
    AutomatedScenarioReview,
    ControlledFieldChange,
    FindingSeverity,
    ResearcherScenarioReview,
    ReviewDecision,
    ReviewFinding,
    RevisionCycleRecord,
    ScenarioPipelineDisposition,
    ScenarioPipelineFailureRecord,
)
from src.data_models.scenarios import (
    CandidateScenario,
    ScenarioGenerationInvocationConfig,
    ScenarioGenerationRunConfig,
    ScenarioStage,
    V11ReplicationSeed,
    V11UseCaseSeed,
)
from src.paths import (
    ACTIVE_SCENARIO_GENERATION_ROOT,
    ACTIVE_SCENARIO_GENERATION_VERSION,
    ACTIVE_SCENARIO_INPUT_ROOT,
    ACTIVE_SCENARIO_SEED_SCHEMA_SHA256,
    ACTIVE_SCENARIO_SEED_SHA256,
    ACTIVE_SCENARIO_SEED_VERSION,
    ACTIVE_SCENARIO_SET_ID,
    scenario_generation_round_id,
    scenario_generation_run_root,
)
from src.prompts.scenario_generation import SCENARIO_REVIEW_SYSTEM_PROMPT
from src.scenarios.budgets import material_fact_text_sha256, material_fact_word_count
from src.scenarios.pipeline import ScenarioPipelineBackend, ScenarioPipelineResult, default_revision_record_factory, run_scenario_batch_pipeline
from src.scenarios.run_resolution import current_researcher_review, current_scenario_artifacts, reviews_by_artifact_hash, scenario_round_roots
from src.scenarios.seed_validation import load_and_validate_seed
from src.storage import read_model_json, read_model_jsonl, write_model_json_atomic, write_models_jsonl_atomic

RESEARCHER_REVISION_CONTRACT_SHA256 = sha256_bytes(b"researcher_directed_scenario_revision_v1")


def _load_backend(specification: str, invocation_root: Path) -> ScenarioPipelineBackend:
    """Load a backend factory and scope its provider logs to this invocation."""
    module_name, separator, attribute_name = specification.partition(":")
    if not separator:
        raise ValueError("backend must use module:attribute syntax")
    return cast(ScenarioPipelineBackend, getattr(importlib.import_module(module_name), attribute_name)(invocation_root))


def _select_stage_seeds(
    use_cases: List[V11UseCaseSeed],
    stage: ScenarioStage,
    use_case_id: Optional[str],
    scenario_id: Optional[str],
) -> List[Tuple[V11UseCaseSeed, V11ReplicationSeed]]:
    """Select a complete lifecycle batch or one exact scenario without crossing stages."""
    stage_seeds = [
        (use_case, replication)
        for use_case in use_cases
        for replication in use_case.replications
        if (replication.scenario_id.endswith("_C1")) == (stage == ScenarioStage.CALIBRATION)
    ]
    if scenario_id is not None:
        exact = [item for item in stage_seeds if item[1].scenario_id == scenario_id]
        if len(exact) != 1:
            raise ValueError(f"scenario id is unknown or does not belong to the {stage.value} stage: {scenario_id}")
        if use_case_id is not None and exact[0][0].use_case_id != use_case_id:
            raise ValueError("--use-case-id and --scenario-id refer to different task families")
        return exact
    if stage == ScenarioStage.CALIBRATION:
        if use_case_id is not None:
            raise ValueError("calibration batch generation operates across all ten use cases; omit --use-case-id")
        return stage_seeds
    if use_case_id is None:
        raise ValueError("evaluation batch generation requires --use-case-id or an exact --scenario-id")
    selected = [item for item in stage_seeds if item[0].use_case_id == use_case_id]
    if not selected:
        raise ValueError(f"unknown use case id: {use_case_id}")
    return selected


def _timestamp_from_round_id(round_id: str) -> datetime:
    """Parse one validated round identifier as UTC."""
    return datetime.strptime(round_id, "%Y%m%dT%H%M%S%fZ").replace(tzinfo=timezone.utc)


def _run_config(run_id: str, created_at: Optional[datetime] = None) -> ScenarioGenerationRunConfig:
    """Build the immutable active-seed identity for one logical run."""
    return ScenarioGenerationRunConfig(
        schema_version="1.0.0",
        run_id=run_id,
        seed_version=ACTIVE_SCENARIO_SEED_VERSION,
        generation_protocol_version=ACTIVE_SCENARIO_GENERATION_VERSION,
        scenario_set_id=ACTIVE_SCENARIO_SET_ID,
        seed_sha256=ACTIVE_SCENARIO_SEED_SHA256,
        seed_schema_sha256=ACTIVE_SCENARIO_SEED_SCHEMA_SHA256,
        created_at=created_at or utc_now(),
    )


def _authenticated_run_root(run_id: str) -> Path:
    """Authenticate one existing run against the active seed and protocol."""
    run_root = scenario_generation_run_root(run_id)
    config_path = run_root / "run_config.json"
    if not config_path.is_file():
        raise FileNotFoundError(f"unknown scenario generation run: {run_id}")
    config = read_model_json(config_path, ScenarioGenerationRunConfig)
    expected_identity = _run_config(run_id, config.created_at)
    if config != expected_identity:
        raise ValueError("scenario generation run config does not match the active seed and protocol")
    return run_root


def _prepare_run_root(run_id: str) -> Tuple[str, Path]:
    """Create or authenticate one named logical run."""
    run_root = scenario_generation_run_root(run_id)
    if run_root.exists():
        return run_id, _authenticated_run_root(run_id)
    run_root.mkdir(parents=True, exist_ok=False)
    write_model_json_atomic(run_root / "run_config.json", _run_config(run_id))
    return run_id, run_root


def _create_invocation_root(
    run_root: Path,
    run_id: str,
    stage: ScenarioStage,
    selected: List[Tuple[V11UseCaseSeed, V11ReplicationSeed]],
    backend_specification: str,
) -> Path:
    """Create a timestamped round with an isolated provider-log directory."""
    invocation_id = scenario_generation_round_id()
    invocation_root = run_root / invocation_id
    invocation_root.mkdir(parents=True, exist_ok=False)
    config = ScenarioGenerationInvocationConfig(
        schema_version="1.0.0",
        run_id=run_id,
        invocation_id=invocation_id,
        stage=stage,
        scenario_ids=[replication.scenario_id for _, replication in selected],
        backend=backend_specification,
        created_at=_timestamp_from_round_id(invocation_id),
    )
    write_model_json_atomic(invocation_root / "invocation_config.json", config)
    return invocation_root


def _matching_incomplete_round(
    run_root: Path,
    stage: ScenarioStage,
    selected: List[Tuple[V11UseCaseSeed, V11ReplicationSeed]],
    backend_specification: str,
) -> Optional[Path]:
    """Find the newest matching round whose selected scenario work is incomplete."""
    scenario_ids = [replication.scenario_id for _, replication in selected]
    current = current_scenario_artifacts(run_root)
    if all(scenario_id in current and current[scenario_id].terminal_decision_path.is_file() for scenario_id in scenario_ids):
        return None
    for round_root in reversed(scenario_round_roots(run_root)):
        config_path = round_root / "invocation_config.json"
        if not config_path.is_file():
            continue
        config = read_model_json(config_path, ScenarioGenerationInvocationConfig)
        if config.stage != stage or config.scenario_ids != scenario_ids or config.backend != backend_specification:
            continue
        if any(not (round_root / "scenarios" / scenario_id / "terminal_decision.json").is_file() for scenario_id in scenario_ids):
            return round_root
    return None


def _load_evaluation_anchor(args: argparse.Namespace, use_case_id: str) -> CandidateScenario:
    """Authenticate the reviewed C1 candidate against the pre-R1-R2 tight-limit freeze."""
    if args.tight_limit_manifest is None or args.calibration_run_id is None:
        raise ValueError("evaluation generation requires --tight-limit-manifest and --calibration-run-id")
    tight_manifest = read_model_json(args.tight_limit_manifest, TightLimitManifest)
    validate_model_self_hash(tight_manifest, "manifest_sha256")
    if tight_manifest.freeze_status != FreezeStatus.FROZEN:
        raise ValueError("evaluation generation requires frozen C1-derived tight limits")
    budget = next(item for item in tight_manifest.use_case_budgets if item.use_case_id == use_case_id)
    calibration_run_root = _authenticated_run_root(args.calibration_run_id)
    current = current_scenario_artifacts(calibration_run_root)
    artifact = current.get(budget.calibration_scenario_id)
    if artifact is None:
        raise ValueError("calibration run does not contain the required C1 anchor")
    researcher_review = current_researcher_review(artifact, reviews_by_artifact_hash(calibration_run_root))
    if researcher_review is None or researcher_review.decision != ReviewDecision.ACCEPT:
        raise ValueError("current C1 anchor must have an exact researcher accept decision")
    candidate = artifact.candidate
    if candidate.scenario_id != budget.calibration_scenario_id or candidate.candidate_sha256 != budget.calibration_candidate_sha256:
        raise ValueError("calibration diversity anchor does not match the accepted candidate frozen with the tight limit")
    if (
        material_fact_word_count(candidate.material_facts) != budget.calibration_fact_word_count
        or material_fact_text_sha256(candidate.material_facts) != budget.calibration_fact_text_sha256
    ):
        raise ValueError("calibration diversity anchor material facts differ from the tight-limit freeze")
    return candidate


def _write_pipeline_result(output_root: Path, result: ScenarioPipelineResult) -> None:
    """Persist one complete scenario result with the terminal marker written last."""
    output_dir = output_root / result.candidate.scenario_id
    write_model_json_atomic(output_dir / "candidate.json", result.candidate)
    write_models_jsonl_atomic(output_dir / "automated_reviews.jsonl", result.reviews)
    write_models_jsonl_atomic(output_dir / "revision_cycles.jsonl", result.revisions)
    write_model_json_atomic(
        output_dir / "terminal_decision.json",
        ScenarioPipelineDisposition(
            schema_version="3.0.0",
            scenario_id=result.candidate.scenario_id,
            decision=result.terminal_decision,
            candidate_sha256=result.candidate.candidate_sha256,
            recorded_at=utc_now(),
        ),
    )


def _read_completed_result(
    output_root: Path,
    scenario_id: str,
    expected_reviewer_prompt_sha256: Optional[str] = None,
) -> Optional[ScenarioPipelineResult]:
    """Load one hash-consistent terminal result so paid scenario work can resume safely."""
    output_dir = output_root / scenario_id
    terminal_path = output_dir / "terminal_decision.json"
    if not terminal_path.exists():
        return None
    candidate = read_model_json(output_dir / "candidate.json", CandidateScenario)
    reviews = read_model_jsonl(output_dir / "automated_reviews.jsonl", AutomatedScenarioReview)
    revisions = read_model_jsonl(output_dir / "revision_cycles.jsonl", RevisionCycleRecord)
    disposition = read_model_json(terminal_path, ScenarioPipelineDisposition)
    if candidate.scenario_id != scenario_id or disposition.scenario_id != scenario_id:
        raise ValueError("persisted scenario result has the wrong scenario identifier")
    if disposition.candidate_sha256 != candidate.candidate_sha256:
        raise ValueError("persisted scenario disposition does not bind its candidate")
    if not reviews or any(review.scenario_id != scenario_id for review in reviews):
        raise ValueError("persisted scenario result has invalid automated reviews")
    if any(revision.scenario_id != scenario_id for revision in revisions):
        raise ValueError("persisted scenario result has invalid revision records")
    if expected_reviewer_prompt_sha256 is not None and any(review.reviewer_prompt_sha256 != expected_reviewer_prompt_sha256 for review in reviews):
        return None
    return ScenarioPipelineResult(
        candidate=candidate,
        reviews=reviews,
        revisions=revisions,
        terminal_decision=disposition.decision,
    )


def _archive_superseded_review(output_root: Path, scenario_id: str) -> None:
    """Move stale terminal review artifacts aside while retaining the generated candidate."""
    output_dir = output_root / scenario_id
    artifact_paths = [
        output_dir / "automated_reviews.jsonl",
        output_dir / "revision_cycles.jsonl",
        output_dir / "terminal_decision.json",
    ]
    if not any(path.exists() for path in artifact_paths):
        return
    archive_dir = output_dir / "superseded_reviews" / utc_now().strftime("%Y%m%dT%H%M%S%fZ")
    archive_dir.mkdir(parents=True, exist_ok=False)
    for path in artifact_paths:
        if path.exists():
            path.replace(archive_dir / path.name)


def _write_pipeline_failure(output_root: Path, scenario_id: str, error: Exception) -> None:
    """Persist one scenario failure without marking the scenario terminal."""
    recorded_at = utc_now()
    payload = {
        "schema_version": "3.0.0",
        "scenario_id": scenario_id,
        "error_type": type(error).__name__,
        "error_message": str(error),
        "recorded_at": recorded_at,
    }
    record = ScenarioPipelineFailureRecord.model_validate({**payload, "record_sha256": artifact_sha256(payload)})
    timestamp = recorded_at.strftime("%Y%m%dT%H%M%S%fZ")
    write_model_json_atomic(output_root / scenario_id / "failures" / f"{timestamp}.json", record)


def _generate_candidate_if_missing(
    candidate_root: Path,
    scenario_seed: Tuple[V11UseCaseSeed, V11ReplicationSeed],
    backend: ScenarioPipelineBackend,
) -> CandidateScenario:
    """Load an existing candidate or generate and persist it once for safe resume."""
    scenario_id = scenario_seed[1].scenario_id
    candidate_path = candidate_root / scenario_id / "candidate.json"
    if candidate_path.exists():
        return read_model_json(candidate_path, CandidateScenario)
    candidate = backend.generate_candidate(*scenario_seed)
    write_model_json_atomic(candidate_path, candidate)
    return candidate


def _family_evaluation_seeds(
    use_cases: List[V11UseCaseSeed],
    use_case_id: str,
) -> List[Tuple[V11UseCaseSeed, V11ReplicationSeed]]:
    """Return every non-C1 replication for one task family in seed order."""
    selected = [
        (use_case, replication)
        for use_case in use_cases
        if use_case.use_case_id == use_case_id
        for replication in use_case.replications
        if not replication.scenario_id.endswith("_C1")
    ]
    if not selected:
        raise ValueError(f"unknown use case id: {use_case_id}")
    return selected


def _load_run_researcher_revisions(
    run_root: Path,
    calibration_seeds: List[Tuple[V11UseCaseSeed, V11ReplicationSeed]],
) -> List[Tuple[Tuple[V11UseCaseSeed, V11ReplicationSeed], CandidateScenario, ResearcherScenarioReview]]:
    """Select current hash-bound revise decisions from one named run."""
    current = current_scenario_artifacts(run_root)
    reviews_by_hash = reviews_by_artifact_hash(run_root)
    revised_inputs = []
    for scenario_seed in calibration_seeds:
        scenario_id = scenario_seed[1].scenario_id
        artifact = current.get(scenario_id)
        if artifact is None:
            continue
        review = current_researcher_review(artifact, reviews_by_hash)
        if review is None or review.decision != ReviewDecision.REVISE:
            continue
        if not review.notes.strip():
            raise ValueError(f"researcher revise decision requires nonblank notes for {scenario_id}")
        revised_inputs.append((scenario_seed, artifact.candidate, review))
    return revised_inputs


def _load_round_researcher_revisions(
    round_root: Path,
    selected: List[Tuple[V11UseCaseSeed, V11ReplicationSeed]],
) -> List[Tuple[Tuple[V11UseCaseSeed, V11ReplicationSeed], CandidateScenario, ResearcherScenarioReview]]:
    """Reload immutable researcher-revision inputs when a round resumes."""
    stored = []
    for scenario_seed in selected:
        scenario_id = scenario_seed[1].scenario_id
        input_root = round_root / "inputs" / scenario_id
        parent_path = input_root / "parent_candidate.json"
        review_path = input_root / "researcher_revision.json"
        if parent_path.is_file() != review_path.is_file():
            raise ValueError(f"researcher revision inputs are incomplete for {scenario_id}")
        if parent_path.is_file():
            stored.append(
                (
                    scenario_seed,
                    read_model_json(parent_path, CandidateScenario),
                    read_model_json(review_path, ResearcherScenarioReview),
                )
            )
    return stored


def _researcher_revision_feedback(review: ResearcherScenarioReview) -> AutomatedScenarioReview:
    """Translate a bound researcher note into typed finding-linked revision feedback."""
    finding_id = f"RESEARCHER_{review.scenario_id}_REVISION"
    return AutomatedScenarioReview(
        schema_version="3.0.0",
        scenario_id=review.scenario_id,
        review_kind=AutomatedReviewKind.SCENARIO_QUALITY,
        decision=ReviewDecision.REVISE,
        findings=[
            ReviewFinding(
                finding_id=finding_id,
                severity=FindingSeverity.MAJOR,
                artifact_path="candidate.json",
                field_path="option_descriptions,material_facts,fact_pairs",
                message=review.notes,
                evidence=review.notes,
                suggested_action=f"Regenerate the option information to resolve the researcher note: {review.notes}",
            )
        ],
        reviewed_artifact_sha256=review.reviewed_artifact_sha256,
        reviewer_model_id=f"manual:{review.researcher_id}",
        reviewer_prompt_sha256=RESEARCHER_REVISION_CONTRACT_SHA256,
        reviewed_at=review.reviewed_at,
    )


def _researcher_revision_changes(
    parent_candidate: CandidateScenario,
    revised_candidate: CandidateScenario,
    finding_id: str,
) -> List[ControlledFieldChange]:
    """Rebuild deterministic field-change records for a researcher-directed regeneration."""
    generated_fields = ("option_descriptions", "material_facts", "fact_pairs")
    changes = [
        ControlledFieldChange(
            field_path=field_name,
            previous_value_sha256=artifact_sha256(getattr(parent_candidate, field_name)),
            revised_value_sha256=artifact_sha256(getattr(revised_candidate, field_name)),
            reason="Researcher-directed regeneration resolved the saved scenario-review note.",
            finding_ids=[finding_id],
        )
        for field_name in generated_fields
        if getattr(parent_candidate, field_name) != getattr(revised_candidate, field_name)
    ]
    if not changes:
        raise ValueError("researcher-directed regeneration did not change any generated content")
    return changes


def _run_researcher_directed_revision(
    run_root: Path,
    candidate_root: Path,
    scenario_seed: Tuple[V11UseCaseSeed, V11ReplicationSeed],
    parent_candidate: CandidateScenario,
    researcher_review: ResearcherScenarioReview,
    backend: ScenarioPipelineBackend,
) -> ScenarioPipelineResult:
    """Regenerate one C1 from saved researcher feedback and rerun semantic review."""
    scenario_id = scenario_seed[1].scenario_id
    if parent_candidate.scenario_id != scenario_id or researcher_review.scenario_id != scenario_id:
        raise ValueError("researcher-directed regeneration inputs do not match the selected scenario")
    scenario_input_root = run_root / "inputs" / scenario_id
    stored_parent_path = scenario_input_root / "parent_candidate.json"
    stored_review_path = scenario_input_root / "researcher_revision.json"
    if stored_parent_path.exists() and read_model_json(stored_parent_path, CandidateScenario) != parent_candidate:
        raise ValueError("resumed regeneration run has a different parent candidate")
    if stored_review_path.exists() and read_model_json(stored_review_path, ResearcherScenarioReview) != researcher_review:
        raise ValueError("resumed regeneration run has different researcher feedback")
    write_model_json_atomic(stored_parent_path, parent_candidate)
    write_model_json_atomic(stored_review_path, researcher_review)

    existing = _read_completed_result(candidate_root, scenario_id, sha256_bytes(SCENARIO_REVIEW_SYSTEM_PROMPT.encode("utf-8")))
    if existing is not None:
        return existing
    feedback = _researcher_revision_feedback(researcher_review)
    candidate_path = candidate_root / scenario_id / "candidate.json"
    if candidate_path.exists():
        revised_candidate = read_model_json(candidate_path, CandidateScenario)
        if revised_candidate.provenance.parent_sha256 != parent_candidate.candidate_sha256:
            raise ValueError("resumed regenerated candidate does not bind the supplied parent")
    else:
        revised_candidate, _ = backend.revise_candidate(
            scenario_seed[0],
            scenario_seed[1],
            parent_candidate,
            [feedback],
            1,
        )
        write_model_json_atomic(candidate_path, revised_candidate)
    reviews = backend.review_candidates([revised_candidate], [])
    if (
        len(reviews) != 1
        or reviews[0].scenario_id != scenario_id
        or reviews[0].review_kind != AutomatedReviewKind.SCENARIO_QUALITY
        or reviews[0].reviewed_artifact_sha256 != revised_candidate.candidate_sha256
    ):
        raise ValueError("researcher-directed regeneration returned an invalid semantic review")
    finding_id = feedback.findings[0].finding_id
    changes = _researcher_revision_changes(parent_candidate, revised_candidate, finding_id)
    revision = default_revision_record_factory(parent_candidate, revised_candidate, changes, reviews, 1)
    terminal_decision = ReviewDecision.MANUAL_RESTRUCTURE if reviews[0].decision == ReviewDecision.REVISE else reviews[0].decision
    return ScenarioPipelineResult(
        candidate=revised_candidate,
        reviews=reviews,
        revisions=[revision],
        terminal_decision=terminal_decision,
    )


def main() -> None:
    """Generate candidates and reviews while enforcing scenario lifecycle ordering."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", required=True)
    parser.add_argument("--stage", choices=[stage.value for stage in ScenarioStage], required=True)
    parser.add_argument("--use-case-id")
    parser.add_argument("--scenario-id", help="Generate one exact scenario within the named run")
    parser.add_argument("--run-id", required=True, help="Create or resume one named logical run, for example c1_calibration_v1")
    parser.add_argument("--tight-limit-manifest", type=Path)
    parser.add_argument("--calibration-run-id", help="Named C1 run used to resolve the current accepted diversity anchor")
    parser.add_argument("--output-root", type=Path, default=ACTIVE_SCENARIO_GENERATION_ROOT)
    args = parser.parse_args()
    stage = ScenarioStage(args.stage)
    expected_output_root = ACTIVE_SCENARIO_GENERATION_ROOT.resolve()
    if args.output_root.resolve() != expected_output_root:
        raise ValueError("scenario generation output must remain under the active V0.11.0 seed-version root")
    seed_root = ACTIVE_SCENARIO_INPUT_ROOT
    seed = load_and_validate_seed(
        seed_path=seed_root / "scenario_generation_seeds.json",
        schema_path=seed_root / "scenario_generation_seed_schema.json",
    )
    selected = _select_stage_seeds(seed.use_cases, stage, args.use_case_id, args.scenario_id)
    run_id, run_root = _prepare_run_root(args.run_id)
    current = current_scenario_artifacts(run_root)
    selected_ids = {replication.scenario_id for _, replication in selected}
    incomplete_round = _matching_incomplete_round(run_root, stage, selected, args.backend)
    revision_inputs = _load_run_researcher_revisions(run_root, selected) if stage == ScenarioStage.CALIBRATION else []
    if incomplete_round is not None:
        stored_revision_inputs = _load_round_researcher_revisions(incomplete_round, selected)
        if stored_revision_inputs:
            revision_inputs = stored_revision_inputs
    if incomplete_round is None and revision_inputs:
        selected = [scenario_seed for scenario_seed, _, _ in revision_inputs]
    elif incomplete_round is None:
        missing = [scenario_seed for scenario_seed in selected if scenario_seed[1].scenario_id not in current]
        if missing:
            selected = missing
        elif stage == ScenarioStage.CALIBRATION:
            reviews_by_hash = reviews_by_artifact_hash(run_root)
            pending = [
                scenario_id for scenario_id in sorted(selected_ids) if current_researcher_review(current[scenario_id], reviews_by_hash) is None
            ]
            if pending:
                print(f"Run {run_id} is awaiting researcher review for {', '.join(pending)}")
                return
            print(f"Run {run_id} has no calibration revisions to generate; every selected current candidate is accepted")
            return
        elif all(current[scenario_id].terminal_decision_path.is_file() for scenario_id in selected_ids):
            print(f"Run {run_id} already contains completed current artifacts for {', '.join(sorted(selected_ids))}")
            return
    round_root = incomplete_round or _create_invocation_root(run_root, run_id, stage, selected, args.backend)
    candidate_root = round_root / "scenarios"
    backend = _load_backend(args.backend, round_root)
    if revision_inputs:
        results = {}
        for scenario_seed, parent_candidate, researcher_review in revision_inputs:
            scenario_id = scenario_seed[1].scenario_id
            terminal_path = candidate_root / scenario_id / "terminal_decision.json"
            try:
                result = _run_researcher_directed_revision(
                    round_root,
                    candidate_root,
                    scenario_seed,
                    parent_candidate,
                    researcher_review,
                    backend,
                )
            except Exception as error:
                _write_pipeline_failure(candidate_root, scenario_id, error)
                raise
            if not terminal_path.exists():
                _write_pipeline_result(candidate_root, result)
            results[scenario_id] = result
        decisions = ", ".join(f"{scenario_id}={result.terminal_decision.value}" for scenario_id, result in sorted(results.items()))
        print(f"Researcher revisions completed in run {run_id}, round {round_root.name} ({decisions}); re-review the named run")
        print(f"Round root: {round_root}")
        return
    results = {}
    if stage == ScenarioStage.CALIBRATION:
        expected_reviewer_prompt_sha256 = sha256_bytes(SCENARIO_REVIEW_SYSTEM_PROMPT.encode("utf-8"))
        for scenario_seed in selected:
            scenario_id = scenario_seed[1].scenario_id
            existing = _read_completed_result(candidate_root, scenario_id, expected_reviewer_prompt_sha256)
            if existing is not None:
                results[scenario_id] = existing
                continue
            _archive_superseded_review(candidate_root, scenario_id)
            try:
                candidate = _generate_candidate_if_missing(candidate_root, scenario_seed, backend)
                result = run_scenario_batch_pipeline(
                    [scenario_seed],
                    backend,
                    default_revision_record_factory,
                    initial_candidates={scenario_id: candidate},
                )[scenario_id]
            except Exception as error:
                _write_pipeline_failure(candidate_root, scenario_id, error)
                raise
            _write_pipeline_result(candidate_root, result)
            results[scenario_id] = result
    else:
        fixed_candidates = [_load_evaluation_anchor(args, selected[0][0].use_case_id)]
        for scenario_seed in selected:
            scenario_id = scenario_seed[1].scenario_id
            try:
                _generate_candidate_if_missing(candidate_root, scenario_seed, backend)
            except Exception as error:
                _write_pipeline_failure(candidate_root, scenario_id, error)
                raise
        family_seeds = _family_evaluation_seeds(seed.use_cases, selected[0][0].use_case_id)
        current = current_scenario_artifacts(run_root)
        if any(replication.scenario_id not in current for _, replication in family_seeds):
            pending_ids = [replication.scenario_id for _, replication in family_seeds if replication.scenario_id not in current]
            print(
                f"Saved {selected[0][1].scenario_id} in run {run_id}, round {round_root.name}; "
                f"automated family review is pending {', '.join(pending_ids)}. "
                f"Continue with --run-id {run_id}."
            )
            return
        for _, replication in family_seeds:
            artifact = current[replication.scenario_id]
            destination = candidate_root / replication.scenario_id / "candidate.json"
            if not destination.exists():
                write_model_json_atomic(destination, artifact.candidate)
        initial_candidates = {
            replication.scenario_id: read_model_json(candidate_root / replication.scenario_id / "candidate.json", CandidateScenario)
            for _, replication in family_seeds
        }
        completed = {
            replication.scenario_id: _read_completed_result(
                candidate_root,
                replication.scenario_id,
                sha256_bytes(SCENARIO_REVIEW_SYSTEM_PROMPT.encode("utf-8")),
            )
            for _, replication in family_seeds
        }
        if all(result is not None for result in completed.values()):
            results = {scenario_id: result for scenario_id, result in completed.items() if result is not None}
        else:
            for _, replication in family_seeds:
                _archive_superseded_review(candidate_root, replication.scenario_id)
            try:
                results = run_scenario_batch_pipeline(
                    family_seeds,
                    backend,
                    default_revision_record_factory,
                    fixed_candidates,
                    initial_candidates=initial_candidates,
                )
            except Exception as error:
                for _, replication in family_seeds:
                    _write_pipeline_failure(candidate_root, replication.scenario_id, error)
                raise
            for result in results.values():
                _write_pipeline_result(candidate_root, result)
    decisions = ", ".join(f"{scenario_id}={result.terminal_decision.value}" for scenario_id, result in sorted(results.items()))
    print(f"{stage.value} scenario work completed in run {run_id}, round {round_root.name} ({decisions}); researcher acceptance remains required")
    print(f"Round root: {round_root}")


if __name__ == "__main__":
    main()
