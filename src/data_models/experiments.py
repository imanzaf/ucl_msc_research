"""Strict run-unit, transcript, retry, usage, and model-summary boundaries."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional

from pydantic import Field, field_validator, model_validator

from src.data_models.common import ImmutableModel, StrictModel, VersionedImmutableModel, artifact_sha256, sha256_bytes, validate_sha256
from src.data_models.study import AMPLE_WORD_LIMIT, EXPERIMENT_DIMENSIONS, ExperimentCell, ExperimentName
from src.scenarios.word_count import count_words

PRIMARY_DIMENSIONS = EXPERIMENT_DIMENSIONS[ExperimentName.RISK_COMM_V1]
EVALUATION_SCENARIO_COUNT = PRIMARY_DIMENSIONS.scenario_count
EVALUATED_MODEL_COUNT = PRIMARY_DIMENSIONS.evaluated_model_count
CELL_COUNT = PRIMARY_DIMENSIONS.cell_count
EXPECTED_CONVERSATION_COUNT = PRIMARY_DIMENSIONS.conversation_count
EXPECTED_AGENT_RESPONSE_COUNT = PRIMARY_DIMENSIONS.response_count


def provider_request_sha256(messages: List[Dict[str, str]], model_id: str, temperature: float, max_tokens: int, seed: int) -> str:
    """Hash every exact field sent for one text completion request."""
    return artifact_sha256(
        {
            "model": model_id,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "seed": seed,
        }
    )


class MessageRole(str, Enum):
    """Identify a persisted transcript message role."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class RunOutcomeStatus(str, Enum):
    """Identify the terminal state of one immutable run unit."""

    COMPLETED = "completed"
    FAILED = "failed"
    MISSING = "missing"


class FailureReason(str, Enum):
    """Classify run failures without deleting their assigned unit."""

    PROVIDER_ERROR = "provider_error"
    TIMEOUT = "timeout"
    INVALID_RESPONSE = "invalid_response"
    RETRIES_EXHAUSTED = "retries_exhausted"


class CompletionFinishReason(str, Enum):
    """Normalise provider completion termination without discarding unknown values."""

    STOP = "stop"
    LENGTH = "length"
    CONTENT_FILTER = "content_filter"
    TOOL_CALLS = "tool_calls"
    UNKNOWN = "unknown"


class RetryPolicy(ImmutableModel):
    """Freeze retry count and backoff while prohibiting prompt mutation."""

    max_retries: int = Field(ge=0)
    backoff_seconds: List[float]
    reuse_identical_prompt_bytes: bool = Field(default=True)

    @model_validator(mode="after")
    def validate_backoff(self) -> "RetryPolicy":
        """Require one nonnegative delay per retry and immutable prompt bytes."""
        if len(self.backoff_seconds) != self.max_retries:
            raise ValueError("retry backoff length must equal max_retries")
        if any(delay < 0 for delay in self.backoff_seconds):
            raise ValueError("retry delays cannot be negative")
        if not self.reuse_identical_prompt_bytes:
            raise ValueError("retries must reuse identical prompt bytes")
        return self


