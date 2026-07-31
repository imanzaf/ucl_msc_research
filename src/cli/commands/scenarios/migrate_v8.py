"""Migrate approved flattened calibration outputs into one current-schema run."""

from __future__ import annotations

import argparse
from datetime import datetime
from typing import List

from src.data_models.common import utc_now
from src.paths import scenario_generation_run_root
from src.scenarios.schema_migration import migrate_approved_calibration_runs


def _migration_timestamp(value: str | None) -> datetime:
    """Parse an optional ISO timestamp or return the current UTC time."""
    if value is None:
        return utc_now()
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("--migrated-at must include a timezone")
    return parsed


def main() -> None:
    """Create one complete migrated calibration run without provider calls."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-run-id", action="append", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--migrated-at")
    args = parser.parse_args()
    source_run_ids: List[str] = args.source_run_id
    manifest = migrate_approved_calibration_runs(
        source_run_roots=[scenario_generation_run_root(run_id) for run_id in source_run_ids],
        target_run_root=scenario_generation_run_root(args.run_id),
        migrated_at=_migration_timestamp(args.migrated_at),
    )
    print(f"Migrated {len(manifest.entries)} approved C1 candidates from " f"{', '.join(manifest.source_run_ids)} into {manifest.target_run_id}")


if __name__ == "__main__":
    main()
