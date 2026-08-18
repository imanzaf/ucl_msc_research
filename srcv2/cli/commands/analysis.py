"""Confirmatory and descriptive analysis commands."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

from srcv2.analysis.commercial_interest import (
    CommercialInterestObservation,
    commercial_interest_observations,
    paired_instruction_contrasts,
    summarize_commercial_interest_contrasts,
)
from srcv2.analysis.confirmatory import BudgetScore, UserStateScore, run_confirmatory_tests
from srcv2.analysis.descriptive import GroupObservation, summarize_groups
from srcv2.models.enums import ExperimentKind
from srcv2.models.scoring import ResponseOutcomesRecord
from srcv2.paths import scoring_paths
from srcv2.storage import read_jsonl, write_json, write_jsonl


def _confirmatory(arguments: List[str]) -> None:
    """Run the two prespecified tests from frozen score files."""
    parser = argparse.ArgumentParser(prog="risk-comm-v2 analysis confirmatory")
    parser.add_argument("--user-state-scores", type=Path, required=True)
    parser.add_argument("--budget-scores", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bootstrap-iterations", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=410506)
    args = parser.parse_args(arguments)
    user_scores = [UserStateScore.model_validate(record) for record in read_jsonl(args.user_state_scores)]
    budget_scores = [BudgetScore.model_validate(record) for record in read_jsonl(args.budget_scores)]
    tests = run_confirmatory_tests(user_scores, budget_scores, args.bootstrap_iterations, args.seed)
    write_json(args.output, {"schema_version": "4.0.0", "holm_family_size": 2, "tests": tests})
    print(f"Wrote two Holm-corrected confirmatory tests to {args.output}")


def _describe(arguments: List[str]) -> None:
    """Write grouped descriptive summaries in label rather than outcome order."""
    parser = argparse.ArgumentParser(prog="risk-comm-v2 analysis describe")
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(arguments)
    observations = [GroupObservation.model_validate(record) for record in read_jsonl(args.observations)]
    summaries = summarize_groups(observations)
    write_json(args.output, {"schema_version": "4.0.0", "reporting_mode": "descriptive_only", "summaries": summaries})
    print(f"Wrote {len(summaries)} descriptive group summaries to {args.output}")


def _commercial_interest(arguments: List[str]) -> None:
    """Write matched treatment-minus-control contrasts for every supplied outcome."""
    parser = argparse.ArgumentParser(prog="risk-comm-v2 analysis commercial-interest")
    paths = scoring_paths(ExperimentKind.COMMERCIAL_INTEREST.value)
    parser.add_argument("--observations", type=Path, default=paths["outcome_observations"])
    parser.add_argument("--output", type=Path, default=paths["paired_contrasts"])
    args = parser.parse_args(arguments)
    observations = [CommercialInterestObservation.model_validate(record) for record in read_jsonl(args.observations)]
    contrasts = paired_instruction_contrasts(observations)
    write_json(
        args.output,
        {
            "schema_version": "4.0.0",
            "reporting_mode": "descriptive_secondary",
            "contrast": "protect_commercial_interests_minus_control",
            "summaries": summarize_commercial_interest_contrasts(contrasts),
            "summaries_by_affect": summarize_commercial_interest_contrasts(contrasts, by_affect=True),
            "contrasts": contrasts,
        },
    )
    print(f"Wrote {len(contrasts)} paired commercial-interest contrasts to {args.output}")


def _commercial_interest_observations(arguments: List[str]) -> None:
    """Flatten response scores into complete matched commercial-interest observations."""
    parser = argparse.ArgumentParser(prog="risk-comm-v2 analysis commercial-interest-observations")
    paths = scoring_paths(ExperimentKind.COMMERCIAL_INTEREST.value)
    parser.add_argument("--response-outcomes", type=Path, default=paths["response_scores"])
    parser.add_argument("--output", type=Path, default=paths["outcome_observations"])
    args = parser.parse_args(arguments)
    scores = [ResponseOutcomesRecord.model_validate(record) for record in read_jsonl(args.response_outcomes)]
    observations = commercial_interest_observations(scores)
    write_jsonl(args.output, observations)
    print(f"Wrote {len(observations)} complete paired commercial-interest observations to {args.output}")


def main(command: str, arguments: List[str]) -> None:
    """Dispatch one analysis subcommand."""
    handlers = {
        "confirmatory": _confirmatory,
        "describe": _describe,
        "commercial-interest-observations": _commercial_interest_observations,
        "commercial-interest": _commercial_interest,
    }
    handlers[command](arguments)
