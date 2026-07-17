"""Tests for the mandatory V6 human scenario-acceptance gate."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.generate_v6_scenario_drafts import load_v6_scenario_seeds
from src.data_models.scenario_review import (
    HumanReviewStatus,
    ReviewSubjectScope,
    ScenarioHumanReview,
    SemanticRequirementId,
    build_pending_human_review,
)
from src.data_models.scenarios_v6 import ScenarioFamilyV6
from src.experiments.io import load_scenario_families
from tests.v6_scenario_fixtures import (
    make_accepted_human_review,
    make_generation_manifest,
    make_semantic_review,
    make_v6_family,
)


def write_family_review_artifacts(
    root: Path,
    family: ScenarioFamilyV6,
    human_status: HumanReviewStatus | None,
) -> None:
    """Write one V6 family and its automated and optional human manifests."""
    semantic_review = make_semantic_review(family)
    generation_manifest = make_generation_manifest(family, semantic_review)
    root.mkdir(parents=True, exist_ok=True)
    (root / "semantic_reviews").mkdir(exist_ok=True)
    (root / "human_reviews").mkdir(exist_ok=True)
    (root / "manifests").mkdir(exist_ok=True)
    family_id = family.scenario_family_id
    (root / f"{family_id}.json").write_text(family.model_dump_json(indent=2), encoding="utf-8")
    (root / "semantic_reviews" / f"{family_id}.json").write_text(
        semantic_review.model_dump_json(indent=2),
        encoding="utf-8",
    )
    (root / "manifests" / f"{family_id}.json").write_text(
        generation_manifest.model_dump_json(indent=2),
        encoding="utf-8",
    )
    if human_status is not None:
        human_review = (
            make_accepted_human_review(family, semantic_review, generation_manifest)
            if human_status == HumanReviewStatus.ACCEPTED
            else build_pending_human_review(
                review=semantic_review,
                family=family,
                manifest=generation_manifest,
            )
        )
        (root / "human_reviews" / f"{family_id}.json").write_text(
            human_review.model_dump_json(indent=2),
            encoding="utf-8",
        )


def write_v6_review_run(root: Path, human_status: HumanReviewStatus | None) -> Path:
    """Write the default PFM001 V6 family review fixture."""
    write_family_review_artifacts(root, make_v6_family(), human_status)
    return root


def test_v6_loader_rejects_missing_and_pending_human_manifests(tmp_path: Path) -> None:
    """Verify a generated or pending V6 family cannot enter the experiment runner."""
    missing_dir = write_v6_review_run(tmp_path / "missing", None)
    pending_dir = write_v6_review_run(tmp_path / "pending", HumanReviewStatus.PENDING)

    with pytest.raises(ValueError, match="lacks required review manifests"):
        load_scenario_families(missing_dir)
    with pytest.raises(ValueError, match="not human-accepted: pending"):
        load_scenario_families(pending_dir)


def test_v6_loader_accepts_completed_human_review(tmp_path: Path) -> None:
    """Verify a human-accepted no-finding family can enter the experiment runner."""
    run_dir = write_v6_review_run(tmp_path / "accepted", HumanReviewStatus.ACCEPTED)

    families = load_scenario_families(run_dir)

    assert [family.scenario_family_id for family in families] == ["PFM001"]


def test_v6_loader_validates_only_selected_families(tmp_path: Path) -> None:
    """Verify an unrelated pending family cannot block an accepted pilot selection."""
    seeds = load_v6_scenario_seeds(
        Path("data/inputs/scenarios/v0.3.1/scenario_generation_seeds.json")
    )
    run_dir = tmp_path / "mixed-review-status"
    write_family_review_artifacts(
        run_dir,
        make_v6_family(seeds[0]),
        HumanReviewStatus.ACCEPTED,
    )
    write_family_review_artifacts(
        run_dir,
        make_v6_family(seeds[1]),
        HumanReviewStatus.PENDING,
    )

    families = load_scenario_families(run_dir, scenario_family_ids=["PFM001"])

    assert [family.scenario_family_id for family in families] == ["PFM001"]
    with pytest.raises(ValueError, match="RW001 is not human-accepted: pending"):
        load_scenario_families(run_dir)


def test_v6_loader_rejects_accepted_manifest_missing_a_finding(tmp_path: Path) -> None:
    """Verify acceptance cannot omit an automated finding disposition."""
    family = make_v6_family()
    scenario_id = family.scenario_instances[0].scenario_id
    review = make_semantic_review(
        family,
        {
            (
                SemanticRequirementId.DECISION_MATERIALITY,
                ReviewSubjectScope.SCENARIO,
                scenario_id,
            )
        },
    )
    generation_manifest = make_generation_manifest(family, review)
    run_dir = tmp_path / "missing-finding"
    run_dir.mkdir(parents=True)
    (run_dir / "semantic_reviews").mkdir()
    (run_dir / "human_reviews").mkdir()
    (run_dir / "manifests").mkdir()
    (run_dir / "PFM001.json").write_text(family.model_dump_json(indent=2), encoding="utf-8")
    (run_dir / "semantic_reviews" / "PFM001.json").write_text(
        review.model_dump_json(indent=2),
        encoding="utf-8",
    )
    (run_dir / "manifests" / "PFM001.json").write_text(
        generation_manifest.model_dump_json(indent=2),
        encoding="utf-8",
    )
    pending = build_pending_human_review(
        review=review,
        family=family,
        manifest=generation_manifest,
    )
    accepted_payload = pending.model_dump()
    accepted_payload.update(
        {
            "status": HumanReviewStatus.ACCEPTED,
            "reviewer": "Reviewer One",
            "reviewed_at": "2026-07-15T12:00:00+01:00",
            "finding_resolutions": [],
            "notes": "Incomplete review fixture.",
        }
    )
    accepted_without_resolution = ScenarioHumanReview.model_validate(accepted_payload)
    (run_dir / "human_reviews" / "PFM001.json").write_text(
        accepted_without_resolution.model_dump_json(indent=2),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="cover exactly every automated"):
        load_scenario_families(run_dir)


def test_v6_loader_rejects_family_edited_after_human_acceptance(tmp_path: Path) -> None:
    """Verify human acceptance remains bound to the exact final family content."""
    run_dir = write_v6_review_run(tmp_path / "tampered", HumanReviewStatus.ACCEPTED)
    family = make_v6_family()
    family.scenario_instances[0].title = "Edited after acceptance"
    (run_dir / "PFM001.json").write_text(
        family.model_dump_json(indent=2),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="hash does not match final_family_sha256"):
        load_scenario_families(run_dir)
