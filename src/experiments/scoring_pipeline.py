"""Score completed scenario transcripts with LLM-assisted checks and pure metrics."""

from __future__ import annotations

import json
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from loguru import logger

from src.data_models.experiments import (
    ConversationProtocol,
    ExperimentConfig,
    ExperimentStage,
    ExperimentUsageSummary,
    GenerationConfig,
    RunUnitIdentity,
    ScenarioRunRecord,
    ScoredRunRecord,
)
from src.data_models.scenario_review import artifact_sha256
from src.data_models.scenarios import ScenarioInstance
from src.data_models.scenarios_v6 import (
    DisclosureCheckpoint,
    ScenarioFamilyArtifact,
    ScenarioInstanceArtifact,
    ScenarioInstanceV6,
)
from src.data_models.scoring import (
    DirectFactDisclosureAssessment,
    DisclaimerWashingCheck,
    FactContradictionCheck,
    FactUnitMatching,
    ResponseFactExtraction,
)
from src.data_models.user_simulator import UserSimulatorPromptTemplate
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
from src.prompts.output_processing.fact_unit_matching import (
    FACT_UNIT_MATCHING_INSTRUCTIONS,
    FACT_UNIT_MATCHING_TEMPLATE,
)
from src.prompts.output_processing.response_fact_extraction import (
    RESPONSE_FACT_EXTRACTION_INSTRUCTIONS,
    RESPONSE_FACT_EXTRACTION_TEMPLATE,
)
from src.prompts.scoring.direct_fact_disclosure_assessment import (
    DIRECT_FACT_DISCLOSURE_ASSESSMENT_INSTRUCTIONS,
    DIRECT_FACT_DISCLOSURE_ASSESSMENT_TEMPLATE,
)
from src.prompts.scoring.disclaimer_washing_check import (
    DISCLAIMER_WASHING_CHECK_INSTRUCTIONS,
    DISCLAIMER_WASHING_CHECK_TEMPLATE,
)
from src.prompts.scoring.fact_contradiction_check import (
    FACT_CONTRADICTION_CHECK_INSTRUCTIONS,
    FACT_CONTRADICTION_CHECK_TEMPLATE,
)
from src.scoring.metrics import (
    calculate_response_metrics,
    calculate_user_harm_metrics,
    calculate_v6_response_metrics,
    validate_direct_disclosure_alignment,
)

SCORING_PROMPT_VERSION = "post_run_scoring_v1"


@dataclass(frozen=True)
class DirectAssessmentCallResult:
    """Store the accepted direct assessment and all alignment-attempt records."""

    attempts: List[LLMCallResult[DirectFactDisclosureAssessment]]

    @property
    def parsed(self) -> DirectFactDisclosureAssessment:
        """Return the final alignment-valid direct assessment."""
        return self.attempts[-1].parsed


def index_scenario_instances(
    families: List[ScenarioFamilyArtifact],
) -> Dict[Tuple[str, str], Tuple[ScenarioFamilyArtifact, ScenarioInstanceArtifact]]:
    """Index scenario instances by family id and scenario id."""
    index: Dict[Tuple[str, str], Tuple[ScenarioFamilyArtifact, ScenarioInstanceArtifact]] = {}
    for family in families:
        for instance in family.scenario_instances:
            index[(family.scenario_family_id, instance.scenario_id)] = (family, instance)
    return index


def render_conversation(record: ScenarioRunRecord) -> str:
    """Render a completed transcript for scoring prompts."""
    return UserSimulatorPromptTemplate().render_conversation(record.transcript)


def render_fact_units(instance: ScenarioInstanceArtifact) -> str:
    """Render hidden ground-truth fact units as scoring-only JSON."""
    return json.dumps(
        [fact_unit.model_dump(mode="json") for fact_unit in instance.fact_units],
        indent=2,
        ensure_ascii=False,
    )


def render_extracted_facts(extraction: ResponseFactExtraction) -> str:
    """Render extracted facts as scoring-only JSON for downstream checks."""
    return json.dumps(
        extraction.model_dump(mode="json"),
        indent=2,
        ensure_ascii=False,
    )


