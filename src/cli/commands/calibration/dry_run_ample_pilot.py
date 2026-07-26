"""Create the mandatory offline cost report for the 60-response ample pilot."""

from __future__ import annotations

import argparse
import math
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict

from src.cli.commands.calibration.run_ample_pilot import compile_ample_pilot_request
from src.data_models.common import artifact_sha256, file_sha256, validate_model_self_hash
from src.data_models.experiments import RetryPolicy
from src.data_models.manifests import (
    AcceptedScenarioManifest,
    AmplePilotCostReport,
    CalibrationPromptReviewManifest,
    CueReviewDecision,
    EvaluatedModelManifest,
    FreezeStatus,
    ModelPricingAssumption,
    PricingAssumptionInput,
)
from src.data_models.study import PILOT_WORD_LIMIT, ExpressedConcernCondition
from src.experiments.io import load_accepted_calibration_scenarios
from src.paths import (
    ACTIVE_SCENARIO_ACCEPTED_ROOT,
    ACTIVE_SCENARIO_CHECKPOINT_ROOT,
    ACTIVE_SCENARIO_INPUT_ROOT,
    AMPLE_PILOT_COST_REPORT_PATH,
    EVALUATED_MODEL_MANIFEST_PATH,
)
from src.prompts.experiment import prompt_package_sha256
from src.scenarios.word_count import count_words
from src.storage import read_model_json, write_model_json_atomic


def _estimate_tokens(word_count: int) -> int:
    """Conservatively convert English word counts to approximate provider tokens."""
    return math.ceil(word_count * 1.5)


def _token_cost(input_tokens: int, output_tokens: int, pricing: ModelPricingAssumption) -> Decimal:
    """Calculate one model request's estimated token cost."""
    million = Decimal("1000000")
    return (Decimal(input_tokens) * pricing.input_per_million_usd + Decimal(output_tokens) * pricing.output_per_million_usd) / million


def _pricing_payload(pricing: Dict[str, ModelPricingAssumption]) -> Dict[str, Decimal]:
    """Flatten selected model pricing into the persisted audit mapping."""
    payload = {f"{model_id}:input_per_million_usd": values.input_per_million_usd for model_id, values in pricing.items()}
    payload.update({f"{model_id}:output_per_million_usd": values.output_per_million_usd for model_id, values in pricing.items()})
    return payload


