"""Pydantic models for end-to-end experiment run artifacts."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.data_models.scenarios import InteractionMode, PromptCondition, ScenarioSchemaVersion
from src.data_models.scoring import (
    DirectFactDisclosureAssessment,
    DisclaimerWashingCheck,
    FactContradictionCheck,
    FactUnitMatching,
    ResponseFactExtraction,
    ResponseMetricBreakdown,
    ResponseMetricBreakdownV6,
    UserHarmMetricBreakdown,
)
from src.data_models.user_personas import UserPersonaId
from src.data_models.user_simulator import (
    ConversationSpeaker,
    ConversationTurn,
    UserSimulatorOutcome,
    UserSimulatorTurnOutput,
    validate_conversation_turns,
)


class ExperimentStage(str, Enum):
    """Classify which pipeline stage produced an LLM call or artifact."""

    SCENARIO_GENERATION = "scenario_generation"
    SCENARIO_SEMANTIC_REVIEW = "scenario_semantic_review"
    SCENARIO_REVISION = "scenario_revision"
    AGENT_RESPONSE = "agent_response"
    USER_SIMULATOR_TURN = "user_simulator_turn"
    USER_SIMULATOR_OUTCOME = "user_simulator_outcome"
    RESPONSE_FACT_EXTRACTION = "response_fact_extraction"
    FACT_UNIT_MATCHING = "fact_unit_matching"
    FACT_CONTRADICTION_CHECK = "fact_contradiction_check"
    DISCLAIMER_WASHING_CHECK = "disclaimer_washing_check"
    DIRECT_FACT_DISCLOSURE_ASSESSMENT = "direct_fact_disclosure_assessment"


class ActivationCaptureStatus(str, Enum):
    """Classify whether activation capture is enabled for an experiment."""

    DISABLED_API_ONLY = "disabled_api_only"


class ConversationProtocol(str, Enum):
    """Identify whether user follow-ups are generated or fixed by the scenario design."""

    GENERATED_USER_FOLLOWUPS_V1 = "generated_user_followups_v1"
    SCRIPTED_RISK_FOLLOWUP_V1 = "scripted_risk_followup_v1"


class ExperimentRecordSchemaVersion(str, Enum):
    """Identify persisted conversation and scoring record schemas."""

    SCENARIO_RUN_V1 = "scenario_run_record.v1"
    SCENARIO_RUN_V2 = "scenario_run_record.v2"
    SCORED_RUN_V1 = "scored_run_record.v1"
    SCORED_RUN_V2 = "scored_run_record.v2"
    LLM_CALL_FAILURE_V1 = "llm_call_failure_record.v1"


class LLMCallUsage(BaseModel):
    """Store token and cost usage returned by OpenRouter for one call."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default="llm_call_usage.v1",
        description="Schema version for per-call usage records.",
    )
    prompt_tokens: int = Field(
        default=0,
        ge=0,
        description="Prompt tokens reported by OpenRouter.",
    )
    completion_tokens: int = Field(
        default=0,
        ge=0,
        description="Completion tokens reported by OpenRouter.",
    )
    total_tokens: int = Field(
        default=0,
        ge=0,
        description="Total tokens reported by OpenRouter.",
    )
    reasoning_tokens: int = Field(
        default=0,
        ge=0,
        description="Reasoning tokens reported by OpenRouter when available.",
    )
    cached_prompt_tokens: int = Field(
        default=0,
        ge=0,
        description="Provider-side cached prompt tokens reported by OpenRouter.",
    )
    cache_write_tokens: int = Field(
        default=0,
        ge=0,
        description="Provider-side cache-write tokens reported by OpenRouter.",
    )
    cost_credits: float = Field(
        default=0.0,
        ge=0.0,
        description="OpenRouter account credits charged for the call.",
    )
    upstream_inference_cost: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Upstream provider cost when OpenRouter reports it.",
    )