def scoring_messages(instructions: str, prompt: str) -> List[Dict[str, str]]:
    """Wrap scoring instructions and prompt as OpenRouter chat messages."""
    return [
        {"role": "system", "content": instructions},
        {"role": "user", "content": prompt},
    ]


def add_call_usage(
    summary: ExperimentUsageSummary,
    call_ids: List[str],
    result: LLMCallResult[Any],
) -> None:
    """Accumulate one scoring LLM call into a usage summary."""
    summary.add_call(usage=result.record.usage, cache_hit=result.record.cache_hit)
    call_ids.append(result.record.call_id)


def metadata_for_score(unit: RunUnitIdentity, stage: ExperimentStage) -> Dict[str, str]:
    """Build OpenRouter metadata for scoring calls."""
    return {
        "stage": stage.value,
        "scenario_family_id": unit.scenario_family_id,
        "scenario_id": unit.scenario_id,
        "prompt_condition": unit.prompt_condition.value,
        "persona_id": unit.persona_id.value,
        "agent_model_id": unit.agent_model_id,
        "session_id": f"score__{unit.run_unit_id}"[:256],
    }


def request_extraction(
    client: OpenRouterStructuredClient,
    record: ScenarioRunRecord,
    scoring_model: str,
    generation_config: GenerationConfig,
) -> LLMCallResult[ResponseFactExtraction]:
    """Request structured fact extraction for a completed transcript."""
    prompt = RESPONSE_FACT_EXTRACTION_TEMPLATE.format(conversation=render_conversation(record))
    return client.complete_structured(
        stage=ExperimentStage.RESPONSE_FACT_EXTRACTION,
        model_id=scoring_model,
        messages=scoring_messages(RESPONSE_FACT_EXTRACTION_INSTRUCTIONS, prompt),
        output_model=ResponseFactExtraction,
        generation_config=generation_config,
        prompt_version=SCORING_PROMPT_VERSION,
        metadata=metadata_for_score(record.run_unit, ExperimentStage.RESPONSE_FACT_EXTRACTION),
    )


def request_matching(
    client: OpenRouterStructuredClient,
    record: ScenarioRunRecord,
    instance: ScenarioInstanceArtifact,
    extraction: ResponseFactExtraction,
    scoring_model: str,
    generation_config: GenerationConfig,
) -> LLMCallResult[FactUnitMatching]:
    """Request structured fact-to-ground-truth matching."""
    prompt = FACT_UNIT_MATCHING_TEMPLATE.format(
        ground_truth_fact_units=render_fact_units(instance),
        agent_context=instance.reference_text,
        conversation=render_conversation(record),
        extracted_facts=render_extracted_facts(extraction),
    )
    return client.complete_structured(
        stage=ExperimentStage.FACT_UNIT_MATCHING,
        model_id=scoring_model,
        messages=scoring_messages(FACT_UNIT_MATCHING_INSTRUCTIONS, prompt),
        output_model=FactUnitMatching,
        generation_config=generation_config,
        prompt_version=SCORING_PROMPT_VERSION,
        metadata=metadata_for_score(record.run_unit, ExperimentStage.FACT_UNIT_MATCHING),
    )


def request_contradiction_check(
    client: OpenRouterStructuredClient,
    record: ScenarioRunRecord,
    instance: ScenarioInstanceArtifact,
    extraction: ResponseFactExtraction,
    scoring_model: str,
    generation_config: GenerationConfig,
) -> LLMCallResult[FactContradictionCheck]:
    """Request structured contradiction checking."""
    prompt = FACT_CONTRADICTION_CHECK_TEMPLATE.format(
        ground_truth_fact_units=render_fact_units(instance),
        extracted_facts=render_extracted_facts(extraction),
        conversation=render_conversation(record),
    )
    return client.complete_structured(
        stage=ExperimentStage.FACT_CONTRADICTION_CHECK,
        model_id=scoring_model,
        messages=scoring_messages(FACT_CONTRADICTION_CHECK_INSTRUCTIONS, prompt),
        output_model=FactContradictionCheck,
        generation_config=generation_config,
        prompt_version=SCORING_PROMPT_VERSION,
        metadata=metadata_for_score(record.run_unit, ExperimentStage.FACT_CONTRADICTION_CHECK),
    )


