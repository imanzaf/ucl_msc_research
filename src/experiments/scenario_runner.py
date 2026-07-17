"""Run reviewed scenario artifacts through agent models and the user simulator."""

from __future__ import annotations

import hashlib
import json
import math
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from loguru import logger

from src.data_models.experiments import (
    ActivationCaptureStatus,
    ConversationProtocol,
    ExperimentConfig,
    ExperimentStage,
    ExperimentUsageSummary,
    GenerationConfig,
    RunUnitIdentity,
    ScenarioRunRecord,
    ScoredRunRecord,
)
from src.data_models.scenario_review import (
    PilotExpansionStatus,
    PilotHumanAnnotationArtifact,
    ScenarioPilotExpansionGate,
    artifact_sha256,
    calculate_pilot_omission_precision_recall,
    calculate_quadratic_weighted_kappa,
)
from src.data_models.scenarios import (
    DisclosureCheckpoint,
    FactEvaluationRole,
    PromptCondition,
    PromptVariant,
    ScenarioFamily,
    ScenarioInstance,
)
from src.data_models.user_personas import (
    CommunicationStyle,
    EmotionIntensity,
    RiskAppetite,
    UserEmotion,
    UserPersona,
    UserPersonaId,
)
from src.data_models.user_simulator import (
    ConversationSpeaker,
    ConversationTurn,
    UserSimulatorOutcome,
    UserSimulatorOutcomeInput,
    UserSimulatorPromptTemplate,
    visible_actions_from_user_actions,
    visible_beliefs_from_user_beliefs,
)
from src.experiments.io import (
    add_record_usage,
    append_jsonl,
    create_timestamped_run_id,
    load_scenario_families,
    prepare_experiment_dir,
    read_jsonl_models,
    result_paths,
    summarize_record_usage,
    write_experiment_config,
)
from src.llm.openrouter import LLMCallResult, OpenRouterStructuredClient
from src.prompts.scenarios.persona_tone import ACTIVE_PERSONA_IDS, ACTIVE_PERSONA_TONE_PREFIXES

SCENARIO_RUN_PROMPT_VERSION = "scenario_run_v1"
USER_SIMULATOR_PROMPT_VERSION = "user_simulator_prompt_v1"
PILOT_FAMILY_IDS = {"PFM001", "RW001"}
PILOT_AGENT_MODEL_ID = "meta-llama/llama-3.3-70b-instruct"
PILOT_EXPANSION_GATE_PATH = Path("pilot_validation") / "manifest.json"


@dataclass(frozen=True)
class ScenarioRunSpec:
    """Store one selected scenario/prompt/persona/model run unit."""

    index: int
    family: ScenarioFamily
    instance: ScenarioInstance
    variant: PromptVariant
    persona_id: UserPersonaId
    agent_model_id: str

    @property
    def unit_id(self) -> str:
        """Return the stable run-unit id for this selected scenario spec."""
        return RunUnitIdentity(
            scenario_family_id=self.family.scenario_family_id,
            scenario_id=self.instance.scenario_id,
            interaction_mode=self.family.interaction_mode,
            prompt_condition=self.variant.condition,
            persona_id=self.persona_id,
            agent_model_id=self.agent_model_id,
            scenario_family_sha256=artifact_sha256(self.family),
        ).run_unit_id


def persona_for_id(persona_id: UserPersonaId) -> UserPersona:
    """Return the reusable persona object for one persona id."""
    persona_traits = {
        UserPersonaId.NEUTRAL_BASELINE: (
            UserEmotion.NEUTRAL,
            EmotionIntensity.NEUTRAL,
            RiskAppetite.BALANCED,
            CommunicationStyle.BALANCED,
        ),
        UserPersonaId.ANXIOUS_RISK_AVERSE: (
            UserEmotion.ANXIOUS,
            EmotionIntensity.HIGH,
            RiskAppetite.RISK_AVERSE,
            CommunicationStyle.DETAIL_ORIENTED,
        ),
        UserPersonaId.POSITIVE_RISK_SEEKING: (
            UserEmotion.CONFIDENT,
            EmotionIntensity.HIGH,
            RiskAppetite.RISK_SEEKING,
            CommunicationStyle.TRUSTING_DIRECT,
        ),
    }
    emotion, intensity, risk_appetite, communication_style = persona_traits[persona_id]
    return UserPersona(
        persona_id=persona_id,
        emotion=emotion,
        emotion_intensity=intensity,
        risk_appetite=risk_appetite,
        communication_style=communication_style,
    )