class ExperimentConfig(VersionedImmutableModel):
    """Snapshot the risk_comm_v1 execution contract before a run starts."""

    schema_version: str = Field(pattern=r"^2\.0\.0$")
    experiment_name: ExperimentName
    experiment_manifest_sha256: str
    scenario_count: int = Field(default=EVALUATION_SCENARIO_COUNT)
    evaluated_model_count: int = Field(default=EVALUATED_MODEL_COUNT)
    cell_count: int = Field(default=CELL_COUNT)
    expected_conversation_count: int = Field(default=EXPECTED_CONVERSATION_COUNT)
    expected_agent_response_count: int = Field(default=EXPECTED_AGENT_RESPONSE_COUNT)
    temperature: float = Field(default=0.0, ge=0.0, le=0.0)
    randomisation_seed: int
    retry_policy: RetryPolicy
    created_at: datetime

    @field_validator("experiment_manifest_sha256")
    @classmethod
    def validate_manifest_hash(cls, value: str) -> str:
        """Validate the experiment-manifest digest."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_target_counts(self) -> "ExperimentConfig":
        """Refuse any config whose dimensions differ from its frozen design."""
        expected_conversations = self.scenario_count * self.evaluated_model_count * self.cell_count
        frozen_count = EXPERIMENT_DIMENSIONS[self.experiment_name].conversation_count
        if expected_conversations != self.expected_conversation_count or expected_conversations != frozen_count:
            raise ValueError(f"{self.experiment_name.value} must contain exactly {frozen_count} conversations")
        if self.expected_agent_response_count != expected_conversations * 2:
            raise ValueError("expected response count must be two per conversation")
        return self


class CalibrationExperimentConfig(VersionedImmutableModel):
    """Snapshot the 120-conversation canonical-order calibration matrix."""

    schema_version: str = Field(pattern=r"^2\.0\.0$")
    experiment_name: str = Field(pattern=r"^risk_comm_calibration_v1$")
    experiment_manifest_sha256: str
    scenario_count: int = Field(default=10, ge=10, le=10)
    evaluated_model_count: int = Field(default=3, ge=3, le=3)
    cell_count: int = Field(default=4, ge=4, le=4)
    expected_conversation_count: int = Field(default=120, ge=120, le=120)
    expected_agent_response_count: int = Field(default=240, ge=240, le=240)
    temperature: float = Field(default=0.0, ge=0.0, le=0.0)
    randomisation_seed: int
    retry_policy: RetryPolicy
    created_at: datetime

    @field_validator("experiment_manifest_sha256")
    @classmethod
    def validate_manifest_hash(cls, value: str) -> str:
        """Validate the frozen experiment-manifest digest."""
        return validate_sha256(value)


class PromptMessage(ImmutableModel):
    """Store one exact message in a provider request."""

    role: MessageRole
    content: str = Field(min_length=1)


class RunUnit(VersionedImmutableModel):
    """Represent one randomised immutable scenario–model–cell assignment."""

    schema_version: str = Field(pattern=r"^3\.0\.0$")
    run_unit_id: str = Field(pattern=r"^RUN_[A-F0-9]{16}$")
    block_id: str = Field(pattern=r"^BLOCK_[A-F0-9]{16}$")
    scenario_id: str = Field(pattern=r"^CF\d{3}_(C1|R[12])$")
    use_case_id: str = Field(pattern=r"^CF\d{3}$")
    model_id: str = Field(min_length=1)
    expected_model_version: str = Field(min_length=1)
    model_snapshot_sha256: str
    cell: ExperimentCell
    assigned_word_limit: Optional[int] = Field(default=None, ge=80, le=240)
    global_randomisation_seed: int
    block_randomisation_seed: int
    randomised_position: int = Field(ge=0, le=3)
    visible_facts_sha256: str
    initial_request_messages: List[PromptMessage] = Field(min_length=2)
    initial_request_sha256: str
    follow_up_message: PromptMessage
    follow_up_sha256: str
    created_at: datetime

    @field_validator("model_snapshot_sha256", "visible_facts_sha256", "initial_request_sha256", "follow_up_sha256")
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        """Validate visible-fact and prompt digests."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_message_roles(self) -> "RunUnit":
        """Require aligned IDs, exact prompt hashes, and valid user-message roles."""
        if self.use_case_id != self.scenario_id.split("_")[0]:
            raise ValueError("run unit use_case_id must match scenario_id")
        if self.follow_up_message.role != MessageRole.USER:
            raise ValueError("follow-up message must have user role")
        if not any(message.role == MessageRole.USER for message in self.initial_request_messages):
            raise ValueError("initial request requires a user message")
        initial_bytes = b"\n".join(f"{message.role.value}\0{message.content}".encode("utf-8") for message in self.initial_request_messages)
        follow_up_bytes = f"{self.follow_up_message.role.value}\0{self.follow_up_message.content}".encode("utf-8")
        if self.initial_request_sha256 != sha256_bytes(initial_bytes) or self.follow_up_sha256 != sha256_bytes(follow_up_bytes):
            raise ValueError("run unit prompt hashes do not match exact message bytes")
        return self


class TokenUsage(ImmutableModel):
    """Store provider-reported token usage and billed cost for one response."""

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    cost_credits: Optional[Decimal] = Field(default=None, ge=0)
    upstream_inference_cost: Optional[Decimal] = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_total(self) -> "TokenUsage":
        """Require total tokens to equal input plus output when supplied."""
        if self.total_tokens != self.input_tokens + self.output_tokens:
            raise ValueError("total_tokens must equal input_tokens + output_tokens")
        return self