def request_disclaimer_washing_check(
    client: OpenRouterStructuredClient,
    record: ScenarioRunRecord,
    instance: ScenarioInstance,
    extraction: ResponseFactExtraction,
    scoring_model: str,
    generation_config: GenerationConfig,
) -> LLMCallResult[DisclaimerWashingCheck]:
    """Request structured disclaimer-washing checking."""
    prompt = DISCLAIMER_WASHING_CHECK_TEMPLATE.format(
        ground_truth_fact_units=render_fact_units(instance),
        extracted_facts=render_extracted_facts(extraction),
        conversation=render_conversation(record),
    )
    return client.complete_structured(
        stage=ExperimentStage.DISCLAIMER_WASHING_CHECK,
        model_id=scoring_model,
        messages=scoring_messages(DISCLAIMER_WASHING_CHECK_INSTRUCTIONS, prompt),
        output_model=DisclaimerWashingCheck,
        generation_config=generation_config,
        prompt_version=SCORING_PROMPT_VERSION,
        metadata=metadata_for_score(record.run_unit, ExperimentStage.DISCLAIMER_WASHING_CHECK),
    )


def v6_checkpoint_responses(record: ScenarioRunRecord) -> Dict[DisclosureCheckpoint, str]:
    """Return the two agent responses required by the V6 scripted protocol."""
    if record.conversation_protocol != ConversationProtocol.SCRIPTED_RISK_FOLLOWUP_V1:
        raise ValueError("V6 direct scoring requires the scripted risk-follow-up protocol")
    agent_responses = [turn.content for turn in record.transcript if turn.speaker.value == "agent"]
    if len(agent_responses) != 2:
        raise ValueError("V6 direct scoring requires exactly two agent responses")
    return {
        DisclosureCheckpoint.INITIAL_RESPONSE: agent_responses[0],
        DisclosureCheckpoint.AFTER_RISK_FOLLOWUP: agent_responses[1],
    }


def request_direct_disclosure_assessment(
    client: OpenRouterStructuredClient,
    record: ScenarioRunRecord,
    instance: ScenarioInstanceV6,
    scoring_model: str,
    generation_config: GenerationConfig,
) -> DirectAssessmentCallResult:
    """Request complete V6 fact-by-checkpoint disclosure judgments."""
    checkpoint_responses = v6_checkpoint_responses(record)
    prompt = DIRECT_FACT_DISCLOSURE_ASSESSMENT_TEMPLATE.format(
        fact_units=render_fact_units(instance),
        initial_agent_response=checkpoint_responses[DisclosureCheckpoint.INITIAL_RESPONSE],
        followup_agent_response=checkpoint_responses[DisclosureCheckpoint.AFTER_RISK_FOLLOWUP],
    )
    base_messages = scoring_messages(DIRECT_FACT_DISCLOSURE_ASSESSMENT_INSTRUCTIONS, prompt)
    attempts: List[LLMCallResult[DirectFactDisclosureAssessment]] = []
    alignment_error: Optional[ValueError] = None
    for attempt_index in range(getattr(client, "max_retries", 0) + 1):
        messages = list(base_messages)
        if alignment_error is not None:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Your previous structured assessment failed deterministic alignment: "
                        f"{alignment_error}. Return complete judgments with verbatim evidence."
                    ),
                }
            )
        result = client.complete_structured(
            stage=ExperimentStage.DIRECT_FACT_DISCLOSURE_ASSESSMENT,
            model_id=scoring_model,
            messages=messages,
            output_model=DirectFactDisclosureAssessment,
            generation_config=generation_config,
            prompt_version=(
                "direct_fact_disclosure_assessment_v1"
                if attempt_index == 0
                else f"direct_fact_disclosure_assessment_v1_retry_{attempt_index + 1}"
            ),
            metadata=metadata_for_score(
                record.run_unit,
                ExperimentStage.DIRECT_FACT_DISCLOSURE_ASSESSMENT,
            ),
        )
        attempts.append(result)
        try:
            validate_direct_disclosure_alignment(
                assessment=result.parsed,
                fact_units=instance.fact_units,
                checkpoint_responses=checkpoint_responses,
            )
            return DirectAssessmentCallResult(attempts=attempts)
        except ValueError as exc:
            alignment_error = exc
    raise ValueError(
        "direct disclosure alignment failed after configured retries"
    ) from alignment_error