def tone_wrap_prompt(prompt: str, persona_id: UserPersonaId) -> str:
    """Apply a code-owned affect-only persona wrapper to a fixed request."""
    return f"{ACTIVE_PERSONA_TONE_PREFIXES[persona_id]}{prompt}"


def initial_prompt_for_persona(instance: ScenarioInstance, persona_id: UserPersonaId) -> str:
    """Return the scenario's first user prompt for a reusable persona."""
    return tone_wrap_prompt(prompt=instance.core_initial_request, persona_id=persona_id)


def prompt_variant_by_condition(
    family: ScenarioFamily, condition: PromptCondition
) -> PromptVariant:
    """Return a family's prompt variant for one prompt condition."""
    for variant in family.prompt_variants:
        if variant.condition == condition:
            return variant
    raise ValueError(f"family {family.scenario_family_id} lacks prompt condition {condition.value}")


def filter_allowed(value: str, allowed_values: Optional[Sequence[str]]) -> bool:
    """Return whether a value passes an optional allow-list filter."""
    return allowed_values is None or value in allowed_values


def iter_run_specs(
    families: Iterable[ScenarioFamily],
    agent_model_ids: Sequence[str],
    scenario_family_ids: Optional[Sequence[str]] = None,
    scenario_ids: Optional[Sequence[str]] = None,
    prompt_conditions: Optional[Sequence[str]] = None,
    persona_ids: Optional[Sequence[str]] = None,
) -> Iterable[Tuple[ScenarioFamily, ScenarioInstance, PromptVariant, UserPersonaId, str]]:
    """Yield every scenario/prompt/persona/model combination selected for execution."""
    allowed_conditions = (
        {PromptCondition(value) for value in prompt_conditions} if prompt_conditions else None
    )
    allowed_personas = {UserPersonaId(value) for value in persona_ids} if persona_ids else None
    if allowed_personas is not None:
        unsupported_personas = allowed_personas - set(ACTIVE_PERSONA_IDS)
        if unsupported_personas:
            unsupported_values = ", ".join(
                sorted(persona_id.value for persona_id in unsupported_personas)
            )
            raise ValueError(
                f"current scenarios do not run these persona ids: {unsupported_values}"
            )
    for family in families:
        if not filter_allowed(family.scenario_family_id, scenario_family_ids):
            continue
        for instance in family.scenario_instances:
            if not filter_allowed(instance.scenario_id, scenario_ids):
                continue
            for variant in family.prompt_variants:
                if allowed_conditions is not None and variant.condition not in allowed_conditions:
                    continue
                for persona_id in ACTIVE_PERSONA_IDS:
                    if allowed_personas is not None and persona_id not in allowed_personas:
                        continue
                    for agent_model_id in agent_model_ids:
                        yield family, instance, variant, persona_id, agent_model_id


