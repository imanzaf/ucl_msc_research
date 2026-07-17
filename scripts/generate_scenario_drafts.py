"""Generate, semantically audit, and revise controlled scenario-family drafts."""

from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from loguru import logger

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from configs.api_settings import OpenRouterCredentialRole, get_api_settings  # noqa: E402
from configs.model_settings import get_model_settings  # noqa: E402
from src.data_models.experiments import (  # noqa: E402
    ExperimentStage,
    ExperimentUsageSummary,
    GenerationConfig,
)
from src.data_models.prompt_controls import ACTIVE_PROMPT_CONTROL_PROFILE  # noqa: E402
from src.data_models.scenario_review import (  # noqa: E402
    SEMANTIC_REQUIREMENT_REGISTRY,
    RequirementAssessment,
    RequirementStatus,
    ScenarioGenerationFailure,
    ScenarioGenerationManifest,
    ScenarioRevisionAttempt,
    ScenarioSemanticReview,
    build_pending_human_review,
    route_failed_assessments,
    validate_semantic_review_coverage,
)
from src.data_models.scenarios import (  # noqa: E402
    GeneratedScenarioInstance,
    PromptCondition,
    PromptInstructions,
    PromptTemplate,
    PromptVariant,
    ScenarioFamily,
    ScenarioInstance,
    ScenarioSeed,
    ScenarioSeedCollection,
    ScenarioSeedReplication,
    ScenarioSeedTaskType,
    ScenarioTaskType,
)
from src.experiments.model_catalog import (  # noqa: E402
    default_scenario_generator_model_id,
    default_scenario_reviewer_model_id,
    validate_models_and_capabilities,
)
from src.llm.openrouter import LLMCallResult, OpenRouterStructuredClient  # noqa: E402
from src.prompts.scenarios.scenario_instance_generation import (  # noqa: E402
    SCENARIO_GENERATION_PROMPT_VERSION,
    SCENARIO_GENERATOR_INSTRUCTIONS,
    render_scenario_generation_prompt,
)
from src.prompts.scenarios.scenario_instance_revision import (  # noqa: E402
    SCENARIO_REVISION_INSTRUCTIONS,
    SCENARIO_REVISION_PROMPT_VERSION,
    render_scenario_revision_prompt,
)
from src.prompts.scenarios.scenario_semantic_review import (  # noqa: E402
    SCENARIO_SEMANTIC_REVIEW_PROMPT_VERSION,
    SEMANTIC_REVIEWER_INSTRUCTIONS,
    render_semantic_review_prompt,
)

DEFAULT_SCENARIO_ROOT = Path("data/inputs/scenarios")
DEFAULT_SCENARIO_SET = "v0.3.1"
SEED_FILENAME = "scenario_generation_seeds.json"
RUNS_DIRNAME = "runs"
RUN_ID_PATTERN = re.compile(r"^[0-9]{8}T[0-9]{6}$")
PROMPT_VARIANT_ORDER = [
    PromptCondition.NEUTRAL,
    PromptCondition.PRODUCTION_BASELINE,
    PromptCondition.PRODUCTION_INTEGRITY,
]


@dataclass(frozen=True)
class InitialScenarioResult:
    """Store one assembled initial scenario and its generation call record."""

    instance: ScenarioInstance
    call_result: LLMCallResult[GeneratedScenarioInstance]


@dataclass(frozen=True)
class RevisionScenarioResult:
    """Store one revised scenario and its revision call record."""

    instance: ScenarioInstance
    findings: List[RequirementAssessment]
    call_result: LLMCallResult[GeneratedScenarioInstance]


@dataclass(frozen=True)
class SemanticReviewCallResult:
    """Store the accepted semantic review call and all coverage-attempt records."""

    attempts: List[LLMCallResult[ScenarioSemanticReview]]

    @property
    def parsed(self) -> ScenarioSemanticReview:
        """Return the final coverage-valid semantic review."""
        return self.attempts[-1].parsed


def resolve_scenario_root(scenario_root: Path) -> Path:
    """Resolve a scenario root relative to the repository when needed."""
    if scenario_root.is_absolute():
        return scenario_root
    return REPO_ROOT / scenario_root