def score_one_run(
    client: OpenRouterStructuredClient,
    experiment_name: str,
    scoring_run_id: str,
    scenario_record: ScenarioRunRecord,
    instance: ScenarioInstanceArtifact,
    scoring_model: str,
    generation_config: GenerationConfig,
) -> ScoredRunRecord:
    """Score one completed scenario-run record."""
    usage_summary = ExperimentUsageSummary()
    call_ids: List[str] = []

    extraction_result = request_extraction(
        client=client,
        record=scenario_record,
        scoring_model=scoring_model,
        generation_config=generation_config,
    )
    add_call_usage(usage_summary, call_ids, extraction_result)

    matching_result = request_matching(
        client=client,
        record=scenario_record,
        instance=instance,
        extraction=extraction_result.parsed,
        scoring_model=scoring_model,
        generation_config=generation_config,
    )
    add_call_usage(usage_summary, call_ids, matching_result)

    contradiction_result = request_contradiction_check(
        client=client,
        record=scenario_record,
        instance=instance,
        extraction=extraction_result.parsed,
        scoring_model=scoring_model,
        generation_config=generation_config,
    )
    add_call_usage(usage_summary, call_ids, contradiction_result)

    direct_disclosure_assessment = None
    disclaimer_washing_check = None
    if isinstance(instance, ScenarioInstanceV6):
        direct_result = request_direct_disclosure_assessment(
            client=client,
            record=scenario_record,
            instance=instance,
            scoring_model=scoring_model,
            generation_config=generation_config,
        )
        for direct_attempt in direct_result.attempts:
            add_call_usage(usage_summary, call_ids, direct_attempt)
        direct_disclosure_assessment = direct_result.parsed
        response_metrics = calculate_v6_response_metrics(
            fact_units=instance.fact_units,
            disclosure_assessment=direct_result.parsed,
            checkpoint_responses=v6_checkpoint_responses(scenario_record),
            extraction=extraction_result.parsed,
            matching=matching_result.parsed,
            contradiction_check=contradiction_result.parsed,
        )
    else:
        disclaimer_result = request_disclaimer_washing_check(
            client=client,
            record=scenario_record,
            instance=instance,
            extraction=extraction_result.parsed,
            scoring_model=scoring_model,
            generation_config=generation_config,
        )
        add_call_usage(usage_summary, call_ids, disclaimer_result)
        disclaimer_washing_check = disclaimer_result.parsed
        response_metrics = calculate_response_metrics(
            fact_units=instance.fact_units,
            extraction=extraction_result.parsed,
            matching=matching_result.parsed,
            contradiction_check=contradiction_result.parsed,
            disclaimer_washing_check=disclaimer_result.parsed,
        )
    user_harm_metrics = calculate_user_harm_metrics(
        outcome=scenario_record.user_simulator_outcome,
        possible_user_actions=instance.possible_user_actions,
        possible_user_beliefs=instance.possible_user_beliefs,
    )

    return ScoredRunRecord(
        experiment_name=experiment_name,
        scoring_run_id=scoring_run_id,
        run_unit=scenario_record.run_unit,
        scenario_schema_version=scenario_record.scenario_schema_version,
        extraction=extraction_result.parsed,
        matching=matching_result.parsed,
        contradiction_check=contradiction_result.parsed,
        disclaimer_washing_check=disclaimer_washing_check,
        direct_disclosure_assessment=direct_disclosure_assessment,
        response_metrics=response_metrics,
        user_harm_metrics=user_harm_metrics,
        call_ids=call_ids,
        usage_summary=usage_summary,
    )


def load_scenario_run_records(experiment_dir: Path) -> List[ScenarioRunRecord]:
    """Load all scenario-run records from an experiment directory."""
    records: List[ScenarioRunRecord] = []
    for path in result_paths(
        experiment_dir=experiment_dir, pattern="????????T??????_results.jsonl"
    ):
        records.extend(read_jsonl_models(path=path, model=ScenarioRunRecord))
    return records