def build_selected_run_specs(
    families: Iterable[ScenarioFamily],
    agent_model_ids: Sequence[str],
    skip_ids: Iterable[str],
    scenario_family_ids: Optional[Sequence[str]] = None,
    scenario_ids: Optional[Sequence[str]] = None,
    prompt_conditions: Optional[Sequence[str]] = None,
    persona_ids: Optional[Sequence[str]] = None,
    limit: Optional[int] = None,
) -> List[ScenarioRunSpec]:
    """Return selected run specs after filters, resume skips, and an optional limit."""
    selected_specs: List[ScenarioRunSpec] = []
    skipped_unit_ids = set(skip_ids)
    specs = iter_run_specs(
        families=families,
        agent_model_ids=agent_model_ids,
        scenario_family_ids=scenario_family_ids,
        scenario_ids=scenario_ids,
        prompt_conditions=prompt_conditions,
        persona_ids=persona_ids,
    )
    for index, (family, instance, variant, persona_id, agent_model_id) in enumerate(specs, start=1):
        spec = ScenarioRunSpec(
            index=index,
            family=family,
            instance=instance,
            variant=variant,
            persona_id=persona_id,
            agent_model_id=agent_model_id,
        )
        if spec.unit_id in skipped_unit_ids:
            logger.info("Skipping previously completed run unit {}", spec.unit_id)
            continue
        if limit is not None and len(selected_specs) >= limit:
            break
        selected_specs.append(spec)
    return selected_specs


def resolve_pilot_evidence_path(scenario_run_dir: Path, configured_path: str) -> Path:
    """Resolve one pilot-evidence path relative to the reviewed scenario run."""
    path = Path(configured_path)
    return path if path.is_absolute() else scenario_run_dir / path


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of one persisted evidence artifact."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expected_primary_annotation_keys(
    instance: ScenarioInstance,
) -> Set[Tuple[str, DisclosureCheckpoint]]:
    """Return the four primary-fact/checkpoint keys required by the human audit."""
    return {
        (fact.fact_unit_id, checkpoint)
        for fact in instance.fact_units
        if fact.evaluation_role == FactEvaluationRole.PRIMARY_ADVERSE_TARGET
        for checkpoint in fact.expected_checkpoints
    }


def recompute_pilot_validation_metrics(
    pilot_records: List[ScoredRunRecord],
    pilot_families: List[ScenarioFamily],
    annotations: PilotHumanAnnotationArtifact,
    manifest: ScenarioPilotExpansionGate,
) -> Tuple[float, float, float]:
    """Align human labels to scored facts and recompute all pilot-validation statistics."""
    records_by_id = {record.run_unit.run_unit_id: record for record in pilot_records}
    instances_by_key = {
        (family.scenario_family_id, instance.scenario_id): instance
        for family in pilot_families
        for instance in family.scenario_instances
    }
    annotation_ids = {item.run_unit_id for item in annotations.conversations}
    if annotation_ids != set(manifest.audited_conversation_ids):
        raise ValueError("pilot annotation conversations do not match the 36-case audit")
    second_reviewed_ids = {
        item.run_unit_id
        for item in annotations.conversations
        if item.judgments[0].secondary_human_status is not None
    }
    if second_reviewed_ids != set(manifest.second_reviewed_conversation_ids):
        raise ValueError("pilot annotation second reviews do not match the 12-case subset")

    automated_human_pairs = []
    reviewer_pairs = []
    for conversation in annotations.conversations:
        record = records_by_id.get(conversation.run_unit_id)
        if record is None:
            raise ValueError("pilot annotation references an unknown scored run unit")
        instance_key = (record.run_unit.scenario_family_id, record.run_unit.scenario_id)
        instance = instances_by_key.get(instance_key)
        if instance is None:
            raise ValueError("pilot annotation references an unknown accepted scenario")
        expected_keys = expected_primary_annotation_keys(instance)
        annotation_keys = {(item.fact_unit_id, item.checkpoint) for item in conversation.judgments}
        if annotation_keys != expected_keys:
            raise ValueError("pilot annotation does not cover every primary fact checkpoint")
        automated_by_key = {
            (item.fact_unit_id, item.checkpoint): item.disclosure_status
            for item in record.direct_disclosure_assessment.judgments
        }
        for item in conversation.judgments:
            key = (item.fact_unit_id, item.checkpoint)
            if key not in automated_by_key:
                raise ValueError("pilot scored assessment lacks a human-audited fact checkpoint")
            automated_human_pairs.append((automated_by_key[key], item.primary_human_status))
            if item.secondary_human_status is not None:
                reviewer_pairs.append((item.primary_human_status, item.secondary_human_status))
    precision, recall = calculate_pilot_omission_precision_recall(automated_human_pairs)
    kappa = calculate_quadratic_weighted_kappa(reviewer_pairs)
    return precision, recall, kappa


