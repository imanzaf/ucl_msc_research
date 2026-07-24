"""Build and atomically publish one fully reviewed V0.10.0 scenario bundle."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from src.data_models.scenario_review import AutomatedScenarioReview, ResearcherScenarioReview, RevisionCycleRecord, ScenarioReviewHistory
from src.data_models.scenarios import CandidateScenario, ScenarioSeedSet, V10HiddenDesign
from src.paths import ACTIVE_SCENARIO_ACCEPTED_ROOT, ACTIVE_SCENARIO_GENERATION_ROOT, ACTIVE_SCENARIO_INPUT_ROOT, ACTIVE_SCENARIO_REVIEW_ROOT
from src.scenarios.acceptance import build_accepted_scenario, publish_accepted_scenario
from src.scenarios.seed_validation import load_and_validate_seed
from src.storage import read_model_json, read_model_jsonl


def validate_candidate_seed_ownership(candidate: CandidateScenario, seed: ScenarioSeedSet) -> None:
    """Require candidate identity and researcher-owned fields to match the approved seed."""
    use_case = next((item for item in seed.use_cases if item.use_case_id == candidate.use_case_id), None)
    if use_case is None or candidate.scenario_id not in {replication.scenario_id for replication in use_case.replications}:
        raise ValueError("candidate scenario id is not present in its V0.10.0 task-family seed")
    replication = next(replication for replication in use_case.replications if replication.scenario_id == candidate.scenario_id)
    seed_owned_fields = {
        "deployment_context": use_case.deployment_context,
        "customer_messages": replication.customer_messages,
        "hidden_design": V10HiddenDesign(
            decision_type=replication.decision_type,
            options=replication.options,
            customer_supporting_option=replication.customer_supporting_option,
            owner_supporting_option=replication.owner_supporting_option,
            owner_benefit_mechanism=replication.owner_benefit_mechanism,
            presentation_order=replication.presentation_order,
        ),
    }
    if any(getattr(candidate, field_name) != value for field_name, value in seed_owned_fields.items()):
        raise ValueError("candidate seed-owned metadata differs from the approved V0.10.0 seed")


def main() -> None:
    """Require complete delayed review and publish one immutable accepted bundle."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--automated-reviews", type=Path, required=True)
    parser.add_argument("--revision-cycles", type=Path, required=True)
    parser.add_argument("--researcher-reviews", type=Path, required=True)
    parser.add_argument("--accepted-root", type=Path, required=True)
    parser.add_argument("--accepted-by", required=True)
    parser.add_argument("--artifact-version", default="v1")
    args = parser.parse_args()
    expected_accepted_root = ACTIVE_SCENARIO_ACCEPTED_ROOT.resolve()
    if args.accepted_root.resolve() != expected_accepted_root:
        raise ValueError("accepted scenarios must publish only under the active V0.10.0 accepted root")

    candidate = read_model_json(args.candidate, CandidateScenario)
    candidate_root = ACTIVE_SCENARIO_GENERATION_ROOT / candidate.scenario_id
    expected_generated_paths = {
        "candidate": candidate_root / "candidate.json",
        "automated_reviews": candidate_root / "automated_reviews.jsonl",
        "revision_cycles": candidate_root / "revision_cycles.jsonl",
    }
    supplied_generated_paths = {
        "candidate": args.candidate,
        "automated_reviews": args.automated_reviews,
        "revision_cycles": args.revision_cycles,
    }
    if any(supplied_generated_paths[name].resolve() != path.resolve() for name, path in expected_generated_paths.items()):
        raise ValueError("scenario publication must use the fixed V0.10.0 generated-candidate bundle paths")
    expected_researcher_review = ACTIVE_SCENARIO_REVIEW_ROOT / "scenario_reviews.jsonl"
    if args.researcher_reviews.resolve() != expected_researcher_review.resolve():
        raise ValueError("scenario publication must use the append-only researcher review store")
    seed = load_and_validate_seed(
        seed_path=ACTIVE_SCENARIO_INPUT_ROOT / "scenario_generation_seeds.json",
        schema_path=ACTIVE_SCENARIO_INPUT_ROOT / "scenario_generation_seed_schema.json",
    )
    validate_candidate_seed_ownership(candidate, seed)
    history = ScenarioReviewHistory(
        schema_version="3.0.0",
        scenario_id=candidate.scenario_id,
        automated_reviews=read_model_jsonl(args.automated_reviews, AutomatedScenarioReview),
        revisions=read_model_jsonl(args.revision_cycles, RevisionCycleRecord),
        researcher_reviews=[
            review for review in read_model_jsonl(args.researcher_reviews, ResearcherScenarioReview) if review.scenario_id == candidate.scenario_id
        ],
    )
    acceptance_record, accepted = build_accepted_scenario(
        candidate=candidate,
        review_history=history,
        accepted_at=datetime.now(timezone.utc),
        accepted_by=args.accepted_by,
        artifact_version=args.artifact_version,
    )
    publish_accepted_scenario(accepted, history, acceptance_record, expected_accepted_root)
    print(f"Published immutable accepted bundle {accepted.scenario_id} at {expected_accepted_root}")


if __name__ == "__main__":
    main()