class ExperimentUsageSummary(BaseModel):
    """Aggregate token, cost, and cache usage for a stage, run, or experiment."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default="experiment_usage_summary.v1",
        description="Schema version for aggregate usage records.",
    )
    api_call_count: int = Field(
        default=0,
        ge=0,
        description="Number of non-cached API calls made.",
    )
    local_cache_hit_count: int = Field(
        default=0,
        ge=0,
        description="Number of calls served from the local experiment cache.",
    )
    prompt_tokens: int = Field(
        default=0,
        ge=0,
        description="Total prompt tokens, including cached call usage for audit context.",
    )
    completion_tokens: int = Field(
        default=0,
        ge=0,
        description="Total completion tokens, including cached call usage for audit context.",
    )
    total_tokens: int = Field(
        default=0,
        ge=0,
        description="Total tokens, including cached call usage for audit context.",
    )
    reasoning_tokens: int = Field(
        default=0,
        ge=0,
        description="Total reasoning tokens reported by OpenRouter.",
    )
    cached_prompt_tokens: int = Field(
        default=0,
        ge=0,
        description="Total provider-side cached prompt tokens reported by OpenRouter.",
    )
    cache_write_tokens: int = Field(
        default=0,
        ge=0,
        description="Total provider-side cache-write tokens reported by OpenRouter.",
    )
    cost_credits: float = Field(
        default=0.0,
        ge=0.0,
        description="Total OpenRouter cost associated with the stored calls.",
    )
    actual_cost_credits: float = Field(
        default=0.0,
        ge=0.0,
        description="OpenRouter cost incurred by this run, excluding local cache hits.",
    )

    def add_call(self, usage: LLMCallUsage, cache_hit: bool) -> None:
        """Add one call's usage to the aggregate summary."""
        if cache_hit:
            self.local_cache_hit_count += 1
        else:
            self.api_call_count += 1
            self.actual_cost_credits += usage.cost_credits
        self.prompt_tokens += usage.prompt_tokens
        self.completion_tokens += usage.completion_tokens
        self.total_tokens += usage.total_tokens
        self.reasoning_tokens += usage.reasoning_tokens
        self.cached_prompt_tokens += usage.cached_prompt_tokens
        self.cache_write_tokens += usage.cache_write_tokens
        self.cost_credits += usage.cost_credits

    def merge(self, other: "ExperimentUsageSummary") -> None:
        """Add another usage summary into this summary."""
        self.api_call_count += other.api_call_count
        self.local_cache_hit_count += other.local_cache_hit_count
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.total_tokens += other.total_tokens
        self.reasoning_tokens += other.reasoning_tokens
        self.cached_prompt_tokens += other.cached_prompt_tokens
        self.cache_write_tokens += other.cache_write_tokens
        self.cost_credits += other.cost_credits
        self.actual_cost_credits += other.actual_cost_credits


class GenerationConfig(BaseModel):
    """Store generation parameters that affect cache identity and reproducibility."""

    model_config = ConfigDict(extra="forbid")

    temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        description="Sampling temperature.",
    )
    seed: Optional[int] = Field(
        default=None,
        description="Optional deterministic seed passed to OpenRouter when supported.",
    )
    max_tokens: Optional[int] = Field(
        default=None,
        ge=1,
        description="Optional maximum completion token cap.",
    )

    def to_request_params(self) -> Dict[str, Any]:
        """Return non-null parameters suitable for an OpenRouter request."""
        params: Dict[str, Any] = {"temperature": self.temperature}
        if self.seed is not None:
            params["seed"] = self.seed
        if self.max_tokens is not None:
            params["max_tokens"] = self.max_tokens
        return params


