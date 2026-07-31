"""Migrate one schema-8 generation run to canonical option records in place."""

from __future__ import annotations

import argparse

from src.paths import scenario_generation_run_root
from src.scenarios.schema_migration import migrate_option_schema_run_in_place


def main() -> None:
    """Convert candidates and rebind every run-level review and manifest digest."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    migrated_count = migrate_option_schema_run_in_place(scenario_generation_run_root(args.run_id))
    print(f"Migrated {migrated_count} candidates to schema 9.0.0 in {args.run_id}")


if __name__ == "__main__":
    main()
