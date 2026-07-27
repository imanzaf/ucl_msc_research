"""Define stable filesystem paths shared across the project package."""

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[1]

ACTIVE_SCENARIO_SEED_VERSION = "v1.0.0"
ACTIVE_SCENARIO_GENERATION_VERSION = "v1.0.0"
ACTIVE_SCENARIO_SET_ID = "customer_facing_risk_communication_v1.0.0"
ACTIVE_SCENARIO_SEED_SHA256 = "846c0ab8a89387d15d7ae53e171ecd6f43cdace4f554889a3f52d1b16ec9b5ff"
ACTIVE_SCENARIO_SEED_SCHEMA_SHA256 = "68eacf33bc69eb4c77f3bc8ce3c40ff2e17ab24dc9dcb2281895a2aaa9749503"
ACTIVE_SCENARIO_INPUT_ROOT = REPO_ROOT / "data" / "inputs" / "scenarios" / ACTIVE_SCENARIO_SEED_VERSION
ACTIVE_SCENARIO_ACCEPTED_ROOT = ACTIVE_SCENARIO_INPUT_ROOT / "accepted"
ACTIVE_SCENARIO_GENERATION_ROOT = REPO_ROOT / "data" / "outputs" / "scenario_generation" / ACTIVE_SCENARIO_SEED_VERSION
ACTIVE_SCENARIO_CHECKPOINT_ROOT = ACTIVE_SCENARIO_GENERATION_ROOT / "checkpoints"
AMPLE_PILOT_COST_REPORT_PATH = ACTIVE_SCENARIO_CHECKPOINT_ROOT / "ample_pilot_cost_report.json"
AMPLE_PILOT_APPROVAL_PATH = ACTIVE_SCENARIO_CHECKPOINT_ROOT / "ample_pilot_approval.json"
AMPLE_PILOT_RECORDS_PATH = ACTIVE_SCENARIO_CHECKPOINT_ROOT / "ample_pilot_records.jsonl"
AMPLE_PILOT_ATTEMPTS_PATH = ACTIVE_SCENARIO_CHECKPOINT_ROOT / "ample_pilot_attempts.jsonl"
RISK_COMM_V1_MANIFEST_ROOT = REPO_ROOT / "data" / "outputs" / "experiments" / "risk_comm_v1" / "manifests"
EVALUATED_MODEL_MANIFEST_PATH = RISK_COMM_V1_MANIFEST_ROOT / "evaluated_models.json"
WORD_BUDGET_MANIFEST_PATH = RISK_COMM_V1_MANIFEST_ROOT / "word_budgets.json"

SCENARIO_RUN_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*_v[1-9][0-9]*$")
SCENARIO_ROUND_ID_FORMAT = "%Y%m%dT%H%M%S%fZ"
SCENARIO_ROUND_ID_PATTERN = re.compile(r"^\d{8}T\d{12}Z$")


def scenario_generation_round_id(created_at: Optional[datetime] = None) -> str:
    """Build a sortable, collision-resistant UTC identifier for one run round."""
    timestamp = created_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        raise ValueError("scenario generation round timestamps must be timezone-aware")
    return timestamp.astimezone(timezone.utc).strftime(SCENARIO_ROUND_ID_FORMAT)


def scenario_generation_run_root(run_id: str) -> Path:
    """Resolve a named logical run directly beneath the active seed-version root."""
    if SCENARIO_RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise ValueError("scenario generation run id must use lowercase snake_case with an explicit _vN suffix")
    return ACTIVE_SCENARIO_GENERATION_ROOT / run_id


def latest_scenario_generation_run_root() -> Path:
    """Return the most recently created named run beneath the active seed root."""
    candidates = (
        [
            path
            for path in ACTIVE_SCENARIO_GENERATION_ROOT.iterdir()
            if path.is_dir() and SCENARIO_RUN_ID_PATTERN.fullmatch(path.name) is not None and (path / "run_config.json").is_file()
        ]
        if ACTIVE_SCENARIO_GENERATION_ROOT.exists()
        else []
    )
    if not candidates:
        raise FileNotFoundError(f"no scenario generation runs found under {ACTIVE_SCENARIO_GENERATION_ROOT}")
    return max(candidates, key=lambda path: (path / "run_config.json").stat().st_mtime_ns)