def validate_recomputed_pilot_metrics(
    manifest: ScenarioPilotExpansionGate,
    precision: float,
    recall: float,
    kappa: float,
) -> None:
    """Require assessor-reported pilot statistics to equal deterministic recomputation."""
    reported_and_computed = [
        ("omission_precision", manifest.omission_precision, precision),
        ("omission_recall", manifest.omission_recall, recall),
        ("weighted_inter_reviewer_kappa", manifest.weighted_inter_reviewer_kappa, kappa),
    ]
    for metric_name, reported, computed in reported_and_computed:
        if not math.isclose(reported, computed, rel_tol=1e-9, abs_tol=1e-9):
            raise ValueError(f"reported {metric_name} does not match annotation recomputation")


def validate_pilot_evidence_artifacts(
    scenario_run_dir: Path,
    manifest: ScenarioPilotExpansionGate,
) -> None:
    """Bind a passed pilot gate to exact result and human-annotation artifacts."""
    pilot_results_path = resolve_pilot_evidence_path(scenario_run_dir, manifest.pilot_results_path)
    annotations_path = resolve_pilot_evidence_path(
        scenario_run_dir, manifest.human_annotations_path
    )
    for path, expected_hash in [
        (pilot_results_path, manifest.pilot_results_sha256),
        (annotations_path, manifest.human_annotations_sha256),
    ]:
        if not path.is_file():
            raise ValueError(f"pilot evidence artifact does not exist: {path}")
        if sha256_file(path) != expected_hash:
            raise ValueError(f"pilot evidence artifact hash mismatch: {path}")

    pilot_records = read_jsonl_models(path=pilot_results_path, model=ScoredRunRecord)
    annotations = PilotHumanAnnotationArtifact.model_validate_json(
        annotations_path.read_text(encoding="utf-8")
    )
    actual_run_unit_ids = [record.run_unit.run_unit_id for record in pilot_records]
    if len(actual_run_unit_ids) != manifest.pilot_conversation_count:
        raise ValueError("pilot result artifact does not contain exactly 48 conversations")
    if set(actual_run_unit_ids) != set(manifest.pilot_run_unit_ids):
        raise ValueError("pilot result artifact run units do not match the expansion manifest")
    if {record.run_unit.scenario_family_id for record in pilot_records} != set(
        manifest.pilot_family_ids
    ):
        raise ValueError("pilot result artifact does not cover the declared families")
    if {record.run_unit.agent_model_id for record in pilot_records} != {
        manifest.pilot_agent_model_id
    }:
        raise ValueError("pilot result artifact does not use the declared single agent model")
    pilot_families = load_scenario_families(
        scenario_run_dir, scenario_family_ids=manifest.pilot_family_ids
    )
    expected_run_unit_ids = {
        spec.unit_id
        for spec in build_selected_run_specs(
            families=pilot_families,
            agent_model_ids=[manifest.pilot_agent_model_id],
            skip_ids=[],
        )
    }
    if set(actual_run_unit_ids) != expected_run_unit_ids:
        raise ValueError(
            "pilot result artifact does not match the complete accepted family/prompt/persona matrix"
        )
    precision, recall, kappa = recompute_pilot_validation_metrics(
        pilot_records=pilot_records,
        pilot_families=pilot_families,
        annotations=annotations,
        manifest=manifest,
    )
    validate_recomputed_pilot_metrics(
        manifest=manifest, precision=precision, recall=recall, kappa=kappa
    )


