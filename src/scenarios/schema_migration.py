"""Migrate approved scenarios into the current option-centric schema."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

from src.data_models.common import artifact_sha256
from src.data_models.scenario_review import (
    AutomatedScenarioReview,
    ResearcherScenarioReview,
    ReviewDecision,
    RevisionCycleRecord,
    ScenarioAcceptanceRecord,
    ScenarioPipelineDisposition,
    ScenarioReviewHistory,
)
from src.data_models.scenarios import (
    AcceptedScenario,
    CandidateScenario,
    ScenarioGenerationInvocationConfig,
    ScenarioGenerationRunConfig,
    ScenarioMigrationEntry,
    ScenarioMigrationManifest,
    ScenarioStage,
)
from src.paths import (
    ACTIVE_SCENARIO_GENERATION_VERSION,
    ACTIVE_SCENARIO_QUERY_SCHEMA_SHA256,
    ACTIVE_SCENARIO_QUERY_SHA256,
    ACTIVE_SCENARIO_SEED_SCHEMA_SHA256,
    ACTIVE_SCENARIO_SEED_SHA256,
    ACTIVE_SCENARIO_SEED_VERSION,
    ACTIVE_SCENARIO_SET_ID,
    scenario_generation_round_id,
)
from src.scenarios.acceptance import validate_accepted_bundle
from src.scenarios.candidate_compatibility import read_accepted_scenario, read_candidate_scenario
from src.scenarios.run_resolution import CurrentScenarioArtifact, current_scenario_artifacts, run_researcher_reviews
from src.storage import read_model_json, read_model_jsonl, write_model_json_atomic, write_models_jsonl_atomic

COMPATIBLE_SOURCE_PROTOCOL_VERSIONS = {"v1.0.6", "v1.0.7", "v1.0.8", "v1.0.9"}


def _validate_source_run(source_run_root: Path) -> str:
    """Authenticate one compatible source run against the active scenario seed."""
    config_path = source_run_root / "run_config.json"
    if not config_path.is_file():
        raise FileNotFoundError(f"source run has no run config: {source_run_root}")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    expected_identity = {
        "schema_version": "2.0.0",
        "run_id": source_run_root.name,
        "seed_version": ACTIVE_SCENARIO_SEED_VERSION,
        "scenario_set_id": ACTIVE_SCENARIO_SET_ID,
        "seed_sha256": ACTIVE_SCENARIO_SEED_SHA256,
        "seed_schema_sha256": ACTIVE_SCENARIO_SEED_SCHEMA_SHA256,
        "query_sha256": ACTIVE_SCENARIO_QUERY_SHA256,
        "query_schema_sha256": ACTIVE_SCENARIO_QUERY_SCHEMA_SHA256,
    }
    if any(config.get(field_name) != expected_value for field_name, expected_value in expected_identity.items()):
        raise ValueError(f"source run does not match the active scenario seed: {source_run_root.name}")
    if config.get("generation_protocol_version") not in COMPATIBLE_SOURCE_PROTOCOL_VERSIONS:
        raise ValueError(f"source run uses an incompatible generation protocol: {source_run_root.name}")
    return source_run_root.name


def _approved_source_artifacts(
    source_run_roots: List[Path],
) -> Dict[str, Tuple[str, CurrentScenarioArtifact, str, ResearcherScenarioReview]]:
    """Select the newest accepted source artifact for every reviewed scenario."""
    selected: Dict[str, Tuple[str, CurrentScenarioArtifact, str, ResearcherScenarioReview]] = {}
    for source_run_root in source_run_roots:
        source_run_id = _validate_source_run(source_run_root)
        reviews_by_source_hash = {review.reviewed_artifact_sha256: review for review in run_researcher_reviews(source_run_root)}
        for scenario_id, artifact in current_scenario_artifacts(source_run_root).items():
            raw_payload = json.loads(artifact.candidate_path.read_text(encoding="utf-8"))
            source_candidate_sha256 = raw_payload.get("candidate_sha256")
            if not isinstance(source_candidate_sha256, str):
                raise ValueError(f"source candidate has no digest: {artifact.candidate_path}")
            researcher_review = reviews_by_source_hash.get(source_candidate_sha256)
            if researcher_review is None or researcher_review.decision != ReviewDecision.ACCEPT:
                continue
            selected[scenario_id] = (source_run_id, artifact, source_candidate_sha256, researcher_review)
    expected_ids = {f"CF{index:03d}_C1" for index in range(1, 11)}
    if set(selected) != expected_ids:
        missing = ", ".join(sorted(expected_ids - set(selected)))
        raise ValueError(f"approved source runs do not cover the complete C1 set: {missing}")
    return selected


def _migrated_automated_review(
    artifact: CurrentScenarioArtifact,
    source_candidate_sha256: str,
    migrated_candidate_sha256: str,
) -> Tuple[AutomatedScenarioReview, str]:
    """Rebind the final source automated review to the migrated candidate digest."""
    source_reviews = read_model_jsonl(artifact.automated_reviews_path, AutomatedScenarioReview)
    current_reviews = [review for review in source_reviews if review.reviewed_artifact_sha256 == source_candidate_sha256]
    if len(current_reviews) != 1:
        raise ValueError(f"source candidate requires exactly one current automated review: {artifact.candidate.scenario_id}")
    source_review = current_reviews[0]
    payload = source_review.model_dump(mode="json")
    payload["reviewed_artifact_sha256"] = migrated_candidate_sha256
    return AutomatedScenarioReview.model_validate(payload), artifact_sha256(source_review)


def _migrated_researcher_review(
    source_review: ResearcherScenarioReview,
    migrated_candidate_sha256: str,
) -> ResearcherScenarioReview:
    """Rebind one accepted researcher review and emit the reduced diagnostic schema."""
    payload = source_review.model_dump(mode="json")
    payload["schema_version"] = "3.4.0"
    payload["reviewed_artifact_sha256"] = migrated_candidate_sha256
    return ResearcherScenarioReview.model_validate(payload)


def _migrated_disposition(
    artifact: CurrentScenarioArtifact,
    source_candidate_sha256: str,
    migrated_candidate_sha256: str,
) -> ScenarioPipelineDisposition:
    """Rebind the source terminal disposition to the migrated candidate digest."""
    source = read_model_json(artifact.terminal_decision_path, ScenarioPipelineDisposition)
    if source.candidate_sha256 != source_candidate_sha256:
        raise ValueError(f"source terminal disposition does not bind its candidate: {source.scenario_id}")
    payload = source.model_dump(mode="json")
    payload["candidate_sha256"] = migrated_candidate_sha256
    return ScenarioPipelineDisposition.model_validate(payload)


def migrate_approved_calibration_runs(
    source_run_roots: List[Path],
    target_run_root: Path,
    migrated_at: datetime,
) -> ScenarioMigrationManifest:
    """Create a complete current-schema run from the newest approved source candidates."""
    if migrated_at.tzinfo is None:
        raise ValueError("migration timestamp must be timezone-aware")
    if target_run_root.exists():
        raise FileExistsError(f"target migration run already exists: {target_run_root}")
    approved = _approved_source_artifacts(source_run_roots)
    target_run_root.parent.mkdir(parents=True, exist_ok=True)
    temporary_root = Path(tempfile.mkdtemp(prefix=f".{target_run_root.name}.", dir=target_run_root.parent))
    try:
        run_config = ScenarioGenerationRunConfig(
            schema_version="2.0.0",
            run_id=target_run_root.name,
            seed_version=ACTIVE_SCENARIO_SEED_VERSION,
            generation_protocol_version=ACTIVE_SCENARIO_GENERATION_VERSION,
            scenario_set_id=ACTIVE_SCENARIO_SET_ID,
            seed_sha256=ACTIVE_SCENARIO_SEED_SHA256,
            seed_schema_sha256=ACTIVE_SCENARIO_SEED_SCHEMA_SHA256,
            query_sha256=ACTIVE_SCENARIO_QUERY_SHA256,
            query_schema_sha256=ACTIVE_SCENARIO_QUERY_SCHEMA_SHA256,
            created_at=migrated_at,
        )
        write_model_json_atomic(temporary_root / "run_config.json", run_config)
        round_id = scenario_generation_round_id(migrated_at)
        round_root = temporary_root / round_id
        invocation = ScenarioGenerationInvocationConfig(
            schema_version="1.0.0",
            run_id=target_run_root.name,
            invocation_id=round_id,
            stage=ScenarioStage.CALIBRATION,
            scenario_ids=sorted(approved),
            backend="src.scenarios.schema_migration:migrate_approved_calibration_runs",
            created_at=migrated_at,
        )
        write_model_json_atomic(round_root / "invocation_config.json", invocation)

        migrated_reviews: List[ResearcherScenarioReview] = []
        entries: List[ScenarioMigrationEntry] = []
        for scenario_id, (source_run_id, artifact, source_candidate_sha256, researcher_review) in sorted(approved.items()):
            migrated_candidate: CandidateScenario = artifact.candidate
            automated_review, source_automated_review_sha256 = _migrated_automated_review(
                artifact,
                source_candidate_sha256,
                migrated_candidate.candidate_sha256,
            )
            migrated_researcher_review = _migrated_researcher_review(
                researcher_review,
                migrated_candidate.candidate_sha256,
            )
            disposition = _migrated_disposition(
                artifact,
                source_candidate_sha256,
                migrated_candidate.candidate_sha256,
            )
            scenario_root = round_root / "scenarios" / scenario_id
            write_model_json_atomic(scenario_root / "candidate.json", migrated_candidate)
            write_models_jsonl_atomic(scenario_root / "automated_reviews.jsonl", [automated_review])
            write_models_jsonl_atomic(scenario_root / "revision_cycles.jsonl", [])
            write_model_json_atomic(scenario_root / "terminal_decision.json", disposition)
            migrated_reviews.append(migrated_researcher_review)
            entries.append(
                ScenarioMigrationEntry(
                    scenario_id=scenario_id,
                    source_run_id=source_run_id,
                    source_round_id=artifact.round_id,
                    source_candidate_sha256=source_candidate_sha256,
                    migrated_candidate_sha256=migrated_candidate.candidate_sha256,
                    researcher_review_id=migrated_researcher_review.review_id,
                    source_automated_review_sha256=source_automated_review_sha256,
                )
            )
        write_models_jsonl_atomic(temporary_root / "researcher_review" / "scenario_reviews.jsonl", migrated_reviews)
        manifest_payload = {
            "schema_version": "1.0.0",
            "target_run_id": target_run_root.name,
            "source_run_ids": sorted({entry.source_run_id for entry in entries}),
            "entries": entries,
            "migrated_at": migrated_at,
        }
        manifest = ScenarioMigrationManifest.model_validate(
            {
                **manifest_payload,
                "manifest_sha256": artifact_sha256(manifest_payload),
            }
        )
        write_model_json_atomic(temporary_root / "migration_manifest.json", manifest)
        os.replace(temporary_root, target_run_root)
        return manifest
    finally:
        if temporary_root.exists():
            shutil.rmtree(temporary_root)


def migrate_accepted_bundle(source_bundle_root: Path, target_bundle_root: Path) -> AcceptedScenario:
    """Write one hash-consistent current-schema copy of an accepted bundle."""
    accepted = read_accepted_scenario(source_bundle_root / "accepted_scenario.json")
    source_history = read_model_json(source_bundle_root / "review_history.json", ScenarioReviewHistory)
    history_payload = source_history.model_dump(mode="json")
    history_payload["schema_version"] = "3.4.0"
    history = ScenarioReviewHistory.model_validate(history_payload)
    history_sha256 = artifact_sha256(history)

    source_acceptance = read_model_json(source_bundle_root / "acceptance_record.json", ScenarioAcceptanceRecord)
    acceptance_payload = source_acceptance.model_dump(mode="json", exclude={"record_sha256"})
    acceptance_payload["review_history_sha256"] = history_sha256
    acceptance = ScenarioAcceptanceRecord.model_validate(
        {
            **acceptance_payload,
            "record_sha256": artifact_sha256(acceptance_payload),
        }
    )

    accepted_payload = accepted.model_dump(mode="json", exclude={"artifact_sha256"})
    accepted_payload["review_history_sha256"] = history_sha256
    accepted_payload["acceptance_record_sha256"] = acceptance.record_sha256
    migrated = AcceptedScenario.model_validate(
        {
            **accepted_payload,
            "artifact_sha256": artifact_sha256(accepted_payload),
        }
    )
    validate_accepted_bundle(migrated, history, acceptance)
    write_model_json_atomic(target_bundle_root / "review_history.json", history)
    write_model_json_atomic(target_bundle_root / "acceptance_record.json", acceptance)
    write_model_json_atomic(target_bundle_root / "accepted_scenario.json", migrated)
    return migrated


def migrate_option_schema_run_in_place(run_root: Path) -> int:
    """Atomically convert one schema-8 run and all candidate bindings to schema 9."""
    config_path = run_root / "run_config.json"
    if not config_path.is_file():
        raise FileNotFoundError(f"scenario run has no run config: {run_root}")
    raw_config = json.loads(config_path.read_text(encoding="utf-8"))
    raw_candidates = sorted(run_root.glob("*/scenarios/*/candidate.json"))
    if raw_config.get("generation_protocol_version") == ACTIVE_SCENARIO_GENERATION_VERSION:
        if raw_candidates and all(json.loads(path.read_text(encoding="utf-8")).get("schema_version") == "9.0.0" for path in raw_candidates):
            return 0
        raise ValueError("active-protocol run contains a non-current candidate schema")
    if raw_config.get("generation_protocol_version") != "v1.0.8":
        raise ValueError("in-place option-schema migration requires a V1.0.8 source run")

    staging_root = Path(tempfile.mkdtemp(prefix=f".{run_root.name}.schema9.", dir=run_root.parent))
    backup_root = run_root.parent / f".{run_root.name}.schema8-backup"
    if backup_root.exists():
        shutil.rmtree(staging_root)
        raise FileExistsError(f"scenario migration backup already exists: {backup_root}")
    try:
        shutil.copytree(run_root, staging_root, dirs_exist_ok=True)
        new_hash_by_old_hash: Dict[str, str] = {}
        new_hash_by_scenario_id: Dict[str, str] = {}
        for candidate_path in sorted(staging_root.glob("*/scenarios/*/candidate.json")):
            raw_candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
            old_hash = raw_candidate.get("candidate_sha256")
            if not isinstance(old_hash, str):
                raise ValueError(f"candidate has no digest: {candidate_path}")
            candidate = read_candidate_scenario(candidate_path)
            new_hash_by_old_hash[old_hash] = candidate.candidate_sha256
            new_hash_by_scenario_id[candidate.scenario_id] = candidate.candidate_sha256
            write_model_json_atomic(candidate_path, candidate)

            scenario_root = candidate_path.parent
            revisions = read_model_jsonl(scenario_root / "revision_cycles.jsonl", RevisionCycleRecord)
            if revisions:
                raise ValueError("in-place schema migration only supports runs whose migrated round has no revision cycles")
            automated_reviews = read_model_jsonl(scenario_root / "automated_reviews.jsonl", AutomatedScenarioReview)
            rebound_automated = []
            for review in automated_reviews:
                payload = review.model_dump(mode="json")
                if payload["reviewed_artifact_sha256"] == old_hash:
                    payload["reviewed_artifact_sha256"] = candidate.candidate_sha256
                rebound_automated.append(AutomatedScenarioReview.model_validate(payload))
            write_models_jsonl_atomic(scenario_root / "automated_reviews.jsonl", rebound_automated)

            disposition = read_model_json(scenario_root / "terminal_decision.json", ScenarioPipelineDisposition)
            disposition_payload = disposition.model_dump(mode="json")
            if disposition_payload["candidate_sha256"] != old_hash:
                raise ValueError(f"terminal disposition does not bind its schema-8 candidate: {candidate.scenario_id}")
            disposition_payload["candidate_sha256"] = candidate.candidate_sha256
            write_model_json_atomic(
                scenario_root / "terminal_decision.json",
                ScenarioPipelineDisposition.model_validate(disposition_payload),
            )

        researcher_path = staging_root / "researcher_review" / "scenario_reviews.jsonl"
        researcher_reviews = read_model_jsonl(researcher_path, ResearcherScenarioReview)
        rebound_researcher = []
        for review in researcher_reviews:
            payload = review.model_dump(mode="json")
            previous_hash = payload["reviewed_artifact_sha256"]
            if previous_hash not in new_hash_by_old_hash:
                raise ValueError(f"researcher review does not bind a migrated candidate: {review.scenario_id}")
            payload["reviewed_artifact_sha256"] = new_hash_by_old_hash[previous_hash]
            rebound_researcher.append(ResearcherScenarioReview.model_validate(payload))
        write_models_jsonl_atomic(researcher_path, rebound_researcher)

        manifest_path = staging_root / "migration_manifest.json"
        source_manifest = read_model_json(manifest_path, ScenarioMigrationManifest)
        manifest_payload = source_manifest.model_dump(mode="json", exclude={"manifest_sha256"})
        for entry in manifest_payload["entries"]:
            entry["migrated_candidate_sha256"] = new_hash_by_scenario_id[entry["scenario_id"]]
        write_model_json_atomic(
            manifest_path,
            ScenarioMigrationManifest.model_validate(
                {
                    **manifest_payload,
                    "manifest_sha256": artifact_sha256(manifest_payload),
                }
            ),
        )

        raw_config["generation_protocol_version"] = ACTIVE_SCENARIO_GENERATION_VERSION
        write_model_json_atomic(staging_root / "run_config.json", ScenarioGenerationRunConfig.model_validate(raw_config))
        current = current_scenario_artifacts(staging_root)
        if set(current) != set(new_hash_by_scenario_id):
            raise ValueError("migrated run does not resolve every converted scenario")
        run_researcher_reviews(staging_root)

        promoted = False
        try:
            os.replace(run_root, backup_root)
            os.replace(staging_root, run_root)
            promoted = True
        except Exception:
            if run_root.exists():
                shutil.rmtree(run_root)
            if backup_root.exists():
                os.replace(backup_root, run_root)
            raise
        finally:
            if promoted and backup_root.exists():
                shutil.rmtree(backup_root)
        return len(new_hash_by_scenario_id)
    finally:
        if staging_root.exists():
            shutil.rmtree(staging_root)