def main() -> None:
    """Authenticate frozen pilot inputs and persist an exact offline cost estimate."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--accepted-root", type=Path, required=True)
    parser.add_argument("--accepted-scenario-manifest", type=Path, required=True)
    parser.add_argument("--evaluated-model-manifest", type=Path, required=True)
    parser.add_argument("--prompt-review-manifest", type=Path, required=True)
    parser.add_argument("--retry-policy", type=Path, required=True)
    parser.add_argument("--pricing", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    expected_paths = [
        (args.accepted_root, ACTIVE_SCENARIO_ACCEPTED_ROOT),
        (args.accepted_scenario_manifest, ACTIVE_SCENARIO_INPUT_ROOT / "calibration_accepted_scenario_manifest.json"),
        (args.evaluated_model_manifest, EVALUATED_MODEL_MANIFEST_PATH),
        (args.prompt_review_manifest, ACTIVE_SCENARIO_CHECKPOINT_ROOT / "calibration_prompt_review.json"),
        (args.output, AMPLE_PILOT_COST_REPORT_PATH),
    ]
    if any(supplied.resolve() != expected.resolve() for supplied, expected in expected_paths):
        raise ValueError("ample-pilot cost reporting must use the active scenario lifecycle paths")
    if args.output.exists():
        raise FileExistsError("the ample-pilot cost report already exists and cannot be replaced")
    accepted_manifest = read_model_json(args.accepted_scenario_manifest, AcceptedScenarioManifest)
    model_manifest = read_model_json(args.evaluated_model_manifest, EvaluatedModelManifest)
    prompt_review = read_model_json(args.prompt_review_manifest, CalibrationPromptReviewManifest)
    retry_policy = read_model_json(args.retry_policy, RetryPolicy)
    for manifest in [accepted_manifest, model_manifest, prompt_review]:
        validate_model_self_hash(manifest, "manifest_sha256")
    if model_manifest.freeze_status != FreezeStatus.FROZEN or prompt_review.decision != CueReviewDecision.APPROVE:
        raise ValueError("ample-pilot cost reporting requires frozen models and approved C1 prompts")
    if prompt_review.accepted_scenario_manifest_sha256 != accepted_manifest.manifest_sha256:
        raise ValueError("C1 prompt review does not bind the supplied calibration scenario manifest")
    scenarios = load_accepted_calibration_scenarios(args.accepted_root, accepted_manifest)
    if len(scenarios) != 10:
        raise ValueError("ample-pilot cost reporting requires exactly ten accepted C1 scenarios")
    all_pricing = read_model_json(args.pricing, PricingAssumptionInput).models
    model_ids = {model.model_id for model in model_manifest.evaluated_models}
    if not model_ids.issubset(all_pricing):
        raise ValueError("pricing input must cover every frozen evaluated model")
    pricing = {model_id: all_pricing[model_id] for model_id in sorted(model_ids)}
    attempts_per_response = retry_policy.max_retries + 1
    estimated_input_tokens = 0
    estimated_output_tokens = 0
    estimated_cost = Decimal("0")
    worst_case_input_tokens = 0
    worst_case_output_tokens = 0
    worst_case_cost = Decimal("0")
    request_sha256s = []
    response_count = 0
    for scenario in sorted(scenarios, key=lambda item: item.scenario_id):
        for model in sorted(model_manifest.evaluated_models, key=lambda item: item.model_id):
            for cue in ExpressedConcernCondition:
                messages, _prompt_sha256, _record_id, _random_seed, request_sha256 = compile_ample_pilot_request(
                    scenario,
                    model.model_id,
                    cue,
                    args.seed,
                )
                input_tokens = _estimate_tokens(sum(count_words(message["content"]) for message in messages))
                output_tokens = _estimate_tokens(PILOT_WORD_LIMIT)
                maximum_output_tokens = PILOT_WORD_LIMIT * 4
                estimated_input_tokens += input_tokens
                estimated_output_tokens += output_tokens
                estimated_cost += _token_cost(input_tokens, output_tokens, pricing[model.model_id])
                worst_case_input_tokens += input_tokens * attempts_per_response
                worst_case_output_tokens += maximum_output_tokens * attempts_per_response
                worst_case_cost += _token_cost(
                    input_tokens * attempts_per_response,
                    maximum_output_tokens * attempts_per_response,
                    pricing[model.model_id],
                )
                request_sha256s.append(request_sha256)
                response_count += 1
    payload = {
        "schema_version": "2.0.0",
        "accepted_scenario_manifest_sha256": accepted_manifest.manifest_sha256,
        "evaluated_model_manifest_sha256": model_manifest.manifest_sha256,
        "prompt_review_manifest_sha256": prompt_review.manifest_sha256,
        "prompt_package_sha256": prompt_package_sha256(),
        "retry_policy_sha256": artifact_sha256(retry_policy),
        "pricing_file_sha256": file_sha256(args.pricing),
        "randomisation_seed": args.seed,
        "provider_request_sha256s": sorted(request_sha256s),
        "pilot_responses": response_count,
        "maximum_attempts_including_retries": response_count * attempts_per_response,
        "estimated_input_tokens": estimated_input_tokens,
        "estimated_output_tokens": estimated_output_tokens,
        "estimated_cost_usd": estimated_cost.quantize(Decimal("0.0001")),
        "worst_case_input_tokens": worst_case_input_tokens,
        "worst_case_output_tokens": worst_case_output_tokens,
        "worst_case_cost_usd": worst_case_cost.quantize(Decimal("0.0001")),
        "pricing_assumptions": _pricing_payload(pricing),
        "generated_at": datetime.now(timezone.utc),
    }
    report = AmplePilotCostReport.model_validate({**payload, "report_sha256": artifact_sha256(payload)})
    write_model_json_atomic(args.output, report)
    print(
        f"Estimated {report.pilot_responses} pilot responses at ${report.estimated_cost_usd} base / "
        f"${report.worst_case_cost_usd} worst case; wrote {args.output}"
    )


if __name__ == "__main__":
    main()