def resolve_scenario_set_dir(scenario_root: Path, scenario_set: str) -> Path:
    """Return one safe versioned scenario-set directory."""
    scenario_set_path = Path(scenario_set)
    if scenario_set_path.is_absolute() or len(scenario_set_path.parts) != 1:
        raise ValueError("scenario set must be one directory name such as v0.3.1")
    if scenario_set_path.parts[0] in {"", ".", ".."}:
        raise ValueError("scenario set must be one safe directory name")
    return resolve_scenario_root(scenario_root) / scenario_set_path


def create_timestamped_run_id() -> str:
    """Create a timestamp identifier for one generation run."""
    return datetime.now().strftime("%Y%m%dT%H%M%S")


def resolve_run_output_dir(scenario_set_dir: Path, run_id: str) -> Path:
    """Return the validated timestamped generation output directory."""
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("run id must use YYYYMMDDTHHMMSS format")
    return scenario_set_dir / RUNS_DIRNAME / run_id


def parse_positive_int(value: str) -> int:
    """Parse a command-line integer that must be positive."""
    try:
        parsed_value = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be an integer") from exc
    if parsed_value < 1:
        raise argparse.ArgumentTypeError("value must be at least 1")
    return parsed_value


def load_scenario_seeds(path: Path) -> List[ScenarioSeed]:
    """Load and validate the current seed collection."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return list(ScenarioSeedCollection.model_validate(payload).seeds)


def assemble_prompt_variant(
    seed: ScenarioSeed,
    condition: PromptCondition,
) -> PromptVariant:
    """Build one code-owned agent prompt condition from family instructions."""
    invariant_guidance = [
        *ACTIVE_PROMPT_CONTROL_PROFILE.invariant_core_instructions,
        *seed.invariant_task_constraints,
    ]
    guidance = list(invariant_guidance)
    if condition != PromptCondition.NEUTRAL:
        guidance.extend(ACTIVE_PROMPT_CONTROL_PROFILE.baseline_factuality_instructions)
    integrity = (
        list(ACTIVE_PROMPT_CONTROL_PROFILE.integrity_completeness_instructions)
        if condition == PromptCondition.PRODUCTION_INTEGRITY
        else []
    )
    return PromptVariant(
        prompt_variant_id=f"{seed.scenario_family_id}_{condition.value}",
        condition=condition,
        system_prompt=PromptInstructions(
            agent_role=seed.agent_role,
            agent_task=seed.agent_task,
            guidance=guidance,
            integrity_instructions=integrity,
        ),
    )


def assemble_instance(
    generated: GeneratedScenarioInstance,
    task_type: ScenarioSeedTaskType,
    replication: ScenarioSeedReplication,
) -> ScenarioInstance:
    """Attach seed-owned task and replication metadata to generated fields."""
    return ScenarioInstance(
        **generated.model_dump(),
        scenario_id=replication.scenario_id,
        task_type_id=task_type.task_type_id,
        replication_id=replication.replication_id,
        user_goal=task_type.user_goal,
        reference_format=task_type.reference_format,
        core_initial_request=task_type.core_initial_request,
        core_risk_followup=task_type.core_risk_followup,
        variation_brief=replication.variation_brief,
    )


def build_task_type(task_type: ScenarioSeedTaskType) -> ScenarioTaskType:
    """Convert one seed task into persisted family metadata."""
    return ScenarioTaskType(
        task_type_id=task_type.task_type_id,
        task_archetype=task_type.task_archetype,
        reference_format=task_type.reference_format,
        user_goal=task_type.user_goal,
        core_initial_request=task_type.core_initial_request,
        core_risk_followup=task_type.core_risk_followup,
        scenario_ids=[replication.scenario_id for replication in task_type.replications],
    )


def assemble_family(
    seed: ScenarioSeed,
    instances: List[ScenarioInstance],
) -> ScenarioFamily:
    """Assemble and validate one complete family from scenario instances."""
    return ScenarioFamily(
        scenario_family_id=seed.scenario_family_id,
        segment=seed.segment,
        interaction_mode=seed.interaction_mode,
        tool_using=seed.tool_using,
        agent_role=seed.agent_role,
        agent_task=seed.agent_task,
        invariant_task_constraints=list(seed.invariant_task_constraints),
        task_guidance=list(ACTIVE_PROMPT_CONTROL_PROFILE.baseline_factuality_instructions),
        integrity_instructions=list(
            ACTIVE_PROMPT_CONTROL_PROFILE.integrity_completeness_instructions
        ),
        user_role=seed.user_role,
        task_types=[build_task_type(task_type) for task_type in seed.task_types],
        scenario_instances=instances,
        prompt_variants=[
            assemble_prompt_variant(seed=seed, condition=condition)
            for condition in PROMPT_VARIANT_ORDER
        ],
        prompt_template=PromptTemplate(),
    )


def request_initial_scenario(
    client: OpenRouterStructuredClient,
    seed: ScenarioSeed,
    task_type: ScenarioSeedTaskType,
    replication: ScenarioSeedReplication,
    model_id: str,
    generation_config: GenerationConfig,
) -> InitialScenarioResult:
    """Generate and assemble one initial scenario replication."""
    call_result = client.complete_structured(
        stage=ExperimentStage.SCENARIO_GENERATION,
        model_id=model_id,
        messages=[
            {"role": "system", "content": SCENARIO_GENERATOR_INSTRUCTIONS},
            {
                "role": "user",
                "content": render_scenario_generation_prompt(seed, task_type, replication),
            },
        ],
        output_model=GeneratedScenarioInstance,
        generation_config=generation_config,
        prompt_version=SCENARIO_GENERATION_PROMPT_VERSION,
        metadata={
            "stage": ExperimentStage.SCENARIO_GENERATION.value,
            "scenario_family_id": seed.scenario_family_id,
            "scenario_id": replication.scenario_id,
            "session_id": f"scenario-generate__{seed.scenario_family_id}__{replication.scenario_id}",
        },
    )
    return InitialScenarioResult(
        instance=assemble_instance(call_result.parsed, task_type, replication),
        call_result=call_result,
    )


def generate_initial_family_scenarios(
    client: OpenRouterStructuredClient,
    seed: ScenarioSeed,
    model_id: str,
    generation_config: GenerationConfig,
    concurrency: int,
) -> List[InitialScenarioResult]:
    """Generate all four initial scenarios with bounded within-family concurrency."""
    specs = [
        (task_type, replication)
        for task_type in seed.task_types
        for replication in task_type.replications
    ]
    if concurrency <= 1:
        return [
            request_initial_scenario(
                client=client,
                seed=seed,
                task_type=task_type,
                replication=replication,
                model_id=model_id,
                generation_config=generation_config,
            )
            for task_type, replication in specs
        ]

    results_by_index: Dict[int, InitialScenarioResult] = {}
    worker_count = min(concurrency, len(specs))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures: Dict[Future[InitialScenarioResult], int] = {
            executor.submit(
                request_initial_scenario,
                client,
                seed,
                task_type,
                replication,
                model_id,
                generation_config,
            ): index
            for index, (task_type, replication) in enumerate(specs)
        }
        for future in as_completed(futures):
            results_by_index[futures[future]] = future.result()
    return [results_by_index[index] for index in range(len(specs))]


def request_semantic_review(
    client: OpenRouterStructuredClient,
    seed: ScenarioSeed,
    family: ScenarioFamily,
    reviewer_model_id: str,
    output_dir: Optional[Path] = None,
) -> SemanticReviewCallResult:
    """Request one deterministic independent semantic audit for a complete family."""
    base_messages = [
        {"role": "system", "content": SEMANTIC_REVIEWER_INSTRUCTIONS},
        {"role": "user", "content": render_semantic_review_prompt(seed, family)},
    ]
    attempts: List[LLMCallResult[ScenarioSemanticReview]] = []
    coverage_error: Optional[ValueError] = None
    for attempt_index in range(getattr(client, "max_retries", 0) + 1):
        messages = list(base_messages)
        if coverage_error is not None:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Your previous structured matrix failed exact coverage validation: "
                        f"{coverage_error}. Return the complete matrix with no missing or extra assessments."
                    ),
                }
            )
        result = client.complete_structured(
            stage=ExperimentStage.SCENARIO_SEMANTIC_REVIEW,
            model_id=reviewer_model_id,
            messages=messages,
            output_model=ScenarioSemanticReview,
            generation_config=GenerationConfig(temperature=0.0),
            prompt_version=(
                SCENARIO_SEMANTIC_REVIEW_PROMPT_VERSION
                if attempt_index == 0
                else f"{SCENARIO_SEMANTIC_REVIEW_PROMPT_VERSION}_retry_{attempt_index + 1}"
            ),
            metadata={
                "stage": ExperimentStage.SCENARIO_SEMANTIC_REVIEW.value,
                "scenario_family_id": family.scenario_family_id,
                "session_id": f"scenario-review__{family.scenario_family_id}",
            },
            require_supported_parameters=True,
        )
        attempts.append(result)
        if output_dir is not None:
            persist_semantic_review_attempt(
                output_dir=output_dir,
                review=result.parsed,
                attempt_number=attempt_index + 1,
            )
        try:
            validate_semantic_review_coverage(review=result.parsed, family=family)
            return SemanticReviewCallResult(attempts=attempts)
        except ValueError as exc:
            coverage_error = exc
    raise ValueError("semantic review coverage failed after configured retries") from coverage_error


def paired_instance_for(
    family: ScenarioFamily,
    instance: ScenarioInstance,
) -> ScenarioInstance:
    """Return the other replication belonging to a scenario's task type."""
    paired = [
        candidate
        for candidate in family.scenario_instances
        if candidate.task_type_id == instance.task_type_id
        and candidate.scenario_id != instance.scenario_id
    ]
    if len(paired) != 1:
        raise ValueError(
            f"scenario {instance.scenario_id} does not have exactly one paired replication"
        )
    return paired[0]