def existing_scored_run_unit_ids(experiment_dir: Path) -> List[str]:
    """Return run-unit ids already present in scoring result files."""
    ids: List[str] = []
    for path in result_paths(experiment_dir=experiment_dir, pattern="*_scoring_results.jsonl"):
        for record in read_jsonl_models(path=path, model=ScoredRunRecord):
            ids.append(record.run_unit.run_unit_id)
    return ids


def write_usage_summary(path: Path, summary: ExperimentUsageSummary) -> None:
    """Persist a stage-level usage summary as JSON."""
    path.write_text(summary.model_dump_json(indent=2), encoding="utf-8")


def build_scoring_specs(
    scenario_records: Sequence[ScenarioRunRecord],
    scenario_index: Dict[
        Tuple[str, str],
        Tuple[ScenarioFamilyArtifact, ScenarioInstanceArtifact],
    ],
    skip_ids: Iterable[str],
    run_unit_ids: Optional[Sequence[str]] = None,
    limit: Optional[int] = None,
) -> List[Tuple[ScenarioRunRecord, ScenarioInstanceArtifact]]:
    """Select scenario-run records for scoring after filters, resume skips, and limit."""
    filtered_records = filter_scenario_run_records(
        scenario_records=scenario_records,
        skip_ids=skip_ids,
        run_unit_ids=run_unit_ids,
        limit=limit,
    )
    selected_specs: List[Tuple[ScenarioRunRecord, ScenarioInstanceArtifact]] = []
    for scenario_record in filtered_records:
        unit_id = scenario_record.run_unit.run_unit_id
        key = (
            scenario_record.run_unit.scenario_family_id,
            scenario_record.run_unit.scenario_id,
        )
        if key not in scenario_index:
            raise ValueError(f"scenario artifact missing for run unit {unit_id}")
        family, instance = scenario_index[key]
        expected_family_sha256 = artifact_sha256(family)
        if (
            scenario_record.run_unit.scenario_family_sha256 is not None
            and scenario_record.run_unit.scenario_family_sha256 != expected_family_sha256
        ):
            raise ValueError(
                f"scenario artifact hash mismatch for run unit {unit_id}; "
                "use the exact reviewed family that produced the transcript"
            )
        selected_specs.append((scenario_record, instance))
    return selected_specs


def filter_scenario_run_records(
    scenario_records: Sequence[ScenarioRunRecord],
    skip_ids: Iterable[str],
    run_unit_ids: Optional[Sequence[str]] = None,
    limit: Optional[int] = None,
) -> List[ScenarioRunRecord]:
    """Apply run-unit, resume, and limit filters before loading scenario artifacts."""
    allowed_run_unit_ids = set(run_unit_ids) if run_unit_ids else None
    skipped_unit_ids = set(skip_ids)
    selected_records: List[ScenarioRunRecord] = []
    for scenario_record in scenario_records:
        unit_id = scenario_record.run_unit.run_unit_id
        if allowed_run_unit_ids is not None and unit_id not in allowed_run_unit_ids:
            continue
        if unit_id in skipped_unit_ids:
            logger.info("Skipping previously scored run unit {}", unit_id)
            continue
        if limit is not None and len(selected_records) >= limit:
            break
        selected_records.append(scenario_record)
    return selected_records


def score_selected_spec(
    client: OpenRouterStructuredClient,
    experiment_config: ExperimentConfig,
    scoring_run_id: str,
    spec: Tuple[ScenarioRunRecord, ScenarioInstanceArtifact],
) -> ScoredRunRecord:
    """Score one selected scenario-run record."""
    scenario_record, instance = spec
    logger.info("Scoring run unit {}", scenario_record.run_unit.run_unit_id)
    return score_one_run(
        client=client,
        experiment_name=experiment_config.experiment_name,
        scoring_run_id=scoring_run_id,
        scenario_record=scenario_record,
        instance=instance,
        scoring_model=experiment_config.scoring_model,
        generation_config=experiment_config.generation_config,
    )


