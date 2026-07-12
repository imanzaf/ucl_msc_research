"""Run reviewed scenario artifacts through agent models and the user simulator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from loguru import logger

from src.data_models.experiments import (
    ActivationCaptureStatus,
    ExperimentConfig,
    ExperimentStage,
    ExperimentUsageSummary,
    GenerationConfig,
    RunUnitIdentity,
    ScenarioRunRecord,
)
from src.data_models.scenarios import (
    InteractionMode,
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
    UserSimulatorTurnInput,
    UserSimulatorTurnOutput,
    visible_actions_from_user_actions,
    visible_beliefs_from_user_beliefs,
)
from src.experiments.io import (
    append_jsonl,
    create_timestamped_run_id,
    load_scenario_families,
    prepare_experiment_dir,
    read_jsonl_models,
    result_paths,
    write_experiment_config,
)
from src.llm.openrouter import LLMCallResult, OpenRouterStructuredClient

SCENARIO_RUN_PROMPT_VERSION = "scenario_run_v1"
USER_SIMULATOR_PROMPT_VERSION = "user_simulator_prompt_v1"


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


def initial_prompt_for_persona(instance: ScenarioInstance, persona_id: UserPersonaId) -> str:
    """Return the scenario's first user prompt for a reusable persona."""
    prompt_values = instance.initial_user_prompt.model_dump()
    return str(prompt_values[persona_id.value])