def seed_task_type_for(
    seed: ScenarioSeed,
    task_type_id: str,
) -> ScenarioSeedTaskType:
    """Return seed-owned task metadata for one task_type_id."""
    for task_type in seed.task_types:
        if task_type.task_type_id == task_type_id:
            return task_type
    raise ValueError(f"seed lacks task type {task_type_id}")


def seed_replication_for(
    task_type: ScenarioSeedTaskType,
    scenario_id: str,
) -> ScenarioSeedReplication:
    """Return seed-owned replication metadata for one scenario id."""
    for replication in task_type.replications:
        if replication.scenario_id == scenario_id:
            return replication
    raise ValueError(f"task type {task_type.task_type_id} lacks scenario {scenario_id}")


def request_scenario_revision(
    client: OpenRouterStructuredClient,
    seed: ScenarioSeed,
    family: ScenarioFamily,
    instance: ScenarioInstance,
    findings: List[RequirementAssessment],
    generator_model_id: str,
    generation_config: GenerationConfig,
) -> RevisionScenarioResult:
    """Request and assemble one full replacement for a flagged scenario."""
    task_type = seed_task_type_for(seed, instance.task_type_id)
    replication = seed_replication_for(task_type, instance.scenario_id)
    call_result = client.complete_structured(
        stage=ExperimentStage.SCENARIO_REVISION,
        model_id=generator_model_id,
        messages=[
            {"role": "system", "content": SCENARIO_REVISION_INSTRUCTIONS},
            {
                "role": "user",
                "content": render_scenario_revision_prompt(
                    task_type=task_type,
                    replication=replication,
                    instance=instance,
                    paired_instance=paired_instance_for(family, instance),
                    findings=findings,
                ),
            },
        ],
        output_model=GeneratedScenarioInstance,
        generation_config=generation_config,
        prompt_version=SCENARIO_REVISION_PROMPT_VERSION,
        metadata={
            "stage": ExperimentStage.SCENARIO_REVISION.value,
            "scenario_family_id": seed.scenario_family_id,
            "scenario_id": instance.scenario_id,
            "session_id": f"scenario-revise__{seed.scenario_family_id}__{instance.scenario_id}",
        },
    )
    return RevisionScenarioResult(
        instance=assemble_instance(call_result.parsed, task_type, replication),
        findings=findings,
        call_result=call_result,
    )


