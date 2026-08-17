"""Read-only scenario and judge-review status commands."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import List

from srcv2.models.scenarios import AcceptedScenario
from srcv2.models.scoring import FrozenJudgeContract, JudgeCallRecord, JudgePilotSample
from srcv2.paths import SCENARIO_ROOT
from srcv2.scenarios.review import ResearcherReviewRecord, accept_curated_scenarios, publish_scenarios
from srcv2.storage import read_json, read_jsonl, write_jsonl


def _scenario_status(arguments: List[str]) -> None:
    """Summarize one-pass scenario review records without changing them."""
    parser = argparse.ArgumentParser(prog="risk-comm-v2 review scenario-status")
    parser.add_argument("--reviews", type=Path, required=True)
    args = parser.parse_args(arguments)
    reviews = [ResearcherReviewRecord.model_validate(record) for record in read_jsonl(args.reviews)]
    counts = Counter(review.disposition.value for review in reviews)
    print(f"review records: {len(reviews)}")
    for state, count in sorted(counts.items()):
        print(f"{state}: {count}")


def _accept_curated_scenarios(arguments: List[str]) -> None:
    """Record explicit researcher acceptance of the complete curated corpus."""
    parser = argparse.ArgumentParser(prog="risk-comm-v2 review accept-curated-scenarios")
    parser.add_argument("--scenarios", type=Path, default=SCENARIO_ROOT / "pending_scenarios.jsonl")
    parser.add_argument("--researcher-id", required=True)
    parser.add_argument("--rationale", required=True)
    parser.add_argument("--output", type=Path, default=SCENARIO_ROOT / "reviews.jsonl")
    parser.add_argument("--confirm-accept-all", action="store_true", required=True)
    args = parser.parse_args(arguments)
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite existing review records: {args.output}")
    scenarios = [AcceptedScenario.model_validate(record) for record in read_jsonl(args.scenarios)]
    reviews = accept_curated_scenarios(scenarios, args.researcher_id, args.rationale)
    write_jsonl(args.output, reviews)
    print(f"Accepted {len(reviews)} curated scenarios in {args.output}")


def _judge_status(arguments: List[str]) -> None:
    """Summarize the pilot sample, raw results, and optional contract freeze."""
    parser = argparse.ArgumentParser(prog="risk-comm-v2 review judge-status")
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--frozen-contract", type=Path)
    args = parser.parse_args(arguments)
    sample = JudgePilotSample.model_validate(read_json(args.sample))
    records = [JudgeCallRecord.model_validate(record) for record in read_jsonl(args.results)]
    print(f"pilot responses: {len(sample.response_ids)}")
    print(f"judge calls: {len(records)}")
    print(f"structurally invalid: {sum(not record.structurally_valid for record in records)}")
    if args.frozen_contract is not None:
        contract = FrozenJudgeContract.model_validate(read_json(args.frozen_contract))
        print(f"contract: {contract.state}")


def _publish_scenarios(arguments: List[str]) -> None:
    """Publish reviewed scenarios only when each has one accepted disposition."""
    parser = argparse.ArgumentParser(prog="risk-comm-v2 review publish-scenarios")
    parser.add_argument("--scenarios", type=Path, required=True)
    parser.add_argument("--reviews", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(arguments)
    scenarios = [AcceptedScenario.model_validate(record) for record in read_jsonl(args.scenarios)]
    reviews = [ResearcherReviewRecord.model_validate(record) for record in read_jsonl(args.reviews)]
    published = publish_scenarios(scenarios, reviews)
    write_jsonl(args.output, published)
    print(f"Published {len(published)} accepted scenarios to {args.output}")


def main(command: str, arguments: List[str]) -> None:
    """Dispatch one review-status subcommand."""
    handlers = {
        "scenario-status": _scenario_status,
        "accept-curated-scenarios": _accept_curated_scenarios,
        "publish-scenarios": _publish_scenarios,
        "judge-status": _judge_status,
    }
    handlers[command](arguments)
