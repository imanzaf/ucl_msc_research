"""Create a conservative cost report for one scenario-generation batch."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict, Tuple

from src.data_models.common import artifact_sha256, file_sha256
from src.data_models.manifests import ModelPricingAssumption, PricingAssumptionInput, ScenarioGenerationCostReport
from src.data_models.scenarios import ScenarioStage
from src.experiments.model_catalog import load_model_catalog
from src.paths import ACTIVE_SCENARIO_CHECKPOINT_ROOT, ACTIVE_SCENARIO_INPUT_ROOT
from src.scenarios.openrouter_backend import STRUCTURED_MAX_OUTPUT_TOKENS
from src.scenarios.seed_validation import load_and_validate_seed
from src.storage import read_model_json, write_model_json_atomic

SCENARIO_BACKEND = "src.scenarios.openrouter_backend:create_openrouter_scenario_backend"
SEED_ROOT = ACTIVE_SCENARIO_INPUT_ROOT
OUTPUT_ROOT = ACTIVE_SCENARIO_CHECKPOINT_ROOT


def _call_counts(stage: ScenarioStage) -> Tuple[int, int, int, int, int]:
    """Return scenario, base-role, and worst-role call counts for one lifecycle batch."""
    if stage == ScenarioStage.CALIBRATION:
        return 10, 10, 10, 20, 20
    return 4, 4, 1, 8, 2


def _role_cost(
    calls: int,
    maximum_input_tokens: int,
    maximum_output_tokens: int,
    pricing: ModelPricingAssumption,
) -> Decimal:
    """Calculate one role's conservative token cost for a declared call count."""
    million = Decimal("1000000")
    return (
        Decimal(calls)
        * (Decimal(maximum_input_tokens) * pricing.input_per_million_usd + Decimal(maximum_output_tokens) * pricing.output_per_million_usd)
        / million
    )


def _pricing_payload(pricing: Dict[str, ModelPricingAssumption]) -> Dict[str, Decimal]:
    """Flatten model pricing into the persisted audit mapping."""
    payload = {f"{model_id}:input_per_million_usd": values.input_per_million_usd for model_id, values in pricing.items()}
    payload.update({f"{model_id}:output_per_million_usd": values.output_per_million_usd for model_id, values in pricing.items()})
    return payload


def main() -> None:
    """Authenticate the V0.9.0 batch and write its offline cost report."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=[stage.value for stage in ScenarioStage], required=True)
    parser.add_argument("--use-case-id")
    parser.add_argument("--pricing", type=Path, required=True)
    parser.add_argument("--maximum-input-tokens-per-call", type=int, required=True)
    parser.add_argument("--backend", default=SCENARIO_BACKEND)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    stage = ScenarioStage(args.stage)
    if (stage == ScenarioStage.CALIBRATION) != (args.use_case_id is None):
        raise ValueError("calibration omits --use-case-id; evaluation requires exactly one use case")
    expected_name = "calibration_cost_report.json" if stage == ScenarioStage.CALIBRATION else f"{args.use_case_id}_cost_report.json"
    if args.output.resolve() != (OUTPUT_ROOT / expected_name).resolve():
        raise ValueError("scenario-generation cost reports must use the fixed V0.9.0 checkpoint path")
    if args.output.exists():
        raise FileExistsError("the scenario-generation cost report already exists and cannot be replaced")
    seed_path = SEED_ROOT / "scenario_generation_seeds.json"
    schema_path = SEED_ROOT / "scenario_generation_seed_schema.json"
    seed = load_and_validate_seed(seed_path, schema_path)
    if args.use_case_id is not None and args.use_case_id not in {item.use_case_id for item in seed.use_cases}:
        raise ValueError("scenario-generation cost report references an unknown use case")
    catalog = load_model_catalog()
    model_ids = [catalog.scenario_generator_model.model_id, catalog.scenario_reviewer_model.model_id]
    all_pricing = read_model_json(args.pricing, PricingAssumptionInput).models
    if not set(model_ids).issubset(all_pricing):
        raise ValueError("pricing input must cover the configured scenario generator and reviewer")
    pricing = {model_id: all_pricing[model_id] for model_id in model_ids}
    scenario_count, base_generation, base_review, worst_generation, worst_review = _call_counts(stage)
    maximum_output_tokens = STRUCTURED_MAX_OUTPUT_TOKENS
    base_cost = _role_cost(
        base_generation,
        args.maximum_input_tokens_per_call,
        maximum_output_tokens,
        pricing[model_ids[0]],
    ) + _role_cost(base_review, args.maximum_input_tokens_per_call, maximum_output_tokens, pricing[model_ids[1]])
    worst_cost = _role_cost(
        worst_generation,
        args.maximum_input_tokens_per_call,
        maximum_output_tokens,
        pricing[model_ids[0]],
    ) + _role_cost(worst_review, args.maximum_input_tokens_per_call, maximum_output_tokens, pricing[model_ids[1]])
    payload = {
        "schema_version": "2.0.0",
        "stage": stage,
        "use_case_id": args.use_case_id,
        "backend_specification": args.backend,
        "seed_sha256": file_sha256(seed_path),
        "seed_schema_sha256": file_sha256(schema_path),
        "generator_model_id": model_ids[0],
        "reviewer_model_id": model_ids[1],
        "scenario_count": scenario_count,
        "base_generation_calls": base_generation,
        "base_review_calls": base_review,
        "worst_case_generation_calls": worst_generation,
        "worst_case_review_calls": worst_review,
        "maximum_input_tokens_per_call": args.maximum_input_tokens_per_call,
        "maximum_output_tokens_per_call": maximum_output_tokens,
        "base_cost_usd": base_cost.quantize(Decimal("0.01")),
        "worst_case_cost_usd": worst_cost.quantize(Decimal("0.01")),
        "pricing_assumptions": _pricing_payload(pricing),
        "generated_at": datetime.now(timezone.utc),
    }
    report = ScenarioGenerationCostReport.model_validate({**payload, "report_sha256": artifact_sha256(payload)})
    write_model_json_atomic(args.output, report)
    print(f"Wrote scenario-generation cost report with ${report.worst_case_cost_usd} worst-case cost")


if __name__ == "__main__":
    main()
