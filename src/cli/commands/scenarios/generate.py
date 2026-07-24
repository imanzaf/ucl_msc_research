"""Run lifecycle-ordered C1 or C1-anchored R1-R2 scenario generation."""

from __future__ import annotations

import argparse
import importlib
from pathlib import Path
from typing import List, Optional, Tuple, cast

from src.data_models.common import artifact_sha256, sha256_bytes, utc_now, validate_model_self_hash
from src.data_models.manifests import FreezeStatus, TightLimitManifest
from src.data_models.scenario_review import AutomatedScenarioReview, RevisionCycleRecord, ScenarioPipelineDisposition, ScenarioPipelineFailureRecord
from src.data_models.scenarios import CandidateScenario, ScenarioStage, V10ReplicationSeed, V10UseCaseSeed
from src.paths import ACTIVE_SCENARIO_GENERATION_ROOT, ACTIVE_SCENARIO_INPUT_ROOT
from src.prompts.scenario_generation import SCENARIO_REVIEW_SYSTEM_PROMPT
from src.scenarios.budgets import material_fact_text_sha256, material_fact_word_count
from src.scenarios.pipeline import ScenarioPipelineBackend, ScenarioPipelineResult, default_revision_record_factory, run_scenario_batch_pipeline
from src.scenarios.seed_validation import load_and_validate_seed
from src.storage import read_model_json, read_model_jsonl, write_model_json_atomic, write_models_jsonl_atomic


def _load_backend(specification: str) -> ScenarioPipelineBackend:
    """Load a backend factory from module:attribute without embedding credentials."""
    module_name, separator, attribute_name = specification.partition(":")
    if not separator:
        raise ValueError("backend must use module:attribute syntax")
    return cast(ScenarioPipelineBackend, getattr(importlib.import_module(module_name), attribute_name)())


def _select_stage_seeds(
    use_cases: List[V10UseCaseSeed],
    stage: ScenarioStage,
    use_case_id: Optional[str],
) -> List[Tuple[V10UseCaseSeed, V10ReplicationSeed]]:
    """Select ten C1 seeds or one use case's two R seeds without crossing lifecycle stages."""
    if stage == ScenarioStage.CALIBRATION:
        if use_case_id is not None:
            raise ValueError("calibration generation operates across all ten use cases; omit --use-case-id")
        return [
            (
                use_case,
                next(replication for replication in use_case.replications if replication.scenario_id.endswith("_C1")),
            )
            for use_case in use_cases
        ]
    if use_case_id is None:
        raise ValueError("evaluation generation requires --use-case-id")
    selected_use_cases = [use_case for use_case in use_cases if use_case.use_case_id == use_case_id]
    if len(selected_use_cases) != 1:
        raise ValueError(f"unknown or duplicate use case id: {use_case_id}")
    selected = selected_use_cases[0]
    return [(selected, replication) for replication in selected.replications if not replication.scenario_id.endswith("_C1")]


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
    """Load one hash-consistent terminal result so paid calibration can resume safely."""
    output_dir = output_root / scenario_id
    terminal_path = output_dir / "terminal_decision.json"
    if not terminal_path.exists():
        return None
    candidate = read_model_json(output_dir / "candidate.json", CandidateScenario)
    reviews = read_model_jsonl(output_dir / "automated_reviews.jsonl", AutomatedScenarioReview)
    revisions = read_model_jsonl(output_dir / "revision_cycles.jsonl", RevisionCycleRecord)
    disposition = read_model_json(terminal_path, ScenarioPipelineDisposition)
    if candidate.scenario_id != scenario_id or disposition.scenario_id != scenario_id:
        raise ValueError("persisted calibration result has the wrong scenario identifier")
    if disposition.candidate_sha256 != candidate.candidate_sha256:
        raise ValueError("persisted calibration disposition does not bind its candidate")
    if not reviews or any(review.scenario_id != scenario_id for review in reviews):
        raise ValueError("persisted calibration result has invalid automated reviews")
    if any(revision.scenario_id != scenario_id for revision in revisions):
        raise ValueError("persisted calibration result has invalid revision records")
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


def main() -> None:
    """Generate candidates and reviews while enforcing scenario lifecycle ordering."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", required=True)
    parser.add_argument("--stage", choices=[stage.value for stage in ScenarioStage], required=True)
    parser.add_argument("--use-case-id")
    parser.add_argument("--tight-limit-manifest", type=Path)
    parser.add_argument("--calibration-candidate", type=Path)
    parser.add_argument("--output-root", type=Path, default=ACTIVE_SCENARIO_GENERATION_ROOT)
    args = parser.parse_args()
    stage = ScenarioStage(args.stage)
    expected_output_root = ACTIVE_SCENARIO_GENERATION_ROOT.resolve()
    if args.output_root.resolve() != expected_output_root:
        raise ValueError("scenario generation output must remain under the active V0.10.0 generation root")
    seed_root = ACTIVE_SCENARIO_INPUT_ROOT
    seed = load_and_validate_seed(
        seed_path=seed_root / "scenario_generation_seeds.json",
        schema_path=seed_root / "scenario_generation_seed_schema.json",
    )
    selected = _select_stage_seeds(seed.use_cases, stage, args.use_case_id)
    fixed_candidates = []
    if stage == ScenarioStage.EVALUATION:
        fixed_candidates = [_load_evaluation_anchor(args, selected[0][0].use_case_id)]
    backend = _load_backend(args.backend)
    results = {}
    if stage == ScenarioStage.CALIBRATION:
        expected_reviewer_prompt_sha256 = sha256_bytes(SCENARIO_REVIEW_SYSTEM_PROMPT.encode("utf-8"))
        for scenario_seed in selected:
            scenario_id = scenario_seed[1].scenario_id
            existing = _read_completed_result(expected_output_root, scenario_id, expected_reviewer_prompt_sha256)
            if existing is not None:
                results[scenario_id] = existing
                continue
            _archive_superseded_review(expected_output_root, scenario_id)
            try:
                candidate_path = expected_output_root / scenario_id / "candidate.json"
                if candidate_path.exists():
                    candidate = read_model_json(candidate_path, CandidateScenario)
                else:
                    candidate = backend.generate_candidate(*scenario_seed)
                    write_model_json_atomic(candidate_path, candidate)
                result = run_scenario_batch_pipeline(
                    [scenario_seed],
                    backend,
                    default_revision_record_factory,
                    initial_candidates={scenario_id: candidate},
                )[scenario_id]
            except Exception as error:
                _write_pipeline_failure(expected_output_root, scenario_id, error)
                raise
            _write_pipeline_result(expected_output_root, result)
            results[scenario_id] = result
    else:
        results = run_scenario_batch_pipeline(selected, backend, default_revision_record_factory, fixed_candidates)
        for result in results.values():
            _write_pipeline_result(expected_output_root, result)
    decisions = ", ".join(f"{scenario_id}={result.terminal_decision.value}" for scenario_id, result in sorted(results.items()))
    print(f"{stage.value} scenario batch completed ({decisions}); researcher acceptance remains required")


if __name__ == "__main__":
    main()
