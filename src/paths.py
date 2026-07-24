"""Define stable filesystem paths shared across the project package."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

ACTIVE_SCENARIO_SEED_VERSION = "v0.10.0"
ACTIVE_SCENARIO_SET_ID = "customer_finance_task_family_facts_v0.10.0"
ACTIVE_SCENARIO_SEED_SHA256 = "cf912e7f4d8ae6c2e8dd4d0b02f753a68b017444880e4ac4f297423984baee5f"
ACTIVE_SCENARIO_SEED_SCHEMA_SHA256 = "b37ebe9bc1fdb017259aa043cf07ebf0af3b167beb84adc36a822593594c7c1d"
ACTIVE_SCENARIO_INPUT_ROOT = REPO_ROOT / "data" / "inputs" / "scenarios" / ACTIVE_SCENARIO_SEED_VERSION
ACTIVE_SCENARIO_ACCEPTED_ROOT = ACTIVE_SCENARIO_INPUT_ROOT / "accepted"
ACTIVE_SCENARIO_GENERATION_ROOT = REPO_ROOT / "data" / "outputs" / "scenario_generation" / ACTIVE_SCENARIO_SEED_VERSION
ACTIVE_SCENARIO_CHECKPOINT_ROOT = ACTIVE_SCENARIO_GENERATION_ROOT / "checkpoints"
ACTIVE_SCENARIO_REVIEW_ROOT = REPO_ROOT / "data" / "outputs" / "review" / "records"
AMPLE_PILOT_COST_REPORT_PATH = ACTIVE_SCENARIO_CHECKPOINT_ROOT / "ample_pilot_cost_report.json"
AMPLE_PILOT_APPROVAL_PATH = ACTIVE_SCENARIO_CHECKPOINT_ROOT / "ample_pilot_approval.json"
AMPLE_PILOT_RECORDS_PATH = ACTIVE_SCENARIO_CHECKPOINT_ROOT / "ample_pilot_records.jsonl"
AMPLE_PILOT_ATTEMPTS_PATH = ACTIVE_SCENARIO_CHECKPOINT_ROOT / "ample_pilot_attempts.jsonl"
RISK_COMM_V1_MANIFEST_ROOT = REPO_ROOT / "data" / "outputs" / "experiments" / "risk_comm_v1" / "manifests"
EVALUATED_MODEL_MANIFEST_PATH = RISK_COMM_V1_MANIFEST_ROOT / "evaluated_models.json"
WORD_BUDGET_MANIFEST_PATH = RISK_COMM_V1_MANIFEST_ROOT / "word_budgets.json"