def revise_flagged_scenarios(
    client: OpenRouterStructuredClient,
    seed: ScenarioSeed,
    family: ScenarioFamily,
    findings_by_scenario: Dict[str, List[RequirementAssessment]],
    generator_model_id: str,
    generation_config: GenerationConfig,
    concurrency: int,
) -> List[RevisionScenarioResult]:
    """Revise only flagged scenarios with bounded within-family concurrency."""
    flagged_instances = [
        instance
        for instance in family.scenario_instances
        if instance.scenario_id in findings_by_scenario
    ]
    if not flagged_instances:
        return []
    if concurrency <= 1:
        return [
            request_scenario_revision(
                client=client,
                seed=seed,
                family=family,
                instance=instance,
                findings=findings_by_scenario[instance.scenario_id],
                generator_model_id=generator_model_id,
                generation_config=generation_config,
            )
            for instance in flagged_instances
        ]

    results_by_id: Dict[str, RevisionScenarioResult] = {}
    worker_count = min(concurrency, len(flagged_instances))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures: Dict[Future[RevisionScenarioResult], str] = {
            executor.submit(
                request_scenario_revision,
                client,
                seed,
                family,
                instance,
                findings_by_scenario[instance.scenario_id],
                generator_model_id,
                generation_config,
            ): instance.scenario_id
            for instance in flagged_instances
        }
        for future in as_completed(futures):
            results_by_id[futures[future]] = future.result()
    return [results_by_id[instance.scenario_id] for instance in flagged_instances]


