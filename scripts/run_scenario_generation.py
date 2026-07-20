"""Run lifecycle-ordered C1 or C1-anchored R1-R4 scenario generation."""

from __future__ import annotations

import argparse
import importlib
from pathlib import Path
from typing import List, Optional, Tuple, cast

from src.data_models.common import utc_now, validate_model_self_hash
from src.data_models.manifests import CueReviewDecision, FreezeStatus, PromptReviewManifest, TightLimitManifest
from src.data_models.scenario_review import ScenarioPipelineDisposition
from src.data_models.scenarios import CandidateScenario, ReplicationSeed, ScenarioStage, UseCaseSeed
from src.data_models.study import NEUTRAL_CUE, WORRIED_CUE
from src.scenarios.pipeline import ScenarioPipelineBackend, default_revision_record_factory, run_scenario_batch_pipeline
from src.scenarios.seed_validation import load_and_validate_seed
from src.storage import read_model_json, write_model_json_atomic, write_models_jsonl_atomic

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_backend(specification: str) -> ScenarioPipelineBackend:
    """Load a backend factory from module:attribute without embedding credentials."""
    module_name, separator, attribute_name = specification.partition(":")
    if not separator:
        raise ValueError("backend must use module:attribute syntax")
    return cast(ScenarioPipelineBackend, getattr(importlib.import_module(module_name), attribute_name)())


def _select_stage_seeds(
    use_cases: List[UseCaseSeed],
    stage: ScenarioStage,
    use_case_id: Optional[str],
) -> List[Tuple[UseCaseSeed, ReplicationSeed]]:
    """Select ten C1 seeds or one use case's four R seeds without crossing lifecycle stages."""
    if stage == ScenarioStage.CALIBRATION:
        if use_case_id is not None:
            raise ValueError("calibration generation operates across all ten use cases; omit --use-case-id")
        return [
            (use_case, next(replication for replication in use_case.replications if replication.scenario_id.endswith("_C1")))
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
    """Authenticate the reviewed C1 candidate against the pre-R1-R4 tight-limit freeze."""
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
        candidate.minimal_complete_response.word_count != budget.calibration_minimal_word_count
        or candidate.minimal_complete_response.text_sha256 != budget.calibration_response_text_sha256
    ):
        raise ValueError("calibration diversity anchor minimal response differs from the tight-limit freeze")
    return candidate


def main() -> None:
    """Generate ignored candidates and reviews while enforcing V9 lifecycle ordering."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", required=True)
    parser.add_argument("--stage", type=ScenarioStage, choices=list(ScenarioStage), required=True)
    parser.add_argument("--use-case-id")
    parser.add_argument("--prompt-review-manifest", type=Path, required=True)
    parser.add_argument("--tight-limit-manifest", type=Path)
    parser.add_argument("--calibration-candidate", type=Path)
    parser.add_argument("--output-root", type=Path, default=REPO_ROOT / "data/outputs/scenario_generation/v0.5.1")
    parser.add_argument("--execute-paid", action="store_true")
    args = parser.parse_args()
    if not args.execute_paid:
        raise PermissionError("scenario generation may call paid APIs and requires --execute-paid")
    expected_output_root = (REPO_ROOT / "data/outputs/scenario_generation/v0.5.1").resolve()
    if args.output_root.resolve() != expected_output_root:
        raise ValueError("scenario generation output must remain under data/outputs/scenario_generation/v0.5.1")
    prompt_review = read_model_json(args.prompt_review_manifest, PromptReviewManifest)
    validate_model_self_hash(prompt_review, "manifest_sha256")
    if prompt_review.decision != CueReviewDecision.APPROVE:
        raise ValueError("model-generated calibration is blocked until cue wording is approved")
    if prompt_review.neutral_cue != NEUTRAL_CUE or prompt_review.worried_cue != WORRIED_CUE:
        raise ValueError("cue review does not bind the code-owned prompt wording")
    seed_root = REPO_ROOT / "data/inputs/scenarios/v0.5.1"
    seed = load_and_validate_seed(
        seed_path=seed_root / "scenario_generation_seeds.json",
        schema_path=seed_root / "scenario_generation_seed_schema.json",
    )
    selected = _select_stage_seeds(seed.use_cases, args.stage, args.use_case_id)
    fixed_candidates = []
    if args.stage == ScenarioStage.EVALUATION:
        fixed_candidates = [_load_evaluation_anchor(args, selected[0][0].use_case_id)]
    results = run_scenario_batch_pipeline(selected, _load_backend(args.backend), default_revision_record_factory, fixed_candidates)
    for scenario_id, result in results.items():
        output_dir = expected_output_root / scenario_id
        write_model_json_atomic(output_dir / "candidate.json", result.candidate)
        write_models_jsonl_atomic(output_dir / "automated_reviews.jsonl", result.reviews)
        write_models_jsonl_atomic(output_dir / "revision_cycles.jsonl", result.revisions)
        write_model_json_atomic(
            output_dir / "terminal_decision.json",
            ScenarioPipelineDisposition(
                schema_version="1.0.0",
                scenario_id=scenario_id,
                decision=result.terminal_decision,
                candidate_sha256=result.candidate.candidate_sha256,
                recorded_at=utc_now(),
            ),
        )
    decisions = ", ".join(f"{scenario_id}={result.terminal_decision.value}" for scenario_id, result in sorted(results.items()))
    print(f"{args.stage.value} scenario batch completed ({decisions}); researcher acceptance remains required")


if __name__ == "__main__":
    main()
