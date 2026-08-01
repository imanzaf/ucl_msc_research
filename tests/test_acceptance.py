"""Test direct selection-based scenario publication and bundle integrity."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.cli.commands.scenarios import publish as publish_command
from src.cli.commands.scenarios.generate import _run_config
from src.data_models.scenario_review import ScenarioAcceptanceRecord, ScenarioReviewHistory
from src.data_models.scenarios import AcceptedScenario, CandidateScenario, ScenarioGenerationRunConfig
from src.scenarios.acceptance import build_accepted_scenario, publish_accepted_scenario, validate_accepted_bundle
from src.scenarios.revisions import build_revised_candidate, editable_candidate_content
from src.storage import read_model_json, write_model_json_atomic
from tests.factories import make_candidate_scenario

PUBLISHED_AT = datetime(2026, 8, 1, 16, 0, tzinfo=timezone.utc)


def _bundle(candidate: CandidateScenario, version: str = "v1") -> tuple[AcceptedScenario, ScenarioReviewHistory, ScenarioAcceptanceRecord]:
    """Build a direct publication bundle with no review records."""
    history = ScenarioReviewHistory(schema_version="3.4.0", scenario_id=candidate.scenario_id)
    acceptance, accepted = build_accepted_scenario(
        candidate,
        history,
        accepted_at=PUBLISHED_AT,
        accepted_by="researcher",
        artifact_version=version,
    )
    return accepted, history, acceptance


def test_selected_candidate_publishes_without_automated_or_researcher_reviews(tmp_path: Path) -> None:
    """Treat publication itself as the only required researcher action."""
    candidate = make_candidate_scenario("CF001_R1")
    accepted, history, acceptance = _bundle(candidate)

    assert history.automated_reviews == []
    assert history.researcher_reviews == []
    assert accepted.options == candidate.options
    publish_accepted_scenario(accepted, history, acceptance, tmp_path)
    validate_accepted_bundle(
        read_model_json(tmp_path / candidate.scenario_id / "accepted_scenario.json", AcceptedScenario),
        read_model_json(tmp_path / candidate.scenario_id / "review_history.json", ScenarioReviewHistory),
        read_model_json(tmp_path / candidate.scenario_id / "acceptance_record.json", ScenarioAcceptanceRecord),
    )


def test_republishing_archives_the_previous_bundle(tmp_path: Path) -> None:
    """Replace the current publication while preserving the prior published bundle."""
    parent = make_candidate_scenario("CF001_R1")
    first_bundle = _bundle(parent)
    publish_accepted_scenario(*first_bundle, accepted_root=tmp_path)
    edited = editable_candidate_content(parent)
    edited["options"][0]["favourable_fact"] = {
        "fact_text": "The revised benefit is worth £150.",
        "specificity_markers": ["£150"],
    }
    revised, _ = build_revised_candidate(parent, edited, "researcher", PUBLISHED_AT)
    second_bundle = _bundle(revised, "v2")

    publish_accepted_scenario(*second_bundle, accepted_root=tmp_path, replace_existing=True)

    current = read_model_json(tmp_path / parent.scenario_id / "accepted_scenario.json", AcceptedScenario)
    assert current.artifact_version == "v2"
    assert (tmp_path / "_history" / parent.scenario_id / first_bundle[0].artifact_sha256 / "accepted_scenario.json").is_file()


def test_publish_selected_candidates_uses_only_named_current_versions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Publish a subset without requiring seed ownership, reviews, or a complete set."""
    run_root = tmp_path / "scenario_set_v1"
    config = _run_config(run_root.name, PUBLISHED_AT).model_dump(mode="json")
    config["query_sha256"] = "1" * 64
    write_model_json_atomic(run_root / "run_config.json", ScenarioGenerationRunConfig.model_validate(config))
    candidates = [make_candidate_scenario("CF001_R1"), make_candidate_scenario("CF001_R2")]
    for index, candidate in enumerate(candidates, start=1):
        round_id = f"20260801T16000{index}000000Z"
        write_model_json_atomic(run_root / round_id / "scenarios" / candidate.scenario_id / "candidate.json", candidate)
    accepted_root = tmp_path / "accepted"
    monkeypatch.setattr(publish_command, "ACTIVE_SCENARIO_ACCEPTED_ROOT", accepted_root)

    published, manifests = publish_command.publish_selected_candidates(
        run_root,
        ["CF001_R2"],
        "researcher",
        PUBLISHED_AT,
    )

    assert [item.scenario_id for item in published] == ["CF001_R2"]
    assert manifests == []
    assert (accepted_root / "CF001_R2" / "accepted_scenario.json").is_file()
    assert not (accepted_root / "CF001_R1").exists()