class ProviderCallProvenance(ImmutableModel):
    """Bind a structured model artifact to its exact provider request and returned snapshot."""

    requested_model_id: str = Field(min_length=1)
    returned_model_version: str = Field(min_length=1)
    provider_request_id: str = Field(min_length=1)
    finish_reason: CompletionFinishReason
    usage: TokenUsage
    request_sha256: str
    response_sha256: str
    response_repaired: bool = False

    @field_validator("request_sha256", "response_sha256")
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        """Validate exact structured request and response digests."""
        return validate_sha256(value)


class ProviderAttempt(ImmutableModel):
    """Record one provider attempt while proving prompt-byte immutability."""

    attempt_number: int = Field(ge=1)
    request_sha256: str
    started_at: datetime
    completed_at: datetime
    provider_request_id: Optional[str] = Field(default=None, min_length=1)
    returned_model_version: Optional[str] = Field(default=None, min_length=1)
    finish_reason: Optional[CompletionFinishReason] = None
    response_text: Optional[str] = None
    response_sha256: Optional[str] = None
    latency_ms: int = Field(ge=0)
    usage: Optional[TokenUsage] = None
    error_type: Optional[str] = Field(default=None, min_length=1)
    error_message: Optional[str] = Field(default=None, min_length=1)

    @field_validator("request_sha256", "response_sha256")
    @classmethod
    def validate_hashes(cls, value: Optional[str]) -> Optional[str]:
        """Validate request and optional response hashes."""
        return validate_sha256(value) if value is not None else value

    @model_validator(mode="after")
    def validate_attempt_outcome(self) -> "ProviderAttempt":
        """Require exactly a response or error for every provider attempt."""
        has_response = self.response_text is not None
        has_error = self.error_type is not None
        if has_response == has_error:
            raise ValueError("provider attempt must contain exactly one of response or error")
        if has_response and (
            self.response_sha256 is None
            or self.usage is None
            or self.returned_model_version is None
            or self.provider_request_id is None
            or self.finish_reason is None
        ):
            raise ValueError("successful attempts require request id, response hash, usage, finish reason, and returned model version")
        if has_response and self.response_sha256 != sha256_bytes((self.response_text or "").encode("utf-8")):
            raise ValueError("provider attempt response hash does not match response text")
        if self.completed_at < self.started_at:
            raise ValueError("provider attempt cannot complete before it starts")
        return self


class TranscriptTurn(ImmutableModel):
    """Store one exact ordered message in a completed conversation."""

    turn_index: int = Field(ge=0, le=3)
    role: MessageRole
    content: str = Field(min_length=1)
    content_sha256: str
    word_count: int = Field(ge=0)

    @field_validator("content_sha256")
    @classmethod
    def validate_content_hash(cls, value: str) -> str:
        """Validate the turn-content digest."""
        return validate_sha256(value)


