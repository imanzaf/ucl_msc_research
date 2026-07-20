"""Filesystem layout and accepted-only loaders for risk_comm_v1."""

from __future__ import annotations

import re
from pathlib import Path
from typing import List

from src.data_models.common import artifact_sha256, validate_model_self_hash
from src.data_models.experiments import ConversationTranscript
from src.data_models.manifests import AcceptedScenarioManifest, ScenarioManifestScope
from src.data_models.scenario_review import ScenarioAcceptanceRecord, ScenarioReviewHistory
from src.data_models.scenarios import AcceptedScenario, ScenarioStage
from src.scenarios.acceptance import validate_accepted_bundle
from src.storage import read_model_json, read_model_jsonl

EXPERIMENT_NAME_PATTERN = re.compile(r"^[a-z0-9_]+_v[0-9]+$")


def prepare_experiment_dir(experiment_root: Path, experiment_name: str) -> Path:
    """Create config, results, cache, logs, assets, and checkpoints layout."""
    if EXPERIMENT_NAME_PATTERN.fullmatch(experiment_name) is None:
        raise ValueError("experiment name must follow lowercase_snake_case_v<N>")
    experiment_dir = experiment_root / experiment_name
    for relative_path in ["results", "cache", "logs", "assets", "checkpoints"]:
        (experiment_dir / relative_path).mkdir(parents=True, exist_ok=True)
    return experiment_dir


def load_all_accepted_scenarios(
    accepted_root: Path,
    manifest: AcceptedScenarioManifest,
) -> List[AcceptedScenario]:
    """Authenticate the frozen accepted manifest and return all 50 published bundles."""
    if manifest.manifest_scope != ScenarioManifestScope.COMPLETE:
        raise ValueError("this loader requires the complete 50-scenario accepted manifest")
    scenarios = _load_accepted_scenarios(accepted_root, manifest)
    if len(scenarios) != 50:
        raise ValueError("accepted scenario set must contain exactly 50 unique C1/R1-R4 scenarios")
    return scenarios


def load_accepted_calibration_scenarios(
    accepted_root: Path,
    manifest: AcceptedScenarioManifest,
) -> List[AcceptedScenario]:
    """Authenticate and return exactly the ten C1 bundles from a calibration checkpoint."""
    if manifest.manifest_scope != ScenarioManifestScope.CALIBRATION:
        raise ValueError("calibration loader requires a calibration-scope accepted manifest")
    scenarios = _load_accepted_scenarios(accepted_root, manifest)
    if len(scenarios) != 10 or any(scenario.study_stage != ScenarioStage.CALIBRATION for scenario in scenarios):
        raise ValueError("accepted calibration set must contain exactly ten C1 scenarios")
    return scenarios


def _load_accepted_scenarios(
    accepted_root: Path,
    manifest: AcceptedScenarioManifest,
) -> List[AcceptedScenario]:
    """Authenticate every bundle referenced by one scope-valid accepted manifest."""
    validate_model_self_hash(manifest, "manifest_sha256")
    resolved_root = accepted_root.resolve()
    scenarios: List[AcceptedScenario] = []
    for entry in manifest.entries:
        relative_path = Path(entry.artifact_path)
        if relative_path.is_absolute():
            raise ValueError("accepted manifest artifact paths must be relative")
        artifact_path = (accepted_root / relative_path).resolve()
        if not artifact_path.is_relative_to(resolved_root):
            raise ValueError("accepted manifest artifact path escapes accepted root")
        review_path = artifact_path.parent / "review_history.json"
        acceptance_path = artifact_path.parent / "acceptance_record.json"
        accepted = read_model_json(artifact_path, AcceptedScenario)
        history = read_model_json(review_path, ScenarioReviewHistory)
        acceptance = read_model_json(acceptance_path, ScenarioAcceptanceRecord)
        validate_accepted_bundle(accepted, history, acceptance)
        if accepted.scenario_id != entry.scenario_id or accepted.study_stage != entry.study_stage:
            raise ValueError("accepted manifest entry identity differs from its artifact")
        if accepted.artifact_sha256 != entry.artifact_sha256:
            raise ValueError("accepted manifest entry artifact hash mismatch")
        if artifact_sha256(history) != entry.review_history_sha256:
            raise ValueError("accepted manifest entry review-history hash mismatch")
        if acceptance.record_sha256 != entry.acceptance_record_sha256:
            raise ValueError("accepted manifest entry acceptance-record hash mismatch")
        scenarios.append(accepted)
    if len({scenario.scenario_id for scenario in scenarios}) != len(scenarios):
        raise ValueError("accepted scenario manifest contains duplicate scenario ids")
    return sorted(scenarios, key=lambda scenario: scenario.scenario_id)


def load_accepted_evaluation_scenarios(
    accepted_root: Path,
    manifest: AcceptedScenarioManifest,
) -> List[AcceptedScenario]:
    """Return exactly the 40 authenticated evaluation bundles from the frozen accepted set."""
    scenarios = [scenario for scenario in load_all_accepted_scenarios(accepted_root, manifest) if scenario.study_stage == ScenarioStage.EVALUATION]
    if len(scenarios) != 40:
        raise ValueError("accepted evaluation set must contain exactly 40 R1-R4 scenarios")
    return scenarios


def read_transcript_results(path: Path) -> List[ConversationTranscript]:
    """Read and validate completed or terminal transcript records for resume."""
    return read_model_jsonl(path, ConversationTranscript)