def apply_revisions(
    initial_family: ScenarioFamily,
    revisions: List[RevisionScenarioResult],
    seed: ScenarioSeed,
) -> ScenarioFamily:
    """Replace flagged initial instances and revalidate the complete final family."""
    revisions_by_id = {revision.instance.scenario_id: revision.instance for revision in revisions}
    final_instances = [
        revisions_by_id.get(instance.scenario_id, instance)
        for instance in initial_family.scenario_instances
    ]
    return assemble_family(seed=seed, instances=final_instances)


def add_usage(summary: ExperimentUsageSummary, result: LLMCallResult[Any]) -> None:
    """Accumulate one generation-pipeline call into a usage summary."""
    summary.add_call(usage=result.record.usage, cache_hit=result.record.cache_hit)


def write_text_atomic(path: Path, content: str) -> None:
    """Write text through a sibling temporary file before atomically replacing the target."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(content, encoding="utf-8")
    temporary_path.replace(path)


def render_failed_findings_markdown(review: ScenarioSemanticReview) -> str:
    """Render failed semantic findings for the consolidated human review document."""
    failed = [
        assessment
        for assessment in review.assessments
        if assessment.status == RequirementStatus.FAIL
    ]
    if not failed:
        findings = "No automated semantic findings."
    else:
        findings = "\n\n".join(
            (
                f"### `{assessment.finding_id}`: {assessment.requirement_id.value}\n\n"
                f"- Requirement: {SEMANTIC_REQUIREMENT_REGISTRY[assessment.requirement_id].description}\n"
                f"- Subject: `{assessment.subject_scope.value}:{assessment.subject_id}`\n"
                f"- Affected scenarios: {', '.join(assessment.affected_scenario_ids)}\n"
                f"- Type: `{assessment.finding_type.value}`\n"
                f"- Evidence: {assessment.evidence}\n"
                f"- Problem: {assessment.problem}\n"
                f"- Required correction: {assessment.required_correction}\n"
                f"- Fields: {', '.join(assessment.affected_field_paths)}"
            )
            for assessment in failed
        )
    return findings


def render_family_review_markdown(
    family: ScenarioFamily,
    review: ScenarioSemanticReview,
    revised_scenario_ids: List[str],
) -> str:
    """Render the final family plus unresolved human-review responsibilities."""
    scenario_sections = []
    for instance in family.scenario_instances:
        fact_rows = "\n".join(
            (
                f"- `{fact.fact_unit_id}` ({fact.evaluation_role.value}, pair "
                f"`{fact.comparison_pair_id or 'none'}`): {fact.fact}\n"
                f"  - Polarity / risk / requirement: `{fact.polarity.value}` / "
                f"`{fact.risk_category.value}` / `{fact.disclosure_requirement.value}`\n"
                f"  - Source: {fact.source_locator}\n"
                f"  - Source rationale: {fact.reference_rationale}\n"
                f"  - Materiality: {fact.materiality_rationale}\n"
                f"  - Expected disclosure: {fact.expected_disclosure}\n"
                f"  - Specificity markers: {', '.join(fact.specificity_markers) or 'none'}\n"
                f"  - Checkpoints: {', '.join(item.value for item in fact.expected_checkpoints)}"
            )
            for fact in instance.fact_units
        )
        user_context_rows = "\n".join(f"- {item}" for item in instance.user_facing_context)
        action_rows = "\n".join(
            (
                f"- `{action.action_id}` (harmful: {'yes' if action.is_harmful else 'no'}): "
                f"{action.label}: {action.description}"
            )
            for action in instance.possible_user_actions
        )
        belief_rows = "\n".join(
            (
                f"- `{belief.belief_id}` (`{belief.supported_by_fact_pool.value}`): "
                f"{belief.belief}"
            )
            for belief in instance.possible_user_beliefs
        )
        scenario_sections.append(
            f"""### `{instance.scenario_id}`: {instance.title}

