"""Tests for V6 semantic review, selective revision, and persistence."""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List
from uuid import uuid4

import pytest

from scripts.generate_v6_scenario_drafts import (
    generate_review_and_revise_family,
    request_semantic_review,
)
from src.data_models.experiments import (
    ExperimentStage,
    GenerationConfig,
    LLMCallRecord,
    LLMCallUsage,
)
from src.data_models.scenario_review import (
    HumanReviewStatus,
    ReviewSubjectScope,
    ScenarioGenerationFailure,
    ScenarioGenerationManifest,
    ScenarioHumanReview,
    SemanticRequirementId,
    route_failed_assessments,
)
from src.data_models.scenarios_v6 import GeneratedScenarioInstanceV6
from src.llm.openrouter import LLMCallResult
from tests.v6_scenario_fixtures import (
    ReviewKey,
    load_test_v6_seed,
    make_generated_v6_instance,
    make_semantic_review,
    make_v6_family,
)


def make_call_result(parsed: Any, stage: ExperimentStage) -> LLMCallResult[Any]:
    """Create one deterministic fake call result for V6 orchestration tests."""
    record = LLMCallRecord(
        call_id=str(uuid4()),
        stage=stage,
        model_id="fake/model",
        resolved_model_id="fake/model",
        generation_id=str(uuid4()),
        cache_key=str(uuid4()),
        cache_hit=False,
        created_at="2026-07-15T00:00:00+00:00",
        prompt_version="fixture_v1",
        request_payload={},
        response_payload={},
        parsed_output=parsed.model_dump() if hasattr(parsed, "model_dump") else None,
        usage=LLMCallUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
    )
    return LLMCallResult(parsed=parsed, record=record)


class FakeV6GenerationClient:
    """Return stage-aware V6 generation, review, and revision outputs."""

    def __init__(self, review: Any, invalid_revision: bool = False) -> None:
        """Store the review and whether revision output should violate V6 validation."""
        self.review = review
        self.invalid_revision = invalid_revision
        self.calls: List[Dict[str, Any]] = []
        self.lock = Lock()

    def complete_structured(self, **kwargs: Any) -> LLMCallResult[Any]:
        """Return a valid result selected by the requested pipeline stage."""
        with self.lock:
            self.calls.append(kwargs)
        stage = kwargs["stage"]
        if stage == ExperimentStage.SCENARIO_GENERATION:
            scenario_id = kwargs["metadata"]["scenario_id"]
            parsed = make_generated_v6_instance(scenario_id)
        elif stage == ExperimentStage.SCENARIO_SEMANTIC_REVIEW:
            parsed = self.review.pop(0) if isinstance(self.review, list) else self.review
        elif stage == ExperimentStage.SCENARIO_REVISION:
            scenario_id = kwargs["metadata"]["scenario_id"]
            parsed = (
                GeneratedScenarioInstanceV6.model_construct(title="invalid")
                if self.invalid_revision
                else make_generated_v6_instance(f"Revised {scenario_id}")
            )
        else:
            raise AssertionError(f"unexpected stage: {stage}")
        return make_call_result(parsed=parsed, stage=stage)


def scenario_failure_key(scenario_id: str) -> ReviewKey:
    """Return a valid scenario-level semantic failure key."""
    return (
        SemanticRequirementId.DECISION_MATERIALITY,
        ReviewSubjectScope.SCENARIO,
        scenario_id,
    )