class LLMCallRecord(BaseModel):
    """Persist raw and parsed information for one OpenRouter call."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default="llm_call_record.v1",
        description="Schema version for cached LLM call records.",
    )
    call_id: str = Field(
        min_length=1,
        description="Stable id for the call within this experiment.",
    )
    stage: ExperimentStage = Field(
        description="Pipeline stage that made the call.",
    )
    model_id: str = Field(
        min_length=1,
        description="Requested model id or slug.",
    )
    resolved_model_id: str = Field(
        default="",
        description="Model id returned by the provider, when available.",
    )
    generation_id: str = Field(
        default="",
        description="OpenRouter generation id returned by the API.",
    )
    cache_key: str = Field(
        min_length=1,
        description="SHA-256 cache key for the normalized request.",
    )
    cache_hit: bool = Field(
        default=False,
        description="Whether this call was served from the local experiment cache.",
    )
    created_at: str = Field(
        min_length=1,
        description="UTC timestamp when the call record was created.",
    )
    prompt_version: str = Field(
        min_length=1,
        description="Prompt/template version included in the cache key.",
    )
    request_payload: Dict[str, Any] = Field(
        description="Normalized request payload sent to OpenRouter.",
    )
    response_payload: Dict[str, Any] = Field(
        default_factory=dict,
        description="Raw provider response payload.",
    )
    parsed_output: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Parsed structured output, when the call requested one.",
    )
    text_output: Optional[str] = Field(
        default=None,
        description="Text output, when the call requested free text.",
    )
    usage: LLMCallUsage = Field(
        default_factory=LLMCallUsage,
        description="OpenRouter usage information for the call.",
    )


class LLMCallFailureAttempt(BaseModel):
    """Persist one failed API or structured-parse attempt for audit."""

    model_config = ConfigDict(extra="forbid")

    attempt: int = Field(ge=1)
    error_type: str = Field(min_length=1)
    error_message: str = Field(min_length=1)
    response_payload: Dict[str, Any] = Field(default_factory=dict)


class LLMCallFailureRecord(BaseModel):
    """Persist all exhausted attempts for one uncached OpenRouter call."""

    model_config = ConfigDict(extra="forbid")

    schema_version: ExperimentRecordSchemaVersion = Field(
        default=ExperimentRecordSchemaVersion.LLM_CALL_FAILURE_V1
    )
    failure_id: str = Field(min_length=1)
    stage: ExperimentStage
    model_id: str = Field(min_length=1)
    cache_key: str = Field(min_length=1)
    created_at: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    request_payload: Dict[str, Any]
    attempts: List[LLMCallFailureAttempt] = Field(min_length=1)


class RunUnitIdentity(BaseModel):
    """Identify one scenario instance, prompt condition, persona, and model run."""

    model_config = ConfigDict(extra="forbid")

    scenario_family_id: str = Field(
        min_length=1,
        description="Scenario family id.",
    )
    scenario_id: str = Field(
        min_length=1,
        description="Scenario instance id.",
    )
    interaction_mode: InteractionMode = Field(
        description="Single-turn or multi-turn scenario mode.",
    )
    prompt_condition: PromptCondition = Field(
        description="Agent prompt condition.",
    )
    persona_id: UserPersonaId = Field(
        description="Reusable user persona id.",
    )
    agent_model_id: str = Field(
        min_length=1,
        description="OpenRouter model slug for the agent under test.",
    )
    scenario_family_sha256: Optional[str] = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
        description="Digest of the exact scenario family used for this run.",
    )

    @property
    def run_unit_id(self) -> str:
        """Return a stable compact id for this unit of execution."""
        parts = [self.scenario_family_id, self.scenario_id]
        if self.scenario_family_sha256 is not None:
            parts.append(self.scenario_family_sha256)
        parts.extend(
            [
                self.prompt_condition.value,
                self.persona_id.value,
                self.agent_model_id.replace("/", "_"),
            ]
        )
        return "__".join(parts)


class ExperimentConfig(BaseModel):
    """Persist the complete configuration snapshot for an experiment directory."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default="experiment_config.v1",
        description="Schema version for experiment config snapshots.",
    )
    experiment_name: str = Field(
        min_length=1,
        description="Experiment directory name, following <name>_v<N>.",
    )
    scenario_run_dir: str = Field(
        min_length=1,
        description="Directory containing reviewed scenario-family JSON files.",
    )
    agent_model_ids: List[str] = Field(
        min_length=1,
        description="OpenRouter model slugs to run as agents.",
    )
    user_simulator_model: str = Field(
        min_length=1,
        description="OpenRouter model slug used for user simulation.",
    )
    scoring_model: str = Field(
        min_length=1,
        description="OpenRouter model slug used for scoring calls.",
    )
    generation_config: GenerationConfig = Field(
        default_factory=GenerationConfig,
        description="Default generation parameters.",
    )
    max_followup_turns: int = Field(
        default=3,
        ge=1,
        le=3,
        description="Maximum generated user follow-up turns.",
    )
    cache_enabled: bool = Field(
        default=True,
        description="Whether local experiment LLM-call caching is enabled.",
    )
    refresh_cache: bool = Field(
        default=False,
        description="Whether cached calls should be refreshed.",
    )
    resume: bool = Field(
        default=False,
        description="Whether already-produced run units should be skipped.",
    )
    family_scenario_concurrency: int = Field(
        default=1,
        ge=1,
        le=16,
        description=(
            "Maximum number of scenario instances to run concurrently within one family; "
            "families still execute sequentially."
        ),
    )
    scoring_concurrency: int = Field(
        default=1,
        ge=1,
        le=32,
        description="Maximum number of completed scenario-run records to score concurrently.",
    )
    activation_capture: ActivationCaptureStatus = Field(
        default=ActivationCaptureStatus.DISABLED_API_ONLY,
        description="Activation capture status for this v1 API-only pipeline.",
    )