def validate_pilot_expansion_gate(
    scenario_run_dir: Path,
    selected_family_ids: Sequence[str],
    selected_agent_model_ids: Sequence[str],
) -> None:
    """Require passed evidence before adding a family or agent model beyond the pilot."""
    selected_families = set(selected_family_ids)
    if not selected_families:
        return
    if selected_families.issubset(PILOT_FAMILY_IDS) and set(selected_agent_model_ids) == {
        PILOT_AGENT_MODEL_ID
    }:
        return
    manifest_path = scenario_run_dir / PILOT_EXPANSION_GATE_PATH
    if not manifest_path.exists():
        raise ValueError("non-pilot execution requires pilot_validation/manifest.json")
    manifest = ScenarioPilotExpansionGate.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    if manifest.status != PilotExpansionStatus.PASSED:
        raise ValueError(f"pilot expansion gate is not passed: {manifest.status.value}")
    if manifest.pilot_agent_model_id != PILOT_AGENT_MODEL_ID:
        raise ValueError("pilot evidence does not use the fixed primary agent model")
    validate_pilot_evidence_artifacts(scenario_run_dir=scenario_run_dir, manifest=manifest)


def group_specs_by_family(
    specs: Sequence[ScenarioRunSpec],
) -> List[Tuple[str, List[ScenarioRunSpec]]]:
    """Group selected specs by family while preserving first-seen order."""
    grouped_specs: Dict[str, List[ScenarioRunSpec]] = {}
    for spec in specs:
        grouped_specs.setdefault(spec.family.scenario_family_id, []).append(spec)
    return list(grouped_specs.items())


def group_specs_by_scenario(
    specs: Sequence[ScenarioRunSpec],
) -> List[Tuple[str, List[ScenarioRunSpec]]]:
    """Group selected specs by scenario instance while preserving first-seen order."""
    grouped_specs: Dict[str, List[ScenarioRunSpec]] = {}
    for spec in specs:
        grouped_specs.setdefault(spec.instance.scenario_id, []).append(spec)
    return list(grouped_specs.items())


def transcript_to_messages(
    system_prompt: str, transcript: List[ConversationTurn]
) -> List[Dict[str, str]]:
    """Convert a typed transcript into OpenRouter chat messages."""
    messages = [{"role": "system", "content": system_prompt}]
    for turn in transcript:
        role = "user" if turn.speaker == ConversationSpeaker.USER else "assistant"
        messages.append({"role": role, "content": turn.content})
    return messages


def simulator_messages(prompt: str) -> List[Dict[str, str]]:
    """Wrap a rendered simulator prompt as OpenRouter chat messages."""
    return [{"role": "user", "content": prompt}]


def add_call_usage(
    summary: ExperimentUsageSummary, call_ids: List[str], result: LLMCallResult[Any]
) -> None:
    """Accumulate one LLM call result into a run usage summary."""
    summary.add_call(usage=result.record.usage, cache_hit=result.record.cache_hit)
    call_ids.append(result.record.call_id)


def metadata_for_unit(unit: RunUnitIdentity, stage: ExperimentStage) -> Dict[str, str]:
    """Build OpenRouter metadata for observability and sticky routing."""
    return {
        "stage": stage.value,
        "scenario_family_id": unit.scenario_family_id,
        "scenario_id": unit.scenario_id,
        "prompt_condition": unit.prompt_condition.value,
        "persona_id": unit.persona_id.value,
        "agent_model_id": unit.agent_model_id,
        "session_id": unit.run_unit_id[:256],
    }


def request_agent_response(
    client: OpenRouterStructuredClient,
    unit: RunUnitIdentity,
    system_prompt: str,
    transcript: List[ConversationTurn],
    generation_config: GenerationConfig,
) -> LLMCallResult[str]:
    """Request the next agent response for the current conversation."""
    return client.complete_text(
        stage=ExperimentStage.AGENT_RESPONSE,
        model_id=unit.agent_model_id,
        messages=transcript_to_messages(system_prompt=system_prompt, transcript=transcript),
        generation_config=generation_config,
        prompt_version=SCENARIO_RUN_PROMPT_VERSION,
        metadata=metadata_for_unit(unit=unit, stage=ExperimentStage.AGENT_RESPONSE),
    )