- Task: `{instance.task_type_id}`
- Replication: `{instance.replication_id}`
- Automated revision attempted: {'yes' if instance.scenario_id in revised_scenario_ids else 'no'}
- Summary: {instance.generated_summary}
- User goal: {instance.user_goal}
- Source format: `{instance.reference_format.value}`
- Variation brief: {instance.variation_brief}
- Initial request: {instance.core_initial_request}
- Risk follow-up: {instance.core_risk_followup}

#### Source Packet

```text
{instance.reference_text}
```

#### Fact Units

{fact_rows}

#### User-Only Context

{user_context_rows}

#### Possible Actions

{action_rows}

#### Possible Beliefs

{belief_rows}
"""
        )
    failed_count = sum(
        assessment.status == RequirementStatus.FAIL for assessment in review.assessments
    )
    rendered_scenarios = "\n\n".join(scenario_sections)
    rendered_findings = render_failed_findings_markdown(review)
    return f"""# Scenario Family `{family.scenario_family_id}`

- Automated semantic findings: {failed_count}
- Human acceptance: pending

The automated reviewer ran before revision. Review each requested correction against the final source and fact metadata;
revision attempts are not evidence of resolution.

## Automated Review Summary

{review.review_summary}

## Automated Findings

{rendered_findings}

## Final Scenarios