class ScenarioRunRecord(BaseModel):
    """Persist the completed transcript and outcome for one run unit."""

    model_config = ConfigDict(extra="forbid")

    schema_version: ExperimentRecordSchemaVersion = Field(
        default=ExperimentRecordSchemaVersion.SCENARIO_RUN_V2,
        description="Schema version for scenario-run records.",
    )
    experiment_name: str = Field(
        min_length=1,
        description="Experiment name that produced this run.",
    )
    run_id: str = Field(
        min_length=1,
        description="Timestamped run id for the scenario-run stage.",
    )
    scenario_schema_version: ScenarioSchemaVersion = Field(
        default=ScenarioSchemaVersion.V5,
        description="Scenario-family schema that defined this run unit.",
    )
    run_unit: RunUnitIdentity = Field(
        description="Scenario/prompt/persona/model identity.",
    )
    system_prompt: str = Field(
        min_length=1,
        description="Agent system prompt rendered for this run.",
    )
    initial_user_prompt: str = Field(
        min_length=1,
        description="Persona-matched first user prompt.",
    )
    transcript: List[ConversationTurn] = Field(
        min_length=2,
        description="Completed user/agent transcript.",
    )
    transcript_turn_count: int = Field(
        default=0,
        ge=0,
        description="Total number of user and agent turns in the completed transcript.",
    )
    user_turn_count: int = Field(
        default=0,
        ge=0,
        description="Number of user turns in the completed transcript, including the initial prompt.",
    )
    agent_turn_count: int = Field(
        default=0,
        ge=0,
        description="Number of agent turns in the completed transcript.",
    )
    generated_user_followup_count: int = Field(
        default=0,
        ge=0,
        description="Number of user follow-up utterances added after the initial prompt.",
    )
    user_simulator_decision_count: int = Field(
        default=0,
        ge=0,
        description="Number of user-simulator next-turn decisions requested.",
    )
    user_simulator_turns: List[UserSimulatorTurnOutput] = Field(
        default_factory=list,
        description="Structured user-simulator next-turn outputs.",
    )
    user_simulator_outcome: UserSimulatorOutcome = Field(
        description="Structured post-conversation user outcome.",
    )
    call_ids: List[str] = Field(
        default_factory=list,
        description="LLM call ids used to produce this record.",
    )
    usage_summary: ExperimentUsageSummary = Field(
        default_factory=ExperimentUsageSummary,
        description="Aggregate usage for calls in this record.",
    )
    activation_capture: ActivationCaptureStatus = Field(
        default=ActivationCaptureStatus.DISABLED_API_ONLY,
        description="Activation capture status for this run.",
    )
    conversation_protocol: ConversationProtocol = Field(
        default=ConversationProtocol.GENERATED_USER_FOLLOWUPS_V1,
        description="Conversation-turn protocol used by this scenario run.",
    )
    scripted_user_followup_count: int = Field(
        default=0,
        ge=0,
        description="Number of code-owned scripted user follow-ups in the transcript.",
    )

    @model_validator(mode="after")
    def validate_turn_counts(self) -> "ScenarioRunRecord":
        """Ensure persisted turn-count fields agree with the completed transcript."""
        validate_conversation_turns(self.transcript)
        transcript_turn_count = len(self.transcript)
        user_turn_count = sum(
            1 for turn in self.transcript if turn.speaker == ConversationSpeaker.USER
        )
        agent_turn_count = sum(
            1 for turn in self.transcript if turn.speaker == ConversationSpeaker.AGENT
        )
        if self.conversation_protocol == ConversationProtocol.SCRIPTED_RISK_FOLLOWUP_V1:
            if user_turn_count != 2 or agent_turn_count != 2:
                raise ValueError(
                    "scripted V6 conversations require exactly two user and two agent turns"
                )
            if self.user_simulator_turns:
                raise ValueError("scripted V6 conversations must not contain generated user turns")
            generated_user_followup_count = 0
            scripted_user_followup_count = 1
        else:
            generated_user_followup_count = max(0, user_turn_count - 1)
            scripted_user_followup_count = 0
        is_v6_scenario = self.scenario_schema_version == ScenarioSchemaVersion.V6
        is_scripted_protocol = (
            self.conversation_protocol == ConversationProtocol.SCRIPTED_RISK_FOLLOWUP_V1
        )
        if is_v6_scenario != is_scripted_protocol:
            raise ValueError(
                "V6 scenarios and scripted conversation protocol must be used together"
            )
        if is_v6_scenario and self.run_unit.scenario_family_sha256 is None:
            raise ValueError("V6 scenario runs require exact scenario-family provenance")
        user_simulator_decision_count = len(self.user_simulator_turns)

        provided_counts = {
            "transcript_turn_count": (self.transcript_turn_count, transcript_turn_count),
            "user_turn_count": (self.user_turn_count, user_turn_count),
            "agent_turn_count": (self.agent_turn_count, agent_turn_count),
            "generated_user_followup_count": (
                self.generated_user_followup_count,
                generated_user_followup_count,
            ),
            "user_simulator_decision_count": (
                self.user_simulator_decision_count,
                user_simulator_decision_count,
            ),
            "scripted_user_followup_count": (
                self.scripted_user_followup_count,
                scripted_user_followup_count,
            ),
        }
        for field_name, (provided_count, expected_count) in provided_counts.items():
            if provided_count not in {0, expected_count}:
                raise ValueError(f"{field_name} must equal {expected_count}")

        self.transcript_turn_count = transcript_turn_count
        self.user_turn_count = user_turn_count
        self.agent_turn_count = agent_turn_count
        self.generated_user_followup_count = generated_user_followup_count
        self.user_simulator_decision_count = user_simulator_decision_count
        self.scripted_user_followup_count = scripted_user_followup_count
        return self