def request_user_outcome(
    client: OpenRouterStructuredClient,
    unit: RunUnitIdentity,
    model_id: str,
    outcome_input: UserSimulatorOutcomeInput,
    generation_config: GenerationConfig,
) -> LLMCallResult[UserSimulatorOutcome]:
    """Request one structured post-conversation user outcome."""
    prompt_template = UserSimulatorPromptTemplate()
    return client.complete_structured(
        stage=ExperimentStage.USER_SIMULATOR_OUTCOME,
        model_id=model_id,
        messages=simulator_messages(prompt_template.render_outcome_prompt(outcome_input)),
        output_model=UserSimulatorOutcome,
        generation_config=generation_config,
        prompt_version=USER_SIMULATOR_PROMPT_VERSION,
        metadata=metadata_for_unit(unit=unit, stage=ExperimentStage.USER_SIMULATOR_OUTCOME),
    )


def build_outcome_input(
    family: ScenarioFamily,
    instance: ScenarioInstance,
    persona_id: UserPersonaId,
    transcript: List[ConversationTurn],
) -> UserSimulatorOutcomeInput:
    """Build simulator-visible outcome input without hidden harm/support labels."""
    return UserSimulatorOutcomeInput(
        user_role=family.user_role,
        user_goal=instance.user_goal,
        agent_role=family.agent_role,
        persona=persona_for_id(persona_id),
        user_facing_context=instance.user_facing_context,
        conversation=transcript,
        available_actions=visible_actions_from_user_actions(instance.possible_user_actions),
        available_beliefs=visible_beliefs_from_user_beliefs(instance.possible_user_beliefs),
    )


def run_one_scenario_unit(
    agent_client: OpenRouterStructuredClient,
    user_simulator_client: OpenRouterStructuredClient,
    experiment_name: str,
    run_id: str,
    family: ScenarioFamily,
    instance: ScenarioInstance,
    variant: PromptVariant,
    persona_id: UserPersonaId,
    agent_model_id: str,
    user_simulator_model: str,
    generation_config: GenerationConfig,
) -> ScenarioRunRecord:
    """Run one scenario instance for a single prompt/persona/model unit."""
    unit = RunUnitIdentity(
        scenario_family_id=family.scenario_family_id,
        scenario_id=instance.scenario_id,
        interaction_mode=family.interaction_mode,
        prompt_condition=variant.condition,
        persona_id=persona_id,
        agent_model_id=agent_model_id,
        scenario_family_sha256=artifact_sha256(family),
    )
    usage_summary = ExperimentUsageSummary()
    call_ids: List[str] = []
    system_prompt = family.prompt_template.render_system_prompt(
        instructions=variant.system_prompt,
        reference_text=instance.reference_text,
    )
    initial_user_prompt = initial_prompt_for_persona(instance=instance, persona_id=persona_id)
    transcript = [
        ConversationTurn(
            speaker=ConversationSpeaker.USER, turn_index=1, content=initial_user_prompt
        )
    ]

    first_agent_result = request_agent_response(
        client=agent_client,
        unit=unit,
        system_prompt=system_prompt,
        transcript=transcript,
        generation_config=generation_config,
    )
    add_call_usage(summary=usage_summary, call_ids=call_ids, result=first_agent_result)
    transcript.append(
        ConversationTurn(
            speaker=ConversationSpeaker.AGENT, turn_index=2, content=first_agent_result.parsed
        )
    )
    transcript.append(
        ConversationTurn(
            speaker=ConversationSpeaker.USER,
            turn_index=3,
            content=tone_wrap_prompt(prompt=instance.core_risk_followup, persona_id=persona_id),
        )
    )
    second_agent_result = request_agent_response(
        client=agent_client,
        unit=unit,
        system_prompt=system_prompt,
        transcript=transcript,
        generation_config=generation_config,
    )
    add_call_usage(summary=usage_summary, call_ids=call_ids, result=second_agent_result)
    transcript.append(
        ConversationTurn(
            speaker=ConversationSpeaker.AGENT, turn_index=4, content=second_agent_result.parsed
        )
    )

    outcome_input = build_outcome_input(
        family=family,
        instance=instance,
        persona_id=persona_id,
        transcript=transcript,
    )
    outcome_result = request_user_outcome(
        client=user_simulator_client,
        unit=unit,
        model_id=user_simulator_model,
        outcome_input=outcome_input,
        generation_config=generation_config,
    )
    add_call_usage(summary=usage_summary, call_ids=call_ids, result=outcome_result)
    outcome_result.parsed.validate_against_options(outcome_input)

    return ScenarioRunRecord(
        experiment_name=experiment_name,
        run_id=run_id,
        run_unit=unit,
        system_prompt=system_prompt,
        initial_user_prompt=initial_user_prompt,
        transcript=transcript,
        user_simulator_outcome=outcome_result.parsed,
        call_ids=call_ids,
        usage_summary=usage_summary,
        activation_capture=ActivationCaptureStatus.DISABLED_API_ONLY,
        conversation_protocol=ConversationProtocol.SCRIPTED_RISK_FOLLOWUP,
    )


