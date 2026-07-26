"""Define stable filesystem paths shared across the project package."""

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[1]

ACTIVE_SCENARIO_SEED_VERSION = "v0.11.0"
ACTIVE_SCENARIO_GENERATION_VERSION = "v0.10.1"
ACTIVE_SCENARIO_SET_ID = "customer_facing_risk_communication_v0.11.0"
ACTIVE_SCENARIO_SEED_SHA256 = "20731f76e69af4a810e8240ce7ec6042a9493b715d29ac6f0027e7760e96b709"
ACTIVE_SCENARIO_SEED_SCHEMA_SHA256 = "f314f04bbf9351446ffab9ebf82697955fc555e501e4c495a51c922be6498c57"
ACTIVE_SCENARIO_INPUT_ROOT = REPO_ROOT / "data" / "inputs" / "scenarios" / ACTIVE_SCENARIO_SEED_VERSION
ACTIVE_SCENARIO_ACCEPTED_ROOT = ACTIVE_SCENARIO_INPUT_ROOT / "accepted"
ACTIVE_SCENARIO_GENERATION_ROOT = REPO_ROOT / "data" / "outputs" / "scenario_generation" / ACTIVE_SCENARIO_SEED_VERSION
ACTIVE_SCENARIO_RUNS_ROOT = ACTIVE_SCENARIO_GENERATION_ROOT / "runs"
ACTIVE_SCENARIO_CHECKPOINT_ROOT = ACTIVE_SCENARIO_GENERATION_ROOT / "checkpoints"
AMPLE_PILOT_COST_REPORT_PATH = ACTIVE_SCENARIO_CHECKPOINT_ROOT / "ample_pilot_cost_report.json"
AMPLE_PILOT_APPROVAL_PATH = ACTIVE_SCENARIO_CHECKPOINT_ROOT / "ample_pilot_approval.json"
AMPLE_PILOT_RECORDS_PATH = ACTIVE_SCENARIO_CHECKPOINT_ROOT / "ample_pilot_records.jsonl"
AMPLE_PILOT_ATTEMPTS_PATH = ACTIVE_SCENARIO_CHECKPOINT_ROOT / "ample_pilot_attempts.jsonl"
RISK_COMM_V1_MANIFEST_ROOT = REPO_ROOT / "data" / "outputs" / "experiments" / "risk_comm_v1" / "manifests"
EVALUATED_MODEL_MANIFEST_PATH = RISK_COMM_V1_MANIFEST_ROOT / "evaluated_models.json"
WORD_BUDGET_MANIFEST_PATH = RISK_COMM_V1_MANIFEST_ROOT / "word_budgets.json"

SCENARIO_RUN_ID_FORMAT = "%Y%m%dT%H%M%S%fZ"
SCENARIO_RUN_ID_PATTERN = re.compile(r"^\d{8}T\d{12}Z$")


def scenario_generation_run_id(created_at: Optional[datetime] = None) -> str:
    """Build a sortable, collision-resistant UTC identifier for one generation run."""
    timestamp = created_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        raise ValueError("scenario generation run timestamps must be timezone-aware")
    return timestamp.astimezone(timezone.utc).strftime(SCENARIO_RUN_ID_FORMAT)


def scenario_generation_run_root(run_id: str) -> Path:
    """Resolve a validated run identifier beneath the active seed-version output root."""
    if SCENARIO_RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise ValueError("scenario generation run id must use YYYYMMDDTHHMMSSffffffZ")
    return ACTIVE_SCENARIO_RUNS_ROOT / run_id


def latest_scenario_generation_run_root() -> Path:
    """Return the newest configured run beneath the active seed-version output root."""
    candidates = (
        [
            path
            for path in ACTIVE_SCENARIO_RUNS_ROOT.iterdir()
            if path.is_dir() and SCENARIO_RUN_ID_PATTERN.fullmatch(path.name) is not None and (path / "run_config.json").is_file()
        ]
        if ACTIVE_SCENARIO_RUNS_ROOT.exists()
        else []
    )
    if not candidates:
        raise FileNotFoundError(f"no scenario generation runs found under {ACTIVE_SCENARIO_RUNS_ROOT}")
    return max(candidates, key=lambda path: path.name)