def test_no_findings_skips_all_revision_calls(tmp_path: Path) -> None:
    """Verify a fully passing family receives no automated revision."""
    seed = load_test_v6_seed()
    expected_family = make_v6_family(seed)
    client = FakeV6GenerationClient(make_semantic_review(expected_family))

    final_family = generate_review_and_revise_family(
        client=client,
        seed=seed,
        generator_model_id="openai/gpt-generator",
        reviewer_model_id="anthropic/claude-haiku-4.5",
        generation_config=GenerationConfig(temperature=0.4, seed=7),
        output_dir=tmp_path,
        concurrency=4,
    )

    stages = [call["stage"] for call in client.calls]
    assert stages.count(ExperimentStage.SCENARIO_GENERATION) == 4
    assert stages.count(ExperimentStage.SCENARIO_SEMANTIC_REVIEW) == 1
    assert ExperimentStage.SCENARIO_REVISION not in stages
    assert final_family.model_dump() == expected_family.model_dump()
    assert (tmp_path / "PFM001.json").exists()
    human_review = ScenarioHumanReview.model_validate_json(
        (tmp_path / "human_reviews" / "PFM001.json").read_text(encoding="utf-8")
    )
    assert human_review.status == HumanReviewStatus.PENDING
    markdown_paths = list(tmp_path.rglob("*.md"))
    assert markdown_paths == [tmp_path / "human_reviews" / "PFM001.md"]
    review_text = markdown_paths[0].read_text(encoding="utf-8")
    assert "Final Scenarios" in review_text
    assert "Expected disclosure:" in review_text
    assert "Specificity markers:" in review_text
    assert "User-Only Context" in review_text
    assert "Possible Actions" in review_text
    assert "Possible Beliefs" in review_text


def test_controlled_family_persists_prompt_profile_provenance(tmp_path: Path) -> None:
    """Verify V0.3.1 generation persists its code-owned prompt profile in all audit outputs."""
    seed = load_test_v6_seed()
    expected_family = make_v6_family(seed)
    client = FakeV6GenerationClient(make_semantic_review(expected_family))

    final_family = generate_review_and_revise_family(
        client=client,
        seed=seed,
        generator_model_id="openai/gpt-generator",
        reviewer_model_id="anthropic/claude-haiku-4.5",
        generation_config=GenerationConfig(temperature=0.4, seed=7),
        output_dir=tmp_path,
        concurrency=4,
    )

    manifest = ScenarioGenerationManifest.model_validate_json(
        (tmp_path / "manifests" / "PFM001.json").read_text(encoding="utf-8")
    )
    human_review_text = (tmp_path / "human_reviews" / "PFM001.md").read_text(encoding="utf-8")
    assert final_family.prompt_control_profile_id.value == "omission_integrity_v1"
    assert manifest.prompt_control_profile_id == final_family.prompt_control_profile_id
    assert "Prompt control profile: `omission_integrity_v1`" in human_review_text


def test_some_findings_revise_only_flagged_scenarios(tmp_path: Path) -> None:
    """Verify passing initial drafts remain identical and only one flagged draft changes."""
    seed = load_test_v6_seed()
    initial_family = make_v6_family(seed)
    flagged_id = initial_family.scenario_instances[0].scenario_id
    review = make_semantic_review(initial_family, {scenario_failure_key(flagged_id)})
    client = FakeV6GenerationClient(review)

    final_family = generate_review_and_revise_family(
        client=client,
        seed=seed,
        generator_model_id="openai/gpt-generator",
        reviewer_model_id="anthropic/claude-haiku-4.5",
        generation_config=GenerationConfig(temperature=0.4),
        output_dir=tmp_path,
        concurrency=4,
    )

    revision_calls = [
        call for call in client.calls if call["stage"] == ExperimentStage.SCENARIO_REVISION
    ]
    assert [call["metadata"]["scenario_id"] for call in revision_calls] == [flagged_id]
    initial_by_id = {item.scenario_id: item for item in initial_family.scenario_instances}
    final_by_id = {item.scenario_id: item for item in final_family.scenario_instances}
    for scenario_id in set(initial_by_id) - {flagged_id}:
        assert final_by_id[scenario_id].model_dump() == initial_by_id[scenario_id].model_dump()
    assert final_by_id[flagged_id].title == f"Revised {flagged_id} review"
    manifest = ScenarioGenerationManifest.model_validate_json(
        (tmp_path / "manifests" / "PFM001.json").read_text(encoding="utf-8")
    )
    assert manifest.semantic_resolution_verified is False
    human_review_text = (tmp_path / "human_reviews" / "PFM001.md").read_text(encoding="utf-8")
    failed_finding_id = next(
        assessment.finding_id for assessment in review.assessments if assessment.finding_id
    )
    assert failed_finding_id in human_review_text
    assert "Required correction:" in human_review_text