def existing_run_unit_ids(experiment_dir: Path) -> List[str]:
    """Return run-unit ids already present in scenario-run result files."""
    ids: List[str] = []
    for path in result_paths(
        experiment_dir=experiment_dir, pattern="????????T??????_results.jsonl"
    ):
        for record in read_jsonl_models(path=path, model=ScenarioRunRecord):
            ids.append(record.run_unit.run_unit_id)
    return ids


def write_usage_summary(path: Path, summary: ExperimentUsageSummary) -> None:
    """Persist a stage-level usage summary as JSON."""
    path.write_text(summary.model_dump_json(indent=2), encoding="utf-8")


def run_one_selected_spec(
    agent_client: OpenRouterStructuredClient,
    user_simulator_client: OpenRouterStructuredClient,
    experiment_config: ExperimentConfig,
    run_id: str,
    spec: ScenarioRunSpec,
) -> ScenarioRunRecord:
    """Run one selected run spec through the conversation loop."""
    logger.info("Running scenario unit {} ({})", spec.index, spec.unit_id)
    return run_one_scenario_unit(
        agent_client=agent_client,
        user_simulator_client=user_simulator_client,
        experiment_name=experiment_config.experiment_name,
        run_id=run_id,
        family=spec.family,
        instance=spec.instance,
        variant=spec.variant,
        persona_id=spec.persona_id,
        agent_model_id=spec.agent_model_id,
        user_simulator_model=experiment_config.user_simulator_model,
        generation_config=experiment_config.generation_config,
    )


def run_spec_sequence(
    agent_client: OpenRouterStructuredClient,
    user_simulator_client: OpenRouterStructuredClient,
    experiment_config: ExperimentConfig,
    run_id: str,
    specs: Sequence[ScenarioRunSpec],
) -> List[ScenarioRunRecord]:
    """Run selected specs sequentially and return completed records."""
    records: List[ScenarioRunRecord] = []
    for spec in specs:
        records.append(
            run_one_selected_spec(
                agent_client=agent_client,
                user_simulator_client=user_simulator_client,
                experiment_config=experiment_config,
                run_id=run_id,
                spec=spec,
            )
        )
    return records


def run_specs_family_concurrent(
    agent_client: OpenRouterStructuredClient,
    user_simulator_client: OpenRouterStructuredClient,
    experiment_config: ExperimentConfig,
    run_id: str,
    specs: Sequence[ScenarioRunSpec],
    collect_records: Callable[[Sequence[ScenarioRunRecord]], None],
) -> None:
    """Run scenario instances concurrently within each family, with families sequential."""
    for family_id, family_specs in group_specs_by_family(specs):
        scenario_groups = group_specs_by_scenario(family_specs)
        worker_count = min(experiment_config.family_scenario_concurrency, len(scenario_groups))
        logger.info("Running family {} with {} scenario worker(s)", family_id, worker_count)
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures: Dict[Future[List[ScenarioRunRecord]], str] = {
                executor.submit(
                    run_spec_sequence,
                    agent_client,
                    user_simulator_client,
                    experiment_config,
                    run_id,
                    scenario_specs,
                ): scenario_id
                for scenario_id, scenario_specs in scenario_groups
            }
            for future in as_completed(futures):
                scenario_id = futures[future]
                scenario_records = future.result()
                collect_records(scenario_records)
                logger.info("Completed scenario instance {}", scenario_id)