def prompt_variant_by_condition(
    family: ScenarioFamily,
    condition: PromptCondition,
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
    for family in families:
        if not filter_allowed(family.scenario_family_id, scenario_family_ids):
            continue
        for instance in family.scenario_instances:
            if not filter_allowed(instance.scenario_id, scenario_ids):
                continue
            for variant in family.prompt_variants:
                if allowed_conditions is not None and variant.condition not in allowed_conditions:
                    continue
                for persona_id in UserPersonaId:
                    if allowed_personas is not None and persona_id not in allowed_personas:
                        continue
                    for agent_model_id in agent_model_ids:
                        yield family, instance, variant, persona_id, agent_model_id


def transcript_to_messages(
    system_prompt: str,
    transcript: List[ConversationTurn],
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
    summary: ExperimentUsageSummary,
    call_ids: List[str],
    result: LLMCallResult,
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


def request_user_turn(
    client: OpenRouterStructuredClient,
    unit: RunUnitIdentity,
    model_id: str,
    turn_input: UserSimulatorTurnInput,
    generation_config: GenerationConfig,
) -> LLMCallResult[UserSimulatorTurnOutput]:
    """Request one structured user-simulator follow-up turn."""
    prompt_template = UserSimulatorPromptTemplate()
    return client.complete_structured(
        stage=ExperimentStage.USER_SIMULATOR_TURN,
        model_id=model_id,
        messages=simulator_messages(prompt_template.render_next_turn_prompt(turn_input)),
        output_model=UserSimulatorTurnOutput,
        generation_config=generation_config,
        prompt_version=USER_SIMULATOR_PROMPT_VERSION,
        metadata=metadata_for_unit(unit=unit, stage=ExperimentStage.USER_SIMULATOR_TURN),
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
    max_followup_turns: int,
) -> ScenarioRunRecord:
    """Run one scenario instance for a single prompt/persona/model unit."""
    unit = RunUnitIdentity(
        scenario_family_id=family.scenario_family_id,
        scenario_id=instance.scenario_id,
        interaction_mode=family.interaction_mode,
        prompt_condition=variant.condition,
        persona_id=persona_id,
        agent_model_id=agent_model_id,
    )
    usage_summary = ExperimentUsageSummary()
    call_ids: List[str] = []
    simulator_turn_outputs: List[UserSimulatorTurnOutput] = []
    system_prompt = family.prompt_template.render_system_prompt(
        instructions=variant.system_prompt,
        reference_text=instance.reference_text,
    )
    initial_user_prompt = initial_prompt_for_persona(instance=instance, persona_id=persona_id)
    transcript = [
        ConversationTurn(
            speaker=ConversationSpeaker.USER,
            turn_index=1,
            content=initial_user_prompt,
        )
    ]

    agent_result = request_agent_response(
        client=agent_client,
        unit=unit,
        system_prompt=system_prompt,
        transcript=transcript,
        generation_config=generation_config,
    )
    add_call_usage(summary=usage_summary, call_ids=call_ids, result=agent_result)
    transcript.append(
        ConversationTurn(
            speaker=ConversationSpeaker.AGENT,
            turn_index=2,
            content=agent_result.parsed,
        )
    )

    if family.interaction_mode == InteractionMode.MULTI_TURN:
        for followup_turn_index in range(1, max_followup_turns + 1):
            turn_input = UserSimulatorTurnInput(
                user_role=family.user_role,
                user_goal=instance.user_goal,
                agent_role=family.agent_role,
                persona=persona_for_id(persona_id),
                user_facing_context=instance.user_facing_context,
                conversation_so_far=transcript,
                followup_turn_index=followup_turn_index,
                max_followup_turns=max_followup_turns,
            )
            turn_result = request_user_turn(
                client=user_simulator_client,
                unit=unit,
                model_id=user_simulator_model,
                turn_input=turn_input,
                generation_config=generation_config,
            )
            add_call_usage(summary=usage_summary, call_ids=call_ids, result=turn_result)
            simulator_turn_outputs.append(turn_result.parsed)
            if not turn_result.parsed.should_continue:
                break
            transcript.append(
                ConversationTurn(
                    speaker=ConversationSpeaker.USER,
                    turn_index=len(transcript) + 1,
                    content=turn_result.parsed.utterance or "",
                )
            )
            agent_result = request_agent_response(
                client=agent_client,
                unit=unit,
                system_prompt=system_prompt,
                transcript=transcript,
                generation_config=generation_config,
            )
            add_call_usage(summary=usage_summary, call_ids=call_ids, result=agent_result)
            transcript.append(
                ConversationTurn(
                    speaker=ConversationSpeaker.AGENT,
                    turn_index=len(transcript) + 1,
                    content=agent_result.parsed,
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
        user_simulator_turns=simulator_turn_outputs,
        user_simulator_outcome=outcome_result.parsed,
        call_ids=call_ids,
        usage_summary=usage_summary,
        activation_capture=ActivationCaptureStatus.DISABLED_API_ONLY,
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
    scenario_families = load_scenario_families(Path(experiment_config.scenario_run_dir))
    scenario_run_id = run_id or create_timestamped_run_id()
    output_path = experiment_dir / "results" / f"{scenario_run_id}_results.jsonl"
    usage_path = experiment_dir / "results" / f"{scenario_run_id}_scenario_usage.json"
    skip_ids = set(existing_run_unit_ids(experiment_dir)) if experiment_config.resume else set()
    stage_usage = ExperimentUsageSummary()
    produced_records: List[ScenarioRunRecord] = []

    logger.info(
        "Activation capture is disabled for v1 API-only OpenRouter runs: {}",
        experiment_config.activation_capture.value,
    )
    specs = iter_run_specs(
        families=scenario_families,
        agent_model_ids=experiment_config.agent_model_ids,
        scenario_family_ids=scenario_family_ids,
        scenario_ids=scenario_ids,
        prompt_conditions=prompt_conditions,
        persona_ids=persona_ids,
    )
    for index, (family, instance, variant, persona_id, agent_model_id) in enumerate(specs, start=1):
        unit_id = "__".join(
            [
                family.scenario_family_id,
                instance.scenario_id,
                variant.condition.value,
                persona_id.value,
                agent_model_id.replace("/", "_"),
            ]
        )
        if unit_id in skip_ids:
            logger.info("Skipping previously completed run unit {}", unit_id)
            continue
        if limit is not None and len(produced_records) >= limit:
            break
        logger.info("Running scenario unit {} ({})", index, unit_id)
        record = run_one_scenario_unit(
            agent_client=agent_client,
            user_simulator_client=user_simulator_client,
            experiment_name=experiment_config.experiment_name,
            run_id=scenario_run_id,
            family=family,
            instance=instance,
            variant=variant,
            persona_id=persona_id,
            agent_model_id=agent_model_id,
            user_simulator_model=experiment_config.user_simulator_model,
            generation_config=experiment_config.generation_config,
            max_followup_turns=experiment_config.max_followup_turns,
        )
        append_jsonl(path=output_path, records=[record])
        stage_usage.merge(record.usage_summary)
        produced_records.append(record)

    write_usage_summary(path=usage_path, summary=stage_usage)
    logger.success(
        "Wrote {} scenario-run record(s) to {}",
        len(produced_records),
        output_path,
    )
    logger.info("Scenario-run usage summary: {}", json.dumps(stage_usage.model_dump()))
    return produced_records