def test_family_level_finding_routes_revision_to_all_four_scenarios(tmp_path: Path) -> None:
    """Verify a family-level failure is routed to every affected scenario."""
    seed = load_test_v6_seed()
    initial_family = make_v6_family(seed)
    family_key = (
        SemanticRequirementId.TASK_TYPE_DISTINCTNESS,
        ReviewSubjectScope.FAMILY,
        initial_family.scenario_family_id,
    )
    review = make_semantic_review(initial_family, {family_key})
    assert set(route_failed_assessments(review)) == {
        instance.scenario_id for instance in initial_family.scenario_instances
    }
    client = FakeV6GenerationClient(review)

    generate_review_and_revise_family(
        client=client,
        seed=seed,
        generator_model_id="openai/gpt-generator",
        reviewer_model_id="anthropic/claude-haiku-4.5",
        generation_config=GenerationConfig(),
        output_dir=tmp_path,
        concurrency=4,
    )

    revision_ids = {
        call["metadata"]["scenario_id"]
        for call in client.calls
        if call["stage"] == ExperimentStage.SCENARIO_REVISION
    }
    assert revision_ids == {instance.scenario_id for instance in initial_family.scenario_instances}


def test_all_failed_assessments_still_make_one_revision_per_scenario(tmp_path: Path) -> None:
    """Verify many routed findings are batched into four full-correction calls."""
    seed = load_test_v6_seed()
    initial_family = make_v6_family(seed)
    complete_review = make_semantic_review(initial_family)
    every_key = {
        (assessment.requirement_id, assessment.subject_scope, assessment.subject_id)
        for assessment in complete_review.assessments
    }
    client = FakeV6GenerationClient(make_semantic_review(initial_family, every_key))

    generate_review_and_revise_family(
        client=client,
        seed=seed,
        generator_model_id="openai/gpt-generator",
        reviewer_model_id="anthropic/claude-haiku-4.5",
        generation_config=GenerationConfig(),
        output_dir=tmp_path,
        concurrency=4,
    )

    revision_calls = [
        call for call in client.calls if call["stage"] == ExperimentStage.SCENARIO_REVISION
    ]
    assert len(revision_calls) == 4
    assert {call["metadata"]["scenario_id"] for call in revision_calls} == {
        instance.scenario_id for instance in initial_family.scenario_instances
    }


def test_malformed_review_coverage_is_rejected() -> None:
    """Verify the reviewer cannot omit one required scenario-level assessment."""
    seed = load_test_v6_seed()
    family = make_v6_family(seed)
    complete_review = make_semantic_review(family)
    incomplete_review = complete_review.model_copy(
        update={"assessments": complete_review.assessments[:-1]}
    )
    client = FakeV6GenerationClient(incomplete_review)

    with pytest.raises(ValueError, match="coverage failed"):
        request_semantic_review(
            client=client,
            seed=seed,
            family=family,
            reviewer_model_id="anthropic/claude-haiku-4.5",
        )


