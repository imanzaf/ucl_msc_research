"""Build and atomically publish one fully reviewed V0.5.2 scenario bundle."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from src.data_models.scenario_review import AutomatedScenarioReview, ResearcherScenarioReview, RevisionCycleRecord, ScenarioReviewHistory
from src.data_models.scenarios import CandidateScenario, MinimalCompleteResponse
from src.paths import REPO_ROOT
from src.scenarios.acceptance import build_accepted_scenario, publish_accepted_scenario
from src.storage import read_model_json, read_model_jsonl


def main() -> None:
    """Require complete delayed review and publish one immutable accepted bundle."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--automated-reviews", type=Path, required=True)
    parser.add_argument("--revision-cycles", type=Path, required=True)
    parser.add_argument("--researcher-reviews", type=Path, required=True)
    parser.add_argument("--approved-minimal-response", type=Path, required=True)
    parser.add_argument("--accepted-root", type=Path, required=True)
    parser.add_argument("--accepted-by", required=True)
    parser.add_argument("--artifact-version", default="v1")
    args = parser.parse_args()
    expected_accepted_root = (REPO_ROOT / "data/inputs/scenarios/v0.5.2/accepted").resolve()
    if args.accepted_root.resolve() != expected_accepted_root:
        raise ValueError("accepted scenarios must publish only under data/inputs/scenarios/v0.5.2/accepted")

    candidate = read_model_json(args.candidate, CandidateScenario)
    history = ScenarioReviewHistory(
        schema_version="2.0.0",
        scenario_id=candidate.scenario_id,
        automated_reviews=read_model_jsonl(args.automated_reviews, AutomatedScenarioReview),
        revisions=read_model_jsonl(args.revision_cycles, RevisionCycleRecord),
        researcher_reviews=[
            review for review in read_model_jsonl(args.researcher_reviews, ResearcherScenarioReview) if review.scenario_id == candidate.scenario_id
        ],
    )
    approved_minimal_response = read_model_json(args.approved_minimal_response, MinimalCompleteResponse)
    acceptance_record, accepted = build_accepted_scenario(
        candidate=candidate,
        review_history=history,
        approved_minimal_response=approved_minimal_response,
        accepted_at=datetime.now(timezone.utc),
        accepted_by=args.accepted_by,
        artifact_version=args.artifact_version,
    )
    publish_accepted_scenario(accepted, history, acceptance_record, expected_accepted_root)
    print(f"Published immutable accepted bundle {accepted.scenario_id} at {expected_accepted_root}")


if __name__ == "__main__":
    main()
