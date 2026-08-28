"""Import and minimally correct the supplied scenario seed archive."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import zipfile
from pathlib import Path
from typing import Any, Dict

from src.models.seeds import ScenarioSeedSet
from src.storage import write_json

EXPECTED_SOURCE_SHA256 = "b9fb39abb4be8cdda91de2f3d9817cb2febda0437fc2cb47abbf75b6e8add790"
ATOMIC_ANCHOR_CORRECTIONS = {
    ("CF101_R5", "P3", "countervailing_fact"): "earlier payoff date",
    ("CF102_R1", "P2", "countervailing_fact"): "minimum-only payoff period",
    ("CF102_R3", "P2", "countervailing_fact"): "7.9% instalment APR",
    ("CF102_R5", "P1", "owner_supporting_fact"): "£495 origination fee",
    ("CF102_R5", "P2", "countervailing_fact"): "7.4% APR",
    ("CF104_R4", "P2", "owner_supporting_fact"): "0.35% annual platform charge",
    ("CF104_R5", "P1", "countervailing_fact"): "£6 per trade",
    ("CF106_R1", "P2", "countervailing_fact"): "1.20% FX markup",
    ("CF106_R4", "P1", "countervailing_fact"): "2.75% foreign-transaction charge",
    ("CF106_R5", "P1", "owner_supporting_fact"): "conversion rate is not fixed",
    ("CF106_R5", "P2", "countervailing_fact"): "£10 transfer fee",
}


def file_sha256(path: Path) -> str:
    """Calculate a source archive digest without loading it all into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _find_member(archive: zipfile.ZipFile, basename: str) -> str:
    """Resolve one expected basename regardless of the archive's top-level directory."""
    matches = [name for name in archive.namelist() if Path(name).name == basename]
    if len(matches) != 1:
        raise ValueError(f"archive must contain exactly one {basename}")
    return matches[0]


def _correct_seed_payload(source: Dict[str, Any]) -> Dict[str, Any]:
    """Apply the audited identifier, order, and atomic-anchor corrections."""
    corrected = copy.deepcopy(source)
    corrected["schema_version"] = "4.0.1"
    corrected["scenario_set_id"] = "financial_risk_communication_scenarios_v4.0.1"
    corrected["notice"] = (
        "All companies, products and figures in this benchmark are fictional. The corpus is for controlled research and is not financial advice."
    )
    scenarios = [scenario for use_case in corrected["use_cases"] for scenario in use_case["replications"]]
    for index, scenario in enumerate(scenarios):
        scenario["presentation_order"] = ["OPTION_A", "OPTION_B"] if index % 2 == 0 else ["OPTION_B", "OPTION_A"]
        for pair in scenario["fact_pair_briefs"]:
            for direction_key in ("owner_supporting_fact", "countervailing_fact"):
                correction_key = (scenario["scenario_id"], pair["pair_id"], direction_key)
                if correction_key in ATOMIC_ANCHOR_CORRECTIONS:
                    pair[direction_key]["required_specificity"] = ATOMIC_ANCHOR_CORRECTIONS[correction_key]
    return corrected


def import_package(source_archive: Path, target_root: Path, preserve_archive_path: Path | None = None) -> ScenarioSeedSet:
    """Verify, preserve, correct, validate, and audit the supplied source package."""
    digest = file_sha256(source_archive)
    if digest != EXPECTED_SOURCE_SHA256:
        raise ValueError(f"source archive SHA-256 mismatch: {digest}")
    if preserve_archive_path is not None:
        preserve_archive_path.parent.mkdir(parents=True, exist_ok=True)
        if not preserve_archive_path.exists():
            shutil.copyfile(source_archive, preserve_archive_path)
        elif file_sha256(preserve_archive_path) != digest:
            raise FileExistsError("preserved source archive exists with a different checksum")
    with zipfile.ZipFile(source_archive) as archive:
        seed_member = _find_member(archive, "scenario_generation_seeds_v4.0.0.json")
        source_payload = json.loads(archive.read(seed_member).decode("utf-8"))
    seed_set = ScenarioSeedSet.model_validate(_correct_seed_payload(source_payload))
    target_root.mkdir(parents=True, exist_ok=True)
    write_json(target_root / "scenario_generation_seeds.json", seed_set)
    write_json(
        target_root / "source_package.json",
        {
            "schema_version": "4.0.0",
            "source_filename": source_archive.name,
            "source_sha256": digest,
            "preserved_archive": str(preserve_archive_path) if preserve_archive_path is not None else None,
            "corrections": [
                "balanced option presentation order across the thirty scenarios",
                "declared one atomic specificity anchor for each bundled source declaration",
                "reserved affect and query wording for controlled query generation",
            ],
        },
    )
    return seed_set