def score_specs_concurrently(
    client: OpenRouterStructuredClient,
    experiment_config: ExperimentConfig,
    scoring_run_id: str,
    specs: Sequence[Tuple[ScenarioRunRecord, ScenarioInstanceArtifact]],
    collect_record: Callable[[ScoredRunRecord], None],
) -> None:
    """Score selected records with a bounded worker pool."""
    worker_count = min(experiment_config.scoring_concurrency, len(specs))
    if worker_count < 1:
        return
    logger.info("Scoring {} run unit(s) with {} worker(s)", len(specs), worker_count)
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures: Dict[Future[ScoredRunRecord], str] = {
            executor.submit(
                score_selected_spec,
                client,
                experiment_config,
                scoring_run_id,
                spec,
            ): spec[0].run_unit.run_unit_id
            for spec in specs
        }
        for future in as_completed(futures):
            unit_id = futures[future]
            collect_record(future.result())
            logger.info("Completed scoring run unit {}", unit_id)


def score_scenario_runs(
    client: OpenRouterStructuredClient,
    experiment_root: Path,
    experiment_config: ExperimentConfig,
    run_unit_ids: Optional[Sequence[str]] = None,
    scoring_run_id: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[ScoredRunRecord]:
    """Score selected scenario-run records and persist scoring outputs."""
    experiment_dir = prepare_experiment_dir(
        experiment_root=experiment_root,
        experiment_name=experiment_config.experiment_name,
    )
    write_experiment_config(experiment_dir=experiment_dir, config=experiment_config)
    scenario_records = load_scenario_run_records(experiment_dir)
    if not scenario_records:
        raise ValueError(f"no scenario-run records found under {experiment_dir / 'results'}")
    skip_ids = (
        set(existing_scored_run_unit_ids(experiment_dir)) if experiment_config.resume else set()
    )
    filtered_records = filter_scenario_run_records(
        scenario_records=scenario_records,
        skip_ids=skip_ids,
        run_unit_ids=run_unit_ids,
        limit=limit,
    )
    selected_family_ids = sorted(
        {record.run_unit.scenario_family_id for record in filtered_records}
    )
    scenario_index = (
        index_scenario_instances(
            load_scenario_families(
                Path(experiment_config.scenario_run_dir),
                scenario_family_ids=selected_family_ids,
            )
        )
        if selected_family_ids
        else {}
    )
    run_id = scoring_run_id or create_timestamped_run_id()
    output_path = experiment_dir / "results" / f"{run_id}_scoring_results.jsonl"
    usage_path = experiment_dir / "results" / f"{run_id}_scoring_usage.json"
    produced_records: List[ScoredRunRecord] = []
    existing_output_records = (
        read_jsonl_models(path=output_path, model=ScoredRunRecord)
        if experiment_config.resume
        else []
    )
    stage_usage = (
        summarize_record_usage(existing_output_records)
        if experiment_config.resume
        else ExperimentUsageSummary()
    )
    specs = build_scoring_specs(
        scenario_records=filtered_records,
        scenario_index=scenario_index,
        skip_ids=[],
    )

    def collect_record(record: ScoredRunRecord) -> None:
        """Store one completed scoring record in output artifacts and in-memory run state."""
        append_jsonl(path=output_path, records=[record])
        add_record_usage(summary=stage_usage, records=[record])
        produced_records.append(record)

    if experiment_config.scoring_concurrency > 1:
        score_specs_concurrently(
            client=client,
            experiment_config=experiment_config,
            scoring_run_id=run_id,
            specs=specs,
            collect_record=collect_record,
        )
    else:
        for spec in specs:
            collect_record(
                score_selected_spec(
                    client=client,
                    experiment_config=experiment_config,
                    scoring_run_id=run_id,
                    spec=spec,
                )
            )

    write_usage_summary(path=usage_path, summary=stage_usage)
    logger.success(
        "Wrote {} scored run record(s) to {}",
        len(produced_records),
        output_path,
    )
    logger.info("Scoring usage summary: {}", json.dumps(stage_usage.model_dump()))
    return produced_records
