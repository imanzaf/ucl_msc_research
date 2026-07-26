"""Run lifecycle-ordered C1 or C1-anchored R1-R2 scenario generation."""

from __future__ import annotations

import argparse
import importlib
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple, cast

from src.data_models.common import artifact_sha256, sha256_bytes, utc_now, validate_model_self_hash
from src.data_models.manifests import FreezeStatus, TightLimitManifest
from src.data_models.scenario_review import AutomatedScenarioReview, RevisionCycleRecord, ScenarioPipelineDisposition, ScenarioPipelineFailureRecord
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
    scenario_generation_run_id,
    scenario_generation_run_root,
)
from src.prompts.scenario_generation import SCENARIO_REVIEW_SYSTEM_PROMPT
from src.scenarios.budgets import material_fact_text_sha256, material_fact_word_count
from src.scenarios.pipeline import ScenarioPipelineBackend, ScenarioPipelineResult, default_revision_record_factory, run_scenario_batch_pipeline
from src.scenarios.seed_validation import load_and_validate_seed
from src.storage import read_model_json, read_model_jsonl, write_model_json_atomic, write_models_jsonl_atomic


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


def _timestamp_from_run_id(run_id: str) -> datetime:
    """Parse one validated run or invocation identifier as UTC."""
    return datetime.strptime(run_id, "%Y%m%dT%H%M%S%fZ").replace(tzinfo=timezone.utc)


def _run_config(run_id: str) -> ScenarioGenerationRunConfig:
    """Build the immutable active-seed identity for one logical run."""
    return ScenarioGenerationRunConfig(
        schema_version="1.0.0",
        run_id=run_id,
        seed_version=ACTIVE_SCENARIO_SEED_VERSION,
        generation_protocol_version=ACTIVE_SCENARIO_GENERATION_VERSION,
        scenario_set_id=ACTIVE_SCENARIO_SET_ID,
        seed_sha256=ACTIVE_SCENARIO_SEED_SHA256,
        seed_schema_sha256=ACTIVE_SCENARIO_SEED_SCHEMA_SHA256,
        created_at=_timestamp_from_run_id(run_id),
    )


def _prepare_run_root(requested_run_id: Optional[str]) -> Tuple[str, Path]:
    """Create a fresh timestamped run or authenticate an explicitly resumed run."""
    if requested_run_id is None:
        run_id = scenario_generation_run_id()
        run_root = scenario_generation_run_root(run_id)
        run_root.mkdir(parents=True, exist_ok=False)
        write_model_json_atomic(run_root / "run_config.json", _run_config(run_id))
        return run_id, run_root
    run_root = scenario_generation_run_root(requested_run_id)
    config_path = run_root / "run_config.json"
    if not config_path.is_file():
        raise FileNotFoundError(f"cannot resume unknown scenario generation run: {requested_run_id}")
    if read_model_json(config_path, ScenarioGenerationRunConfig) != _run_config(requested_run_id):
        raise ValueError("scenario generation run config does not match the active seed and protocol")
    return requested_run_id, run_root


def _create_invocation_root(
    run_root: Path,
    run_id: str,
    stage: ScenarioStage,
    selected: List[Tuple[V11UseCaseSeed, V11ReplicationSeed]],
    backend_specification: str,
) -> Path:
    """Create a timestamped invocation record and isolated provider-log directory."""
    invocation_id = scenario_generation_run_id()
    invocation_root = run_root / "invocations" / invocation_id
    invocation_root.mkdir(parents=True, exist_ok=False)
    config = ScenarioGenerationInvocationConfig(
        schema_version="1.0.0",
        run_id=run_id,
        invocation_id=invocation_id,
        stage=stage,
        scenario_ids=[replication.scenario_id for _, replication in selected],
        backend=backend_specification,
        created_at=_timestamp_from_run_id(invocation_id),
    )
    write_model_json_atomic(invocation_root / "invocation_config.json", config)
    return invocation_root


def _load_evaluation_anchor(args: argparse.Namespace, use_case_id: str) -> CandidateScenario:
    """Authenticate the reviewed C1 candidate against the pre-R1-R2 tight-limit freeze."""
    if args.tight_limit_manifest is None or args.calibration_candidate is None:
        raise ValueError("evaluation generation requires --tight-limit-manifest and --calibration-candidate")
    tight_manifest = read_model_json(args.tight_limit_manifest, TightLimitManifest)
    validate_model_self_hash(tight_manifest, "manifest_sha256")
    if tight_manifest.freeze_status != FreezeStatus.FROZEN:
        raise ValueError("evaluation generation requires frozen C1-derived tight limits")
    candidate = read_model_json(args.calibration_candidate, CandidateScenario)
    budget = next(item for item in tight_manifest.use_case_budgets if item.use_case_id == use_case_id)
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


def main() -> None:
    """Generate candidates and reviews while enforcing scenario lifecycle ordering."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", required=True)
    parser.add_argument("--stage", choices=[stage.value for stage in ScenarioStage], required=True)
    parser.add_argument("--use-case-id")
    parser.add_argument("--scenario-id", help="Generate one exact scenario; reuse --run-id for later replications or retries")
    parser.add_argument("--run-id", help="Continue an existing logical run; omit to start a fresh timestamped run")
    parser.add_argument("--tight-limit-manifest", type=Path)
    parser.add_argument("--calibration-candidate", type=Path)
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
    invocation_root = _create_invocation_root(run_root, run_id, stage, selected, args.backend)
    candidate_root = run_root / "scenarios"
    fixed_candidates = []
    if stage == ScenarioStage.EVALUATION:
        fixed_candidates = [_load_evaluation_anchor(args, selected[0][0].use_case_id)]
    backend = _load_backend(args.backend, invocation_root)
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
        for scenario_seed in selected:
            scenario_id = scenario_seed[1].scenario_id
            try:
                _generate_candidate_if_missing(candidate_root, scenario_seed, backend)
            except Exception as error:
                _write_pipeline_failure(candidate_root, scenario_id, error)
                raise
        family_seeds = _family_evaluation_seeds(seed.use_cases, selected[0][0].use_case_id)
        if len(selected) == 1 and any(not (candidate_root / replication.scenario_id / "candidate.json").is_file() for _, replication in family_seeds):
            pending_ids = [
                replication.scenario_id
                for _, replication in family_seeds
                if not (candidate_root / replication.scenario_id / "candidate.json").is_file()
            ]
            print(
                f"Saved {selected[0][1].scenario_id} in run {run_id}; "
                f"automated family review is pending {', '.join(pending_ids)}. "
                f"Continue with --run-id {run_id}."
            )
            return
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
    print(f"{stage.value} scenario work completed in run {run_id} ({decisions}); researcher acceptance remains required")
    print(f"Run root: {run_root}")


if __name__ == "__main__":
    main()