def run_scenarios(
    agent_client: OpenRouterStructuredClient,
    user_simulator_client: OpenRouterStructuredClient,
    experiment_root: Path,
    experiment_config: ExperimentConfig,
    scenario_family_ids: Optional[Sequence[str]] = None,
    scenario_ids: Optional[Sequence[str]] = None,
    prompt_conditions: Optional[Sequence[str]] = None,
    persona_ids: Optional[Sequence[str]] = None,
    run_id: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[ScenarioRunRecord]:
    """Run selected reviewed scenarios and persist transcript/outcome records."""
    experiment_dir = prepare_experiment_dir(
        experiment_root=experiment_root,
        experiment_name=experiment_config.experiment_name,
    )
    write_experiment_config(experiment_dir=experiment_dir, config=experiment_config)
    scenario_families = load_scenario_families(
        Path(experiment_config.scenario_run_dir),
        scenario_family_ids=scenario_family_ids,
        scenario_ids=scenario_ids,
    )
    scenario_run_id = run_id or create_timestamped_run_id()
    output_path = experiment_dir / "results" / f"{scenario_run_id}_results.jsonl"
    usage_path = experiment_dir / "results" / f"{scenario_run_id}_scenario_usage.json"
    skip_ids = set(existing_run_unit_ids(experiment_dir)) if experiment_config.resume else set()
    existing_output_records = (
        read_jsonl_models(path=output_path, model=ScenarioRunRecord)
        if experiment_config.resume
        else []
    )
    stage_usage = (
        summarize_record_usage(existing_output_records)
        if experiment_config.resume
        else ExperimentUsageSummary()
    )
    produced_records: List[ScenarioRunRecord] = []

    logger.info(
        "Activation capture is disabled for API-only OpenRouter runs: {}",
        experiment_config.activation_capture.value,
    )
    specs = build_selected_run_specs(
        families=scenario_families,
        agent_model_ids=experiment_config.agent_model_ids,
        skip_ids=skip_ids,
        scenario_family_ids=scenario_family_ids,
        scenario_ids=scenario_ids,
        prompt_conditions=prompt_conditions,
        persona_ids=persona_ids,
        limit=limit,
    )
    validate_pilot_expansion_gate(
        scenario_run_dir=Path(experiment_config.scenario_run_dir),
        selected_family_ids=[spec.family.scenario_family_id for spec in specs],
        selected_agent_model_ids=[spec.agent_model_id for spec in specs],
    )

    def collect_records(records: Sequence[ScenarioRunRecord]) -> None:
        """Store completed run records in output artifacts and in-memory run state."""
        if not records:
            return
        append_jsonl(path=output_path, records=records)
        add_record_usage(summary=stage_usage, records=records)
        produced_records.extend(records)

    if experiment_config.family_scenario_concurrency > 1:
        run_specs_family_concurrent(
            agent_client=agent_client,
            user_simulator_client=user_simulator_client,
            experiment_config=experiment_config,
            run_id=scenario_run_id,
            specs=specs,
            collect_records=collect_records,
        )
    else:
        collect_records(
            run_spec_sequence(
                agent_client=agent_client,
                user_simulator_client=user_simulator_client,
                experiment_config=experiment_config,
                run_id=scenario_run_id,
                specs=specs,
            )
        )

    write_usage_summary(path=usage_path, summary=stage_usage)
    logger.success("Wrote {} scenario-run record(s) to {}", len(produced_records), output_path)
    logger.info("Scenario-run usage summary: {}", json.dumps(stage_usage.model_dump()))
    return produced_records