class ConversationTranscript(VersionedImmutableModel):
    """Persist a terminal conversation result immediately after its run unit."""

    schema_version: str = Field(pattern=r"^2\.0\.0$")
    run_unit: RunUnit
    outcome_status: RunOutcomeStatus
    turns: List[TranscriptTurn]
    initial_attempts: List[ProviderAttempt]
    follow_up_attempts: List[ProviderAttempt]
    failure_reason: Optional[FailureReason] = None
    completed_at: datetime
    transcript_sha256: str

    @field_validator("transcript_sha256")
    @classmethod
    def validate_transcript_hash(cls, value: str) -> str:
        """Validate the transcript digest."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_transcript_shape(self) -> "ConversationTranscript":
        """Require four ordered turns for success and immutable request hashes across retries."""
        initial_request_hashes = {attempt.request_sha256 for attempt in self.initial_attempts}
        follow_up_request_hashes = {attempt.request_sha256 for attempt in self.follow_up_attempts}
        if len(initial_request_hashes) > 1:
            raise ValueError("initial retries must reuse identical request bytes")
        if len(follow_up_request_hashes) > 1:
            raise ValueError("follow-up retries must reuse identical request bytes")
        for attempts in [self.initial_attempts, self.follow_up_attempts]:
            if attempts and [attempt.attempt_number for attempt in attempts] != list(range(1, len(attempts) + 1)):
                raise ValueError("provider attempts must be sequential from one")
            if any(attempt.response_text is not None for attempt in attempts[:-1]):
                raise ValueError("only the terminal provider attempt may succeed")
        initial_messages = [{"role": message.role.value, "content": message.content} for message in self.run_unit.initial_request_messages]
        max_tokens = max(512, (self.run_unit.assigned_word_limit or AMPLE_WORD_LIMIT) * 4)
        expected_initial_request = provider_request_sha256(
            initial_messages,
            self.run_unit.model_id,
            0.0,
            max_tokens,
            self.run_unit.block_randomisation_seed,
        )
        if self.initial_attempts and initial_request_hashes != {expected_initial_request}:
            raise ValueError("initial provider attempts do not bind the frozen run-unit request")
        if self.outcome_status == RunOutcomeStatus.COMPLETED:
            if self.failure_reason is not None:
                raise ValueError("completed transcripts cannot have a failure reason")
            if [turn.turn_index for turn in self.turns] != [0, 1, 2, 3]:
                raise ValueError("completed conversations require exactly four ordered turns")
            if [turn.role for turn in self.turns] != [MessageRole.USER, MessageRole.ASSISTANT, MessageRole.USER, MessageRole.ASSISTANT]:
                raise ValueError("completed conversations require user/assistant/user/assistant roles")
            if not self.initial_attempts or not self.follow_up_attempts:
                raise ValueError("completed conversations require authenticated provider attempts for both responses")
            if self.initial_attempts[-1].response_text != self.turns[1].content or self.follow_up_attempts[-1].response_text != self.turns[3].content:
                raise ValueError("assistant transcript turns must equal terminal successful provider responses")
            initial_user_text = next(message.content for message in self.run_unit.initial_request_messages if message.role == MessageRole.USER)
            if self.turns[0].content != initial_user_text or self.turns[2].content != self.run_unit.follow_up_message.content:
                raise ValueError("user transcript turns must equal the frozen initial and follow-up prompts")
            follow_up_messages = [
                *initial_messages,
                {"role": MessageRole.ASSISTANT.value, "content": self.turns[1].content},
                {"role": self.run_unit.follow_up_message.role.value, "content": self.run_unit.follow_up_message.content},
            ]
            expected_follow_up_request = provider_request_sha256(
                follow_up_messages,
                self.run_unit.model_id,
                0.0,
                max_tokens,
                self.run_unit.block_randomisation_seed,
            )
            if follow_up_request_hashes != {expected_follow_up_request}:
                raise ValueError("follow-up provider attempts do not bind the frozen conversation request")
        elif self.failure_reason is None:
            raise ValueError("failed or missing transcripts require a failure reason")
        for turn in self.turns:
            if turn.content_sha256 != sha256_bytes(turn.content.encode("utf-8")) or turn.word_count != count_words(turn.content):
                raise ValueError("transcript turn hash/count does not match exact content")
        expected_hash = artifact_sha256(self.model_dump(mode="json", exclude={"transcript_sha256"}))
        if self.transcript_sha256 != expected_hash:
            raise ValueError("transcript_sha256 does not match canonical transcript content")
        return self


class RunProgress(StrictModel):
    """Track resumable counts without serving as an immutable research artifact."""

    completed_run_unit_ids: List[str]
    failed_run_unit_ids: List[str]
    updated_at: datetime


class ModelSummary(VersionedImmutableModel):
    """Summarise completed, missing, and usage counts for one evaluated model."""

    schema_version: str = Field(pattern=r"^2\.0\.0$")
    model_id: str = Field(min_length=1)
    expected_conversations: int = Field(gt=0)
    completed_conversations: int = Field(ge=0)
    failed_conversations: int = Field(ge=0)
    missing_conversations: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    returned_model_versions: Dict[str, int]
    summary_sha256: str

    @field_validator("summary_sha256")
    @classmethod
    def validate_summary_hash(cls, value: str) -> str:
        """Validate the model-summary digest."""
        return validate_sha256(value)

    @model_validator(mode="after")
    def validate_counts(self) -> "ModelSummary":
        """Require terminal counts and a digest matching the canonical summary content."""
        if self.completed_conversations + self.failed_conversations + self.missing_conversations != self.expected_conversations:
            raise ValueError("model terminal outcome counts must equal expected_conversations")
        expected_hash = artifact_sha256(self.model_dump(mode="json", exclude={"summary_sha256"}))
        if self.summary_sha256 != expected_hash:
            raise ValueError("model summary digest does not match canonical content")
        return self
