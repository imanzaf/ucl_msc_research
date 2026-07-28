"""Stage and publish the current reviewed set and manifest from one named run."""

from __future__ import annotations

import argparse
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple

from src.cli.commands.scenarios.build_manifest import accepted_manifest_output_path, build_accepted_scenario_manifest
from src.data_models.manifests import ScenarioManifestScope
from src.data_models.scenario_review import (
    AutomatedScenarioReview,
    ReviewDecision,
    RevisionCycleRecord,
    ScenarioAcceptanceRecord,
    ScenarioReviewHistory,
)
from src.data_models.scenarios import AcceptedScenario, CandidateScenario, LoadedScenarioSeedSet, ScenarioGenerationRunConfig, ScenarioHiddenDesign
from src.paths import (
    ACTIVE_SCENARIO_ACCEPTED_ROOT,
    ACTIVE_SCENARIO_INPUT_ROOT,
    ACTIVE_SCENARIO_QUERY_SCHEMA_SHA256,
    ACTIVE_SCENARIO_QUERY_SHA256,
    ACTIVE_SCENARIO_SEED_SCHEMA_SHA256,
    ACTIVE_SCENARIO_SEED_SHA256,
    scenario_generation_run_root,
)
from src.scenarios.acceptance import build_accepted_scenario, publish_accepted_scenario
from src.scenarios.run_resolution import current_researcher_review, current_scenario_artifacts, reviews_by_artifact_hash
from src.scenarios.seed_validation import load_and_validate_seed
from src.storage import read_model_json, read_model_jsonl, write_model_json_atomic


def validate_candidate_seed_ownership(candidate: CandidateScenario, seed: LoadedScenarioSeedSet) -> None:
    """Require candidate identity and researcher-owned fields to match the approved seed."""
    use_case = next((item for item in seed.use_cases if item.use_case_id == candidate.use_case_id), None)
    if use_case is None or candidate.scenario_id not in {replication.scenario_id for replication in use_case.replications}:
        raise ValueError("candidate scenario id is not present in its V2.0.0 task-family seed")
    replication = next(replication for replication in use_case.replications if replication.scenario_id == candidate.scenario_id)
    seed_owned_fields = {
        "deployment_context": use_case.deployment_context,
        "customer_messages": replication.customer_messages,
        "hidden_design": ScenarioHiddenDesign(
            decision_type=replication.decision_type,
            options=replication.options,
            owner_supporting_option=replication.owner_supporting_option,
            owner_benefit_mechanism=replication.owner_benefit_mechanism,
            presentation_order=replication.presentation_order,
        ),
    }
    if any(getattr(candidate, field_name) != value for field_name, value in seed_owned_fields.items()):
        raise ValueError("candidate seed-owned metadata differs from the approved V2.0.0 seed")


def _build_current_accepted_bundles(
    run_id: str,
    accepted_at: datetime,
    accepted_by: str,
    artifact_version: str,
) -> List[Tuple[AcceptedScenario, ScenarioReviewHistory, ScenarioAcceptanceRecord]]:
    """Resolve and validate every current accepted candidate in one named run."""
    run_root = scenario_generation_run_root(run_id)
    if not run_root.is_dir():
        raise FileNotFoundError(f"unknown scenario generation run: {run_id}")
    run_config = read_model_json(run_root / "run_config.json", ScenarioGenerationRunConfig)
    if (
        run_config.run_id != run_id
        or run_config.seed_sha256 != ACTIVE_SCENARIO_SEED_SHA256
        or run_config.seed_schema_sha256 != ACTIVE_SCENARIO_SEED_SCHEMA_SHA256
        or run_config.query_sha256 != ACTIVE_SCENARIO_QUERY_SHA256
        or run_config.query_schema_sha256 != ACTIVE_SCENARIO_QUERY_SCHEMA_SHA256
    ):
        raise ValueError("scenario publication run does not bind the active V2.0.0 scenario inputs")
    seed = load_and_validate_seed(
        seed_path=ACTIVE_SCENARIO_INPUT_ROOT / "scenario_generation_seeds.json",
        schema_path=ACTIVE_SCENARIO_INPUT_ROOT / "scenario_generation_seed_schema.json",
        query_path=ACTIVE_SCENARIO_INPUT_ROOT / "scenario_customer_queries.json",
        query_schema_path=ACTIVE_SCENARIO_INPUT_ROOT / "scenario_customer_queries_schema.json",
    )
    current = current_scenario_artifacts(run_root)
    reviews_by_hash = reviews_by_artifact_hash(run_root)
    if not current:
        raise ValueError(f"run {run_id} contains no generated scenarios")
    bundles: List[Tuple[AcceptedScenario, ScenarioReviewHistory, ScenarioAcceptanceRecord]] = []
    for scenario_id, artifact in sorted(current.items()):
        researcher_review = current_researcher_review(artifact, reviews_by_hash)
        if researcher_review is None or researcher_review.decision != ReviewDecision.ACCEPT:
            raise ValueError(f"current candidate does not have an exact researcher accept decision: {scenario_id}")
        validate_candidate_seed_ownership(artifact.candidate, seed)
        history = ScenarioReviewHistory(
            schema_version="3.3.0",
            scenario_id=scenario_id,
            automated_reviews=read_model_jsonl(artifact.automated_reviews_path, AutomatedScenarioReview),
            revisions=read_model_jsonl(artifact.revision_cycles_path, RevisionCycleRecord),
            researcher_reviews=[researcher_review],
        )
        acceptance_record, accepted = build_accepted_scenario(
            candidate=artifact.candidate,
            review_history=history,
            accepted_at=accepted_at,
            accepted_by=accepted_by,
            artifact_version=artifact_version,
        )
        bundles.append((accepted, history, acceptance_record))
    return bundles


