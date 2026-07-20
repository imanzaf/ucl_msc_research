"""Create the mandatory call/count/token/cost report before paid main execution."""

from __future__ import annotations

import argparse
import math
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from src.data_models.common import artifact_sha256, file_sha256
from src.data_models.experiments import ExperimentConfig, RunUnit
from src.data_models.manifests import DryRunCostReport, PricingAssumptionInput
from src.experiments.layout import validate_experiment_path
from src.experiments.scenario_runner import validate_complete_run_plan
from src.paths import REPO_ROOT
from src.scenarios.word_count import count_words
from src.storage import read_model_json, read_model_jsonl, write_model_json_atomic


def parse_args() -> argparse.Namespace:
    """Parse run plan, frozen config, pricing assumptions, and output path."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-plan", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--pricing", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _estimate_tokens(word_count: int) -> int:
    """Conservatively convert English word counts to approximate provider tokens."""
    return math.ceil(word_count * 1.5)


def main() -> None:
    """Calculate exact calls and conservative per-model token/cost estimates offline."""
    args = parse_args()
    validate_experiment_path(args.config, REPO_ROOT, "config")
    validate_experiment_path(args.run_plan, REPO_ROOT, "checkpoint")
    validate_experiment_path(args.output, REPO_ROOT, "checkpoint")
    run_units = read_model_jsonl(args.run_plan, RunUnit)
    config = read_model_json(args.config, ExperimentConfig)
    validate_complete_run_plan(run_units, config.randomisation_seed)
    pricing = read_model_json(args.pricing, PricingAssumptionInput).models
    estimated_input_tokens = 0
    estimated_output_tokens = 0
    estimated_cost = Decimal("0")
    worst_case_input_tokens = 0
    worst_case_output_tokens = 0
    worst_case_cost = Decimal("0")
    attempts_per_response = config.retry_policy.max_retries + 1
    for run_unit in run_units:
        if run_unit.model_id not in pricing:
            raise ValueError(f"missing pricing assumption for {run_unit.model_id}")
        initial_input_words = sum(count_words(message.content) for message in run_unit.initial_request_messages)
        output_tokens_per_response = _estimate_tokens(run_unit.assigned_word_limit)
        maximum_output_tokens_per_attempt = max(512, run_unit.assigned_word_limit * 4)
        initial_input_tokens = _estimate_tokens(initial_input_words)
        follow_up_input_tokens = initial_input_tokens + output_tokens_per_response + _estimate_tokens(count_words(run_unit.follow_up_message.content))
        worst_follow_up_input_tokens = (
            initial_input_tokens + maximum_output_tokens_per_attempt + _estimate_tokens(count_words(run_unit.follow_up_message.content))
        )
        run_input_tokens = initial_input_tokens + follow_up_input_tokens
        run_output_tokens = output_tokens_per_response * 2
        worst_run_input_tokens = (initial_input_tokens + worst_follow_up_input_tokens) * attempts_per_response
        worst_run_output_tokens = maximum_output_tokens_per_attempt * 2 * attempts_per_response
        estimated_input_tokens += run_input_tokens
        estimated_output_tokens += run_output_tokens
        worst_case_input_tokens += worst_run_input_tokens
        worst_case_output_tokens += worst_run_output_tokens
        model_pricing = pricing[run_unit.model_id]
        estimated_cost += Decimal(run_input_tokens) * model_pricing.input_per_million_usd / Decimal("1000000")
        estimated_cost += Decimal(run_output_tokens) * model_pricing.output_per_million_usd / Decimal("1000000")
        worst_case_cost += Decimal(worst_run_input_tokens) * model_pricing.input_per_million_usd / Decimal("1000000")
        worst_case_cost += Decimal(worst_run_output_tokens) * model_pricing.output_per_million_usd / Decimal("1000000")
    pricing_assumptions = {f"{model_id}:input_per_million_usd": values.input_per_million_usd for model_id, values in pricing.items()}
    pricing_assumptions.update({f"{model_id}:output_per_million_usd": values.output_per_million_usd for model_id, values in pricing.items()})
    payload = {
        "schema_version": "1.0.0",
        "experiment_name": "risk_comm_v1",
        "run_plan_sha256": file_sha256(args.run_plan),
        "experiment_config_sha256": artifact_sha256(config),
        "pricing_file_sha256": file_sha256(args.pricing),
        "conversations": len(run_units),
        "agent_responses": len(run_units) * 2,
        "maximum_attempts_including_retries": len(run_units) * 2 * (config.retry_policy.max_retries + 1),
        "estimated_input_tokens": estimated_input_tokens,
        "estimated_output_tokens": estimated_output_tokens,
        "estimated_cost_usd": estimated_cost.quantize(Decimal("0.01")),
        "worst_case_input_tokens": worst_case_input_tokens,
        "worst_case_output_tokens": worst_case_output_tokens,
        "worst_case_cost_usd": worst_case_cost.quantize(Decimal("0.01")),
        "pricing_assumptions": pricing_assumptions,
        "generated_at": datetime.now(timezone.utc),
    }
    report = DryRunCostReport.model_validate({**payload, "report_sha256": artifact_sha256(payload)})
    write_model_json_atomic(args.output, report)
    print(
        f"Estimated {report.agent_responses} responses at ${report.estimated_cost_usd} base / "
        f"${report.worst_case_cost_usd} worst case; wrote {args.output}"
    )


if __name__ == "__main__":
    main()