def test_malformed_review_coverage_is_retried_and_audited(tmp_path: Path) -> None:
    """Verify an incomplete matrix is retained before a complete retry is accepted."""
    seed = load_test_v6_seed()
    family = make_v6_family(seed)
    complete_review = make_semantic_review(family)
    incomplete_review = complete_review.model_copy(
        update={"assessments": complete_review.assessments[:-1]}
    )
    client = FakeV6GenerationClient([incomplete_review, complete_review])
    client.max_retries = 1

    result = request_semantic_review(
        client=client,
        seed=seed,
        family=family,
        reviewer_model_id="anthropic/claude-haiku-4.5",
        output_dir=tmp_path,
    )

    assert len(result.attempts) == 2
    review_calls = [
        call for call in client.calls if call["stage"] == ExperimentStage.SCENARIO_SEMANTIC_REVIEW
    ]
    assert [call["prompt_version"] for call in review_calls] == [
        "scenario_semantic_review_v1",
        "scenario_semantic_review_v1_retry_2",
    ]
    attempt_dir = tmp_path / "semantic_reviews" / "attempts"
    assert (attempt_dir / "PFM001_attempt_1.json").exists()
    assert (attempt_dir / "PFM001_attempt_2.json").exists()


def test_invalid_revision_preserves_audit_artifacts_without_final_family(
    tmp_path: Path,
) -> None:
    """Verify invalid revision output cannot create a loader-visible final family."""
    seed = load_test_v6_seed()
    family = make_v6_family(seed)
    flagged_id = family.scenario_instances[0].scenario_id
    review = make_semantic_review(family, {scenario_failure_key(flagged_id)})
    client = FakeV6GenerationClient(review, invalid_revision=True)

    with pytest.raises(ValueError):
        generate_review_and_revise_family(
            client=client,
            seed=seed,
            generator_model_id="openai/gpt-generator",
            reviewer_model_id="anthropic/claude-haiku-4.5",
            generation_config=GenerationConfig(),
            output_dir=tmp_path,
            concurrency=4,
        )

    assert (tmp_path / "initial" / "PFM001.json").exists()
    assert (tmp_path / "semantic_reviews" / "PFM001.json").exists()
    assert not (tmp_path / "PFM001.json").exists()
    assert not (tmp_path / "manifests" / "PFM001.json").exists()
    failure = ScenarioGenerationFailure.model_validate_json(
        (tmp_path / "failures" / "PFM001.json").read_text(encoding="utf-8")
    )
    assert failure.failed_stage == ExperimentStage.SCENARIO_REVISION


def test_final_family_is_written_after_audit_manifests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify the top-level family acts as the final persistence commit marker."""
    seed = load_test_v6_seed()
    family = make_v6_family(seed)
    client = FakeV6GenerationClient(make_semantic_review(family))
    written_paths: List[Path] = []

    def record_atomic_write(path: Path, content: str) -> None:
        """Record persistence order while writing valid fixture content."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written_paths.append(path)

    monkeypatch.setattr(
        "scripts.generate_v6_scenario_drafts.write_text_atomic",
        record_atomic_write,
    )
    generate_review_and_revise_family(
        client=client,
        seed=seed,
        generator_model_id="openai/gpt-generator",
        reviewer_model_id="anthropic/claude-haiku-4.5",
        generation_config=GenerationConfig(),
        output_dir=tmp_path,
        concurrency=1,
    )

    assert written_paths[-1] == tmp_path / "PFM001.json"
    assert json.loads(written_paths[-1].read_text(encoding="utf-8"))["schema_version"] == (
        "scenario_family.v6"
    )


def test_completed_family_artifact_cannot_be_silently_overwritten(tmp_path: Path) -> None:
    """Verify a reused successful run directory cannot expose stale family output."""
    seed = load_test_v6_seed()
    family = make_v6_family(seed)
    (tmp_path / "PFM001.json").write_text(family.model_dump_json(), encoding="utf-8")
    client = FakeV6GenerationClient(make_semantic_review(family))

    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        generate_review_and_revise_family(
            client=client,
            seed=seed,
            generator_model_id="openai/gpt-generator",
            reviewer_model_id="anthropic/claude-haiku-4.5",
            generation_config=GenerationConfig(),
            output_dir=tmp_path,
            concurrency=1,
        )

    assert client.calls == []
