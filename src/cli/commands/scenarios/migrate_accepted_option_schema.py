"""Migrate tracked accepted calibration bundles to canonical option records."""

from __future__ import annotations

import argparse
import os
import shutil
import tempfile
from pathlib import Path

from src.cli.commands.scenarios.build_manifest import build_accepted_scenario_manifest
from src.data_models.manifests import AcceptedScenarioManifest, ScenarioManifestScope
from src.paths import ACTIVE_SCENARIO_ACCEPTED_ROOT, ACTIVE_SCENARIO_INPUT_ROOT
from src.scenarios.schema_migration import migrate_accepted_bundle
from src.storage import atomic_write_bytes, read_model_json, write_model_json_atomic


def _staged_accepted_root() -> Path:
    """Build and validate a complete staged schema-9 accepted root."""
    staging_root = Path(tempfile.mkdtemp(prefix=".accepted-schema9.", dir=ACTIVE_SCENARIO_INPUT_ROOT))
    for source_bundle_root in sorted(ACTIVE_SCENARIO_ACCEPTED_ROOT.glob("CF???_*")):
        migrate_accepted_bundle(source_bundle_root, staging_root / source_bundle_root.name)
    return staging_root


def main() -> None:
    """Atomically replace accepted bundles and rebuild their calibration manifest."""
    argparse.ArgumentParser().parse_args()
    manifest_path = ACTIVE_SCENARIO_INPUT_ROOT / "calibration_accepted_scenario_manifest.json"
    source_manifest = read_model_json(manifest_path, AcceptedScenarioManifest)
    if source_manifest.manifest_scope != ScenarioManifestScope.CALIBRATION:
        raise ValueError("accepted option-schema migration requires the calibration manifest")
    staging_root = _staged_accepted_root()
    migrated_manifest = build_accepted_scenario_manifest(
        accepted_root=staging_root,
        scope=ScenarioManifestScope.CALIBRATION,
        published_by=source_manifest.published_by,
        published_at=source_manifest.published_at,
    )
    backup_root = ACTIVE_SCENARIO_INPUT_ROOT / ".accepted-schema8-backup"
    if backup_root.exists():
        shutil.rmtree(staging_root)
        raise FileExistsError(f"accepted migration backup already exists: {backup_root}")
    source_manifest_bytes = manifest_path.read_bytes()
    promoted = False
    try:
        os.replace(ACTIVE_SCENARIO_ACCEPTED_ROOT, backup_root)
        os.replace(staging_root, ACTIVE_SCENARIO_ACCEPTED_ROOT)
        write_model_json_atomic(manifest_path, migrated_manifest)
        promoted = True
    except Exception:
        if ACTIVE_SCENARIO_ACCEPTED_ROOT.exists():
            shutil.rmtree(ACTIVE_SCENARIO_ACCEPTED_ROOT)
        if backup_root.exists():
            os.replace(backup_root, ACTIVE_SCENARIO_ACCEPTED_ROOT)
        atomic_write_bytes(manifest_path, source_manifest_bytes)
        raise
    finally:
        if staging_root.exists():
            shutil.rmtree(staging_root)
        if promoted and backup_root.exists():
            shutil.rmtree(backup_root)
    print(f"Migrated {len(migrated_manifest.entries)} accepted calibration bundles to schema 9.0.0")


if __name__ == "__main__":
    main()