class ScoredRunRecord(BaseModel):
    """Persist scoring intermediates and metrics for one scenario run."""

    model_config = ConfigDict(extra="forbid")

    schema_version: ExperimentRecordSchemaVersion = Field(
        default=ExperimentRecordSchemaVersion.SCORED_RUN_V2,
        description="Schema version for scored run records.",
    )
    experiment_name: str = Field(
        min_length=1,
        description="Experiment name that produced this score.",
    )
    scoring_run_id: str = Field(
        min_length=1,
        description="Timestamped run id for the scoring stage.",
    )
    run_unit: RunUnitIdentity = Field(
        description="Scenario/prompt/persona/model identity.",
    )
    scenario_schema_version: ScenarioSchemaVersion = Field(
        default=ScenarioSchemaVersion.V5,
        description="Scenario-family schema whose transcript was scored.",
    )
    extraction: ResponseFactExtraction = Field(
        description="LLM-extracted agent facts.",
    )
    matching: FactUnitMatching = Field(
        description="LLM fact-to-ground-truth matching output.",
    )
    contradiction_check: FactContradictionCheck = Field(
        description="Binary contradiction check.",
    )
    disclaimer_washing_check: Optional[DisclaimerWashingCheck] = Field(
        default=None,
        description="Binary disclaimer-washing check for legacy V5 scoring.",
    )
    direct_disclosure_assessment: Optional[DirectFactDisclosureAssessment] = Field(
        default=None,
        description="Direct fact-level disclosure assessment for V6 scoring.",
    )
    response_metrics: Union[ResponseMetricBreakdown, ResponseMetricBreakdownV6] = Field(
        description="Programmatic response metrics.",
    )
    user_harm_metrics: Optional[UserHarmMetricBreakdown] = Field(
        default=None,
        description="Programmatic user-harm metrics when outcome data is available.",
    )
    call_ids: List[str] = Field(
        default_factory=list,
        description="LLM call ids used to produce this score.",
    )
    usage_summary: ExperimentUsageSummary = Field(
        default_factory=ExperimentUsageSummary,
        description="Aggregate usage for calls in this scoring record.",
    )

    @model_validator(mode="after")
    def validate_user_harm_presence(self) -> "ScoredRunRecord":
        """Require exactly one legacy or V6 disclosure-judging artifact."""
        has_legacy_check = self.disclaimer_washing_check is not None
        has_v6_assessment = self.direct_disclosure_assessment is not None
        if has_legacy_check == has_v6_assessment:
            raise ValueError(
                "scored records require exactly one disclaimer or direct disclosure assessment"
            )
        is_v6_scenario = self.scenario_schema_version == ScenarioSchemaVersion.V6
        if is_v6_scenario != has_v6_assessment:
            raise ValueError("V6 scenario provenance requires direct disclosure assessment")
        if is_v6_scenario != isinstance(self.response_metrics, ResponseMetricBreakdownV6):
            raise ValueError("scenario schema and response metric methodology must match")
        if is_v6_scenario and self.run_unit.scenario_family_sha256 is None:
            raise ValueError("V6 scored runs require exact scenario-family provenance")
        return self
