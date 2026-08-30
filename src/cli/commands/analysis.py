"""Confirmatory and descriptive analysis commands."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

from src.analysis.commercial_interest import (
    CommercialInterestContrast,
    CommercialInterestObservation,
    commercial_interest_observations,
    paired_instruction_contrasts,
    summarize_commercial_interest_contrasts,
)
from src.analysis.confirmatory import TEST_NAMES_BY_FAMILY, budget_scores_from_outcomes, run_confirmatory_tests, user_state_scores_from_outcomes
from src.analysis.option_first import label_forced_choice_scores, summarize_forced_choices
from src.models.enums import ExperimentKind
from src.models.scoring import ResponseOutcomesRecord
from src.paths import EXPERIMENT_ROOT, scoring_paths
from src.storage import read_json, read_jsonl, write_json, write_jsonl


def _confirmatory(arguments: List[str]) -> None:
    """Run the seven directional tests using research-question-specific families."""
    parser = argparse.ArgumentParser(prog="risk-comm analysis confirmatory")
    parser.add_argument(
        "--user-state-response-scores",
        type=Path,
        default=scoring_paths(ExperimentKind.USER_STATE.value)["response_scores"],
    )
    parser.add_argument(
        "--budget-response-scores",
        type=Path,
        default=scoring_paths(ExperimentKind.INFORMATION_BUDGET.value)["response_scores"],
    )
    parser.add_argument(
        "--commercial-contrasts",
        type=Path,
        default=scoring_paths(ExperimentKind.COMMERCIAL_INTEREST.value)["paired_contrasts"],
    )
    parser.add_argument("--output", type=Path, default=EXPERIMENT_ROOT / "confirmatory_results.json")
    parser.add_argument("--bootstrap-iterations", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=410506)
    args = parser.parse_args(arguments)
    user_outcomes = [ResponseOutcomesRecord.model_validate(record) for record in read_jsonl(args.user_state_response_scores)]
    budget_outcomes = [ResponseOutcomesRecord.model_validate(record) for record in read_jsonl(args.budget_response_scores)]
    commercial_records = read_json(args.commercial_contrasts)
    commercial_contrasts = [CommercialInterestContrast.model_validate(record) for record in commercial_records["contrasts"]]
    tests = run_confirmatory_tests(
        user_state_scores_from_outcomes(user_outcomes),
        budget_scores_from_outcomes(budget_outcomes),
        commercial_contrasts,
        args.bootstrap_iterations,
        args.seed,
    )
    family_sizes = {family.value: len(test_names) for family, test_names in TEST_NAMES_BY_FAMILY.items()}
    write_json(args.output, {"schema_version": "4.0.1", "holm_family_sizes": family_sizes, "tests": tests})
    print(f"Wrote {len(tests)} primary tests across Holm families {family_sizes} to {args.output}")


def _commercial_interest(arguments: List[str]) -> None:
    """Write matched treatment-minus-control contrasts for every supplied outcome."""
    parser = argparse.ArgumentParser(prog="risk-comm analysis commercial-interest")
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
            "reporting_mode": "mixed_confirmatory_and_descriptive",
            "contrast": "protect_commercial_interests_minus_control",
            "summaries": summarize_commercial_interest_contrasts(contrasts),
            "summaries_by_affect": summarize_commercial_interest_contrasts(contrasts, by_affect=True),
            "contrasts": contrasts,
        },
    )
    print(f"Wrote {len(contrasts)} paired commercial-interest contrasts to {args.output}")


def _commercial_interest_observations(arguments: List[str]) -> None:
    """Flatten response scores into complete matched commercial-interest observations."""
    parser = argparse.ArgumentParser(prog="risk-comm analysis commercial-interest-observations")
    paths = scoring_paths(ExperimentKind.COMMERCIAL_INTEREST.value)
    parser.add_argument("--response-outcomes", type=Path, default=paths["response_scores"])
    parser.add_argument("--output", type=Path, default=paths["outcome_observations"])
    args = parser.parse_args(arguments)
    scores = [ResponseOutcomesRecord.model_validate(record) for record in read_jsonl(args.response_outcomes)]
    observations = commercial_interest_observations(scores)
    write_jsonl(args.output, observations)
    print(f"Wrote {len(observations)} complete paired commercial-interest observations to {args.output}")


def _option_first_choices(arguments: List[str]) -> None:
    """Write forced-choice-specific labels and a descriptive summary from frozen response scores."""
    parser = argparse.ArgumentParser(prog="risk-comm analysis option-first-choices")
    paths = scoring_paths(ExperimentKind.OPTION_FIRST.value)
    parser.add_argument("--response-scores", type=Path, default=paths["response_scores"])
    parser.add_argument("--labels-output", type=Path, default=paths["forced_choice_labels"])
    parser.add_argument("--summary-output", type=Path, default=paths["forced_choice_summary"])
    args = parser.parse_args(arguments)
    scores = [ResponseOutcomesRecord.model_validate(record) for record in read_jsonl(args.response_scores)]
    labels = label_forced_choice_scores(scores)
    summary = summarize_forced_choices(labels, scores)
    write_jsonl(args.labels_output, labels)
    write_json(args.summary_output, summary)
    print(f"Wrote {len(labels)} forced-choice labels to {args.labels_output}")
    print(f"Wrote forced-choice summary to {args.summary_output}")


def main(command: str, arguments: List[str]) -> None:
    """Dispatch one analysis subcommand."""
    handlers = {
        "confirmatory": _confirmatory,
        "commercial-interest-observations": _commercial_interest_observations,
        "commercial-interest": _commercial_interest,
        "option-first-choices": _option_first_choices,
    }
    handlers[command](arguments)
