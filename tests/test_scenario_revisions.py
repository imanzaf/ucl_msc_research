"""Test free-form, parent-linked scenario candidate versioning."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.cli.commands.scenarios.generate import _run_config
from src.data_models.scenario_review import ScenarioRevisionRecord
from src.data_models.scenarios import CandidateScenario
from src.scenarios.revisions import build_revised_candidate, editable_candidate_content, save_candidate_revision, save_in_place_candidate_revision
from src.scenarios.run_resolution import current_scenario_artifacts
from src.storage import read_model_json, read_model_jsonl, write_model_json_atomic
from tests.factories import make_candidate_scenario

SAVED_AT = datetime(2026, 8, 1, 15, 30, 0, 123456, tzinfo=timezone.utc)


def _run_root(tmp_path: Path) -> Path:
    """Create one valid named run for revision tests."""
    run_root = tmp_path / "scenario_set_v1"
    write_model_json_atomic(run_root / "run_config.json", _run_config(run_root.name, SAVED_AT))
    return run_root


def test_build_revised_candidate_accepts_query_description_and_fact_edits() -> None:
    """Allow all researcher-edited candidate sections in one version transition."""
    parent = make_candidate_scenario("CF001_R1")
    edited = editable_candidate_content(parent)
    edited["customer_messages"]["neutral_user_query"] = "I need help with my current account. What should I consider?"
    edited["options"][0]["description"] = "A revised neutral option description."
    edited["options"][0]["favourable_fact"]["fact_text"] = "The revised benefit is worth £150 each year."
    edited["options"][0]["favourable_fact"]["specificity_markers"] = ["£150"]

    candidate, changed_fields = build_revised_candidate(parent, edited, "researcher", SAVED_AT)

    assert candidate.provenance.parent_sha256 == parent.candidate_sha256
    assert candidate.customer_messages.neutral_user_query == "I need help with my current account. What should I consider?"
    assert any(path.endswith("neutral_user_query") for path in changed_fields)
    assert any(path.endswith("description") for path in changed_fields)
    assert any(path.endswith("fact_text") for path in changed_fields)


def test_save_candidate_revision_creates_a_new_current_version_and_history(tmp_path: Path) -> None:
    """Save a new round plus one simple append-only revision record."""
    run_root = _run_root(tmp_path)
    parent = make_candidate_scenario("CF001_R1")
    initial_round = run_root / "20260801T140000000000Z"
    write_model_json_atomic(initial_round / "scenarios" / parent.scenario_id / "candidate.json", parent)
    edited = editable_candidate_content(parent)
    edited["customer_messages"]["neutral_user_query"] = "I need help with my current account. What should I consider?"

    candidate, record, round_root = save_candidate_revision(
        run_root,
        parent,
        edited,
        edited_by="researcher",
        notes="Made the query non-leading.",
        saved_at=SAVED_AT,
    )

    assert round_root.name == "20260801T153000123456Z"
    assert current_scenario_artifacts(run_root)[candidate.scenario_id].candidate == candidate
    history = read_model_jsonl(run_root / "revision_history" / f"{candidate.scenario_id}.jsonl", ScenarioRevisionRecord)
    assert history == [record]
    assert record.parent_candidate_sha256 == parent.candidate_sha256
    assert record.notes == "Made the query non-leading."


def test_directly_edited_candidate_json_can_be_normalised_in_place(tmp_path: Path) -> None:
    """Support editing candidate.json directly before saving it as a revision."""
    run_root = _run_root(tmp_path)
    parent = make_candidate_scenario("CF001_R1")
    candidate_path = run_root / "20260801T140000000000Z" / "scenarios" / parent.scenario_id / "candidate.json"
    write_model_json_atomic(candidate_path, parent)
    payload = json.loads(candidate_path.read_text(encoding="utf-8"))
    payload["customer_messages"]["neutral_user_query"] = "I edited this file directly. What should I consider?"
    candidate_path.write_text(json.dumps(payload), encoding="utf-8")

    candidate, record, _ = save_in_place_candidate_revision(
        run_root,
        candidate_path,
        edited_by="researcher",
        saved_at=SAVED_AT,
    )

    assert read_model_json(candidate_path, CandidateScenario) == candidate
    assert candidate.provenance.parent_sha256 == parent.candidate_sha256
    assert record.changed_fields == ["manual_json_edit"]