{rendered_scenarios}
"""


def persist_initial_family(output_dir: Path, family: ScenarioFamily) -> None:
    """Persist initial family evidence before making the semantic-review call."""
    write_text_atomic(
        output_dir / "initial" / f"{family.scenario_family_id}.json",
        family.model_dump_json(indent=2),
    )


def persist_semantic_review(output_dir: Path, review: ScenarioSemanticReview) -> None:
    """Persist the machine-readable semantic-review artifact."""
    write_text_atomic(
        output_dir / "semantic_reviews" / f"{review.scenario_family_id}.json",
        review.model_dump_json(indent=2),
    )


def persist_semantic_review_attempt(
    output_dir: Path,
    review: ScenarioSemanticReview,
    attempt_number: int,
) -> None:
    """Persist every parsed semantic-review attempt before coverage alignment."""
    write_text_atomic(
        output_dir
        / "semantic_reviews"
        / "attempts"
        / f"{review.scenario_family_id}_attempt_{attempt_number}.json",
        review.model_dump_json(indent=2),
    )


def persist_final_artifacts(
    output_dir: Path,
    family: ScenarioFamily,
    review: ScenarioSemanticReview,
    manifest: ScenarioGenerationManifest,
) -> None:
    """Atomically persist the final family and its audit and human-review artifacts."""
    write_text_atomic(
        output_dir / "human_reviews" / f"{family.scenario_family_id}.md",
        render_family_review_markdown(
            family=family,
            review=review,
            revised_scenario_ids=[attempt.scenario_id for attempt in manifest.revision_attempts],
        ),
    )
    write_text_atomic(
        output_dir / "manifests" / f"{family.scenario_family_id}.json",
        manifest.model_dump_json(indent=2),
    )
    write_text_atomic(
        output_dir / "human_reviews" / f"{family.scenario_family_id}.json",
        build_pending_human_review(
            review=review,
            family=family,
            manifest=manifest,
        ).model_dump_json(indent=2),
    )
    # The top-level family is the loader-visible commit marker for a successful run.
    write_text_atomic(
        output_dir / f"{family.scenario_family_id}.json",
        family.model_dump_json(indent=2),
    )


def _generate_review_and_revise_family(
    client: OpenRouterStructuredClient,
    seed: ScenarioSeed,
    generator_model_id: str,
    reviewer_model_id: str,
    generation_config: GenerationConfig,
    output_dir: Path,
    concurrency: int,
) -> ScenarioFamily:
    """Generate, audit, selectively revise, and persist one complete family."""
    final_family_path = output_dir / f"{seed.scenario_family_id}.json"
    if final_family_path.exists():
        raise FileExistsError(
            f"refusing to overwrite completed family artifact: {final_family_path}"
        )
    initial_results = generate_initial_family_scenarios(
        client=client,
        seed=seed,
        model_id=generator_model_id,
        generation_config=generation_config,
        concurrency=concurrency,
    )
    initial_family = assemble_family(
        seed=seed,
        instances=[result.instance for result in initial_results],
    )
    persist_initial_family(output_dir=output_dir, family=initial_family)

    review_result = request_semantic_review(
        client=client,
        seed=seed,
        family=initial_family,
        reviewer_model_id=reviewer_model_id,
        output_dir=output_dir,
    )
    persist_semantic_review(output_dir=output_dir, review=review_result.parsed)
    findings_by_scenario = route_failed_assessments(review_result.parsed)
    revisions = revise_flagged_scenarios(
        client=client,
        seed=seed,
        family=initial_family,
        findings_by_scenario=findings_by_scenario,
        generator_model_id=generator_model_id,
        generation_config=generation_config,
        concurrency=concurrency,
    )
    final_family = apply_revisions(initial_family=initial_family, revisions=revisions, seed=seed)

    usage_summary = ExperimentUsageSummary()
    for initial_result in initial_results:
        add_usage(usage_summary, initial_result.call_result)
    for review_attempt in review_result.attempts:
        add_usage(usage_summary, review_attempt)
    for revision in revisions:
        add_usage(usage_summary, revision.call_result)
    manifest = ScenarioGenerationManifest(
        scenario_family_id=seed.scenario_family_id,
        generator_model_id=generator_model_id,
        reviewer_model_id=reviewer_model_id,
        initial_call_ids={
            result.instance.scenario_id: result.call_result.record.call_id
            for result in initial_results
        },
        semantic_review_call_ids=[attempt.record.call_id for attempt in review_result.attempts],
        reviewed_scenario_ids=[
            instance.scenario_id for instance in initial_family.scenario_instances
        ],
        finding_ids_by_scenario={
            scenario_id: [assessment.finding_id for assessment in assessments]
            for scenario_id, assessments in findings_by_scenario.items()
        },
        revision_attempts=[
            ScenarioRevisionAttempt(
                scenario_id=revision.instance.scenario_id,
                finding_ids=[assessment.finding_id for assessment in revision.findings],
                revision_call_id=revision.call_result.record.call_id,
            )
            for revision in revisions
        ],
        semantic_resolution_verified=False,
        usage_summary=usage_summary,
    )
    persist_final_artifacts(
        output_dir=output_dir,
        family=final_family,
        review=review_result.parsed,
        manifest=manifest,
    )
    return final_family


def infer_failed_stage(output_dir: Path, scenario_family_id: str) -> ExperimentStage:
    """Infer the failed stage from the last successfully persisted audit artifact."""
    initial_path = output_dir / "initial" / f"{scenario_family_id}.json"
    semantic_review_path = output_dir / "semantic_reviews" / f"{scenario_family_id}.json"
    if not initial_path.exists():
        return ExperimentStage.SCENARIO_GENERATION
    if not semantic_review_path.exists():
        return ExperimentStage.SCENARIO_SEMANTIC_REVIEW
    return ExperimentStage.SCENARIO_REVISION


def persist_generation_failure(
    output_dir: Path,
    scenario_family_id: str,
    error: Exception,
) -> None:
    """Persist a typed terminal failure artifact without creating a final family JSON."""
    failure = ScenarioGenerationFailure(
        scenario_family_id=scenario_family_id,
        failed_stage=infer_failed_stage(output_dir, scenario_family_id),
        error_type=type(error).__name__,
        error_message=str(error) or repr(error),
        failed_at=datetime.now().astimezone().isoformat(),
    )
    write_text_atomic(
        output_dir / "failures" / f"{scenario_family_id}.json",
        failure.model_dump_json(indent=2),
    )


def generate_review_and_revise_family(
    client: OpenRouterStructuredClient,
    seed: ScenarioSeed,
    generator_model_id: str,
    reviewer_model_id: str,
    generation_config: GenerationConfig,
    output_dir: Path,
    concurrency: int,
) -> ScenarioFamily:
    """Run one family and preserve typed failure provenance on terminal errors."""
    claim_path = output_dir / "claims" / f"{seed.scenario_family_id}.lock"
    claim_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with claim_path.open("x", encoding="utf-8") as claim_handle:
            claim_handle.write(datetime.now().astimezone().isoformat())
    except FileExistsError as exc:
        raise RuntimeError(
            f"family generation is already active: {seed.scenario_family_id}"
        ) from exc
    try:
        try:
            return _generate_review_and_revise_family(
                client=client,
                seed=seed,
                generator_model_id=generator_model_id,
                reviewer_model_id=reviewer_model_id,
                generation_config=generation_config,
                output_dir=output_dir,
                concurrency=concurrency,
            )
        except Exception as exc:
            persist_generation_failure(
                output_dir=output_dir,
                scenario_family_id=seed.scenario_family_id,
                error=exc,
            )
            raise
    finally:
        claim_path.unlink(missing_ok=True)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments for generation, review, and revision."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario-set", default=DEFAULT_SCENARIO_SET)
    parser.add_argument("--scenario-root", default=str(DEFAULT_SCENARIO_ROOT))
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--max-families", type=parse_positive_int, default=None)
    parser.add_argument("--family-scenario-concurrency", type=parse_positive_int, default=1)
    parser.add_argument("--skip-model-validation", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the complete generation, semantic-review, and revision pipeline."""
    args = parse_args(argv)
    scenario_set_dir = resolve_scenario_set_dir(Path(args.scenario_root), args.scenario_set)
    run_id = args.run_id or create_timestamped_run_id()
    output_dir = resolve_run_output_dir(scenario_set_dir, run_id)
    generator_model_id = default_scenario_generator_model_id()
    reviewer_model_id = default_scenario_reviewer_model_id()
    api_settings = get_api_settings()
    model_settings = get_model_settings()
    if not args.skip_model_validation:
        validate_models_and_capabilities(
            model_ids=[generator_model_id, reviewer_model_id],
            required_parameters_by_model={reviewer_model_id: {"response_format"}},
            api_settings=api_settings,
            credential_role=OpenRouterCredentialRole.SCENARIO_GENERATION,
            timeout_seconds=model_settings.openrouter_request_timeout_seconds,
        )
    seeds = load_scenario_seeds(scenario_set_dir / SEED_FILENAME)
    if args.max_families is not None:
        seeds = seeds[: args.max_families]
    output_dir.mkdir(parents=True, exist_ok=True)
    client = OpenRouterStructuredClient.from_settings(
        api_settings=api_settings,
        model_settings=model_settings,
        credential_role=OpenRouterCredentialRole.SCENARIO_GENERATION,
        cache_dir=output_dir / "cache" / "llm_calls",
    )
    generation_config = GenerationConfig(
        temperature=model_settings.openrouter_temperature,
        seed=model_settings.openrouter_seed,
    )
    for index, seed in enumerate(seeds, start=1):
        logger.info("Processing family {}/{}: {}", index, len(seeds), seed.scenario_family_id)
        generate_review_and_revise_family(
            client=client,
            seed=seed,
            generator_model_id=generator_model_id,
            reviewer_model_id=reviewer_model_id,
            generation_config=generation_config,
            output_dir=output_dir,
            concurrency=args.family_scenario_concurrency,
        )
    logger.success("Generated {} reviewed family draft(s) in {}", len(seeds), output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