def _stage_final_set(
    staging_root: Path,
    bundles: List[Tuple[AcceptedScenario, ScenarioReviewHistory, ScenarioAcceptanceRecord]],
    scope: ScenarioManifestScope,
    published_at: datetime,
    published_by: str,
) -> Path:
    """Stage existing bundles, new bundles, and the complete set manifest."""
    staged_accepted_root = staging_root / "accepted"
    if ACTIVE_SCENARIO_ACCEPTED_ROOT.exists():
        shutil.copytree(ACTIVE_SCENARIO_ACCEPTED_ROOT, staged_accepted_root)
    else:
        staged_accepted_root.mkdir(parents=True)
    for accepted, history, acceptance_record in bundles:
        publish_accepted_scenario(accepted, history, acceptance_record, staged_accepted_root)
    manifest = build_accepted_scenario_manifest(
        accepted_root=staged_accepted_root,
        scope=scope,
        published_by=published_by,
        published_at=published_at,
    )
    staged_manifest_path = staging_root / accepted_manifest_output_path(scope).name
    write_model_json_atomic(staged_manifest_path, manifest)
    return staged_manifest_path


def _promote_final_set(
    staging_root: Path,
    staged_manifest_path: Path,
    bundles: List[Tuple[AcceptedScenario, ScenarioReviewHistory, ScenarioAcceptanceRecord]],
    manifest_output_path: Path,
) -> None:
    """Promote staged bundles and manifest, rolling back ordinary write failures."""
    ACTIVE_SCENARIO_ACCEPTED_ROOT.mkdir(parents=True, exist_ok=True)
    promoted: List[Tuple[Path, Path]] = []
    try:
        for accepted, _, _ in bundles:
            source = staging_root / "accepted" / accepted.scenario_id
            destination = ACTIVE_SCENARIO_ACCEPTED_ROOT / accepted.scenario_id
            os.replace(source, destination)
            promoted.append((destination, source))
        os.replace(staged_manifest_path, manifest_output_path)
    except Exception:
        for destination, source in reversed(promoted):
            if destination.exists():
                os.replace(destination, source)
        raise


def main() -> None:
    """Publish current accepted scenarios and their set manifest in one command."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--scope", choices=[scope.value for scope in ScenarioManifestScope], required=True)
    parser.add_argument("--published-by", required=True)
    parser.add_argument("--artifact-version", default="v1")
    args = parser.parse_args()
    scope = ScenarioManifestScope(args.scope)
    manifest_output_path = accepted_manifest_output_path(scope)
    if manifest_output_path.exists():
        raise FileExistsError(f"accepted-set manifest is immutable and already exists: {manifest_output_path}")
    accepted_at = datetime.now(timezone.utc)
    bundles = _build_current_accepted_bundles(
        run_id=args.run_id,
        accepted_at=accepted_at,
        accepted_by=args.published_by,
        artifact_version=args.artifact_version,
    )
    existing = [accepted.scenario_id for accepted, _, _ in bundles if (ACTIVE_SCENARIO_ACCEPTED_ROOT / accepted.scenario_id).exists()]
    if existing:
        raise FileExistsError(f"accepted scenarios are immutable and already exist: {', '.join(existing)}")
    ACTIVE_SCENARIO_INPUT_ROOT.mkdir(parents=True, exist_ok=True)
    staging_root = Path(tempfile.mkdtemp(prefix=".scenario-publish.", dir=ACTIVE_SCENARIO_INPUT_ROOT))
    try:
        staged_manifest_path = _stage_final_set(
            staging_root=staging_root,
            bundles=bundles,
            scope=scope,
            published_at=accepted_at,
            published_by=args.published_by,
        )
        _promote_final_set(staging_root, staged_manifest_path, bundles, manifest_output_path)
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)
    print(
        f"Published {len(bundles)} current accepted bundles from run {args.run_id} " f"and wrote the {scope.value} manifest to {manifest_output_path}"
    )


if __name__ == "__main__":
    main()
