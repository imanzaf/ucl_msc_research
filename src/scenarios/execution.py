"""Approved, provider-pinned, resumable execution for one-shot fact generation."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import Dict, List, Literal, Optional, Protocol

from pydantic import Field, model_validator

from src.common import ImmutableModel, artifact_sha256, utc_now
from src.llm.openrouter import ProviderReply
from src.models.enums import LicenceCategory, ModelAccess
from src.models.experiments import GenerationControls, ProviderSnapshot
from src.models.manifests import ScenarioGenerationApproval
from src.paths import SCENARIO_ROOT, scenario_generation_paths
from src.scenarios.generation import GeneratedScenarioOutput, GenerationRequest, validate_generated_output_for_request
from src.storage import atomic_write_bytes, read_json, write_json, write_jsonl

WORKFLOW_NAME = "scenario_fact_generation_v1"
MODEL_SLUG = "openai/gpt-5.4"
PROVIDER_NAME = "OpenAI"
PROVIDER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
PRICE_SOURCE_URL = "https://openrouter.ai/openai/gpt-5.4"
INPUT_PRICE_PER_MILLION = Decimal("2.50")
OUTPUT_PRICE_PER_MILLION = Decimal("15.00")
OUTPUT_TOKENS_PER_REQUEST = 2048
PREFLIGHT_COST_ALLOWANCE = Decimal("0.01")


class CompletionClient(Protocol):
    """Describe the pinned completion operation needed by the generation runner."""

    def complete(self, model: ProviderSnapshot, controls: GenerationControls, messages: List[dict[str, str]]) -> ProviderReply:
        """Return one provider response for the supplied frozen request."""
        ...


class ScenarioGenerationEstimate(ImmutableModel):
    """Record the conservative token and list-price calculation for generation."""

    schema_version: str = Field(default="4.0.0", pattern=r"^4\.0\.0$")
    request_batch_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_count: int = Field(ge=1)
    model_slug: str
    provider_name: str
    input_token_estimate: int = Field(ge=1)
    output_token_ceiling_per_request: int = Field(ge=1)
    output_token_ceiling: int = Field(ge=1)
    input_price_per_million: Decimal = Field(gt=0)
    output_price_per_million: Decimal = Field(gt=0)
    preflight_cost_allowance: Decimal = Field(ge=0)
    estimated_max_cost: Decimal = Field(gt=0)
    currency: Literal["USD"] = "USD"
    price_source_url: str
    estimated_at: datetime


class ScenarioGenerationConfig(ImmutableModel):
    """Freeze the approved batch, route, controls, pricing, and run identity."""

    schema_version: str = Field(default="4.0.0", pattern=r"^4\.0\.0$")
    workflow: Literal["scenario_fact_generation_v1"] = "scenario_fact_generation_v1"
    run_id: str = Field(pattern=r"^[0-9]{8}T[0-9]{6}Z$")
    generation_request_batch_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_count: int = Field(ge=1)
    approval_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_model: ProviderSnapshot
    generation_controls: GenerationControls
    estimate: ScenarioGenerationEstimate
    created_at: datetime
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_config(self) -> "ScenarioGenerationConfig":
        """Bind the configuration hash and its repeated batch coordinates."""
        if self.generation_request_batch_sha256 != self.estimate.request_batch_sha256 or self.request_count != self.estimate.request_count:
            raise ValueError("scenario-generation config and estimate identify different request batches")
        expected_hash = artifact_sha256(self.model_dump(mode="json", exclude={"config_sha256"}))
        if self.config_sha256 != expected_hash:
            raise ValueError("scenario-generation config hash does not match canonical content")
        return self


class ScenarioGenerationPreflight(ImmutableModel):
    """Record the structured-output compatibility probe for the pinned route."""

    schema_version: str = Field(default="4.0.0", pattern=r"^4\.0\.0$")
    approval_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model: ProviderSnapshot
    provider_request_id: str
    raw_response: str
    returned_model_version: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    billed_cost: Optional[Decimal] = Field(default=None, ge=0)
    calculated_cost: Decimal = Field(ge=0)
    completed_at: datetime
    preflight_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_preflight(self) -> "ScenarioGenerationPreflight":
        """Require a passed snapshot and bind the preflight record hash."""
        if not self.model.preflight_passed:
            raise ValueError("scenario generation model did not pass structured-output preflight")
        expected_hash = artifact_sha256(self.model_dump(mode="json", exclude={"preflight_sha256"}))
        if self.preflight_sha256 != expected_hash:
            raise ValueError("scenario-generation preflight hash does not match canonical content")
        return self


class ScenarioGenerationRecord(ImmutableModel):
    """Retain one semantic generator response whether or not it validates."""

    schema_version: str = Field(default="4.0.0", pattern=r"^4\.0\.0$")
    request_id: str
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scenario_id: str
    model: ProviderSnapshot
    generation_controls: GenerationControls
    provider_request_id: str
    returned_model_version: str
    raw_response: str
    generated_output: Optional[GeneratedScenarioOutput] = None
    structurally_valid: bool
    validation_error: Optional[str] = None
    finish_reason: Optional[str] = None
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    billed_cost: Optional[Decimal] = Field(default=None, ge=0)
    calculated_cost: Decimal = Field(ge=0)
    received_at: datetime
    attempts: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_semantic_disposition(self) -> "ScenarioGenerationRecord":
        """Require every semantic response to have exactly one validation disposition."""
        if self.structurally_valid != (self.generated_output is not None):
            raise ValueError("structural-validity flag must agree with the parsed generated output")
        if self.structurally_valid and self.validation_error is not None:
            raise ValueError("valid generation records cannot contain a validation error")
        if not self.structurally_valid and not self.validation_error:
            raise ValueError("invalid generation records must retain their validation error")
        return self


class ScenarioGenerationSummary(ImmutableModel):
    """Summarize completed, valid, invalid, token, and cost outcomes."""

    schema_version: str = Field(default="4.0.0", pattern=r"^4\.0\.0$")
    workflow: Literal["scenario_fact_generation_v1"] = "scenario_fact_generation_v1"
    request_batch_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approval_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_count: int = Field(ge=1)
    semantic_response_count: int = Field(ge=0)
    valid_output_count: int = Field(ge=0)
    invalid_output_count: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    reported_cost_record_count: int = Field(ge=0)
    reported_billed_cost: Decimal = Field(ge=0)
    calculated_cost: Decimal = Field(ge=0)
    approved_max_cost: Decimal = Field(gt=0)
    generated_outputs_path: Path
    completed_at: datetime


def generation_request_batch_sha256(requests: List[GenerationRequest]) -> str:
    """Hash one ordered generation-request batch after validating corpus coverage."""
    if len(requests) != 30 or len({request.request_id for request in requests}) != 30:
        raise ValueError("scenario generation requires thirty unique request records")
    if len({request.scenario_id for request in requests}) != 30:
        raise ValueError("scenario generation requires thirty unique scenario identifiers")
    return artifact_sha256([request.model_dump(mode="json") for request in requests])


def build_generation_estimate(requests: List[GenerationRequest], estimated_at: Optional[datetime] = None) -> ScenarioGenerationEstimate:
    """Calculate a conservative current-list-price ceiling for the exact request batch."""
    compact_prompts = [
        request.system_prompt + json.dumps(request.seed_payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")) for request in requests
    ]
    input_tokens = (sum(len(prompt) for prompt in compact_prompts) + 2) // 3
    output_tokens = len(requests) * OUTPUT_TOKENS_PER_REQUEST
    token_cost = Decimal(input_tokens) * INPUT_PRICE_PER_MILLION / Decimal(1_000_000)
    token_cost += Decimal(output_tokens) * OUTPUT_PRICE_PER_MILLION / Decimal(1_000_000)
    estimated_cost = token_cost.quantize(Decimal("0.01"), rounding=ROUND_CEILING) + PREFLIGHT_COST_ALLOWANCE
    return ScenarioGenerationEstimate(
        request_batch_sha256=generation_request_batch_sha256(requests),
        request_count=len(requests),
        model_slug=MODEL_SLUG,
        provider_name=PROVIDER_NAME,
        input_token_estimate=input_tokens,
        output_token_ceiling_per_request=OUTPUT_TOKENS_PER_REQUEST,
        output_token_ceiling=output_tokens,
        input_price_per_million=INPUT_PRICE_PER_MILLION,
        output_price_per_million=OUTPUT_PRICE_PER_MILLION,
        preflight_cost_allowance=PREFLIGHT_COST_ALLOWANCE,
        estimated_max_cost=estimated_cost,
        price_source_url=PRICE_SOURCE_URL,
        estimated_at=estimated_at or utc_now(),
    )


def build_generation_approval(
    estimate: ScenarioGenerationEstimate,
    approved_max_cost: Decimal,
    approved_by: str,
    approval_note: str,
    approved_at: Optional[datetime] = None,
) -> ScenarioGenerationApproval:
    """Build one canonical approval from the researcher's explicit bounded authorization."""
    base = {
        "schema_version": "4.0.0",
        "generation_request_batch_sha256": estimate.request_batch_sha256,
        "request_count": estimate.request_count,
        "model_slug": estimate.model_slug,
        "provider_name": estimate.provider_name,
        "input_token_estimate": estimate.input_token_estimate,
        "output_token_ceiling": estimate.output_token_ceiling,
        "estimated_max_cost": estimate.estimated_max_cost,
        "currency": "USD",
        "approved_max_cost": approved_max_cost,
        "approved_by": approved_by,
        "approved_at": approved_at or utc_now(),
        "approval_note": approval_note,
    }
    return ScenarioGenerationApproval.model_validate({**base, "approval_sha256": artifact_sha256(base)})


def generation_controls() -> GenerationControls:
    """Return the frozen GPT-5.4 controls and strict scenario-output schema."""
    return GenerationControls(
        max_output_tokens=OUTPUT_TOKENS_PER_REQUEST,
        temperature=0.0,
        seed=7,
        reasoning_effort="none",
        extra_parameters={"response_format": _scenario_response_format()},
    )


def candidate_model_snapshot(estimate: ScenarioGenerationEstimate, preflight_passed: bool = False) -> ProviderSnapshot:
    """Build the pinned GPT-5.4 route snapshot from the frozen price metadata."""
    metadata = {
        "model_slug": MODEL_SLUG,
        "provider_name": PROVIDER_NAME,
        "provider_endpoint": PROVIDER_ENDPOINT,
        "routing_policy": "one_provider_only_no_fallback",
        "input_price_per_million": estimate.input_price_per_million,
        "output_price_per_million": estimate.output_price_per_million,
        "price_source_url": estimate.price_source_url,
        "estimated_at": estimate.estimated_at,
    }
    return ProviderSnapshot(
        model_slug=MODEL_SLUG,
        model_access=ModelAccess.CLOSED,
        licence_category=LicenceCategory.PROPRIETARY,
        provider_name=PROVIDER_NAME,
        provider_endpoint=PROVIDER_ENDPOINT,
        routing_policy="one_provider_only_no_fallback",
        metadata_snapshot_sha256=artifact_sha256(metadata),
        preflight_passed=preflight_passed,
    )


def build_generation_config(
    requests: List[GenerationRequest], approval: ScenarioGenerationApproval, created_at: Optional[datetime] = None
) -> ScenarioGenerationConfig:
    """Freeze a run configuration after verifying the exact approval coordinates."""
    estimate = build_generation_estimate(requests, estimated_at=approval.approved_at)
    _require_generation_approval(approval, estimate)
    timestamp = created_at or utc_now()
    base = {
        "schema_version": "4.0.0",
        "workflow": WORKFLOW_NAME,
        "run_id": timestamp.strftime("%Y%m%dT%H%M%SZ"),
        "generation_request_batch_sha256": estimate.request_batch_sha256,
        "request_count": len(requests),
        "approval_sha256": approval.approval_sha256,
        "candidate_model": candidate_model_snapshot(estimate),
        "generation_controls": generation_controls(),
        "estimate": estimate,
        "created_at": timestamp,
    }
    return ScenarioGenerationConfig.model_validate({**base, "config_sha256": artifact_sha256(base)})


def run_scenario_generation(
    requests: List[GenerationRequest],
    approval: ScenarioGenerationApproval,
    client: CompletionClient,
    generated_outputs_path: Path = SCENARIO_ROOT / "generated_outputs.jsonl",
    output_paths: Optional[Dict[str, Path]] = None,
) -> ScenarioGenerationSummary:
    """Run or resume all approved requests while preserving the first semantic output."""
    paths = output_paths or scenario_generation_paths()
    for name, path in paths.items():
        if name not in {"config", "approval"}:
            path.mkdir(parents=True, exist_ok=True)
    config = _load_or_create_config(paths["config"], requests, approval)
    write_json(paths["approval"], approval)
    preflight = _load_or_run_preflight(paths["results"] / "preflight.json", config, approval, client)
    records: List[ScenarioGenerationRecord] = []
    for request in requests:
        cache_path = paths["cache"] / f"{request.request_id}.json"
        record = _load_generation_record(cache_path, request, preflight.model, config.generation_controls)
        if record is None:
            reply = client.complete(preflight.model, config.generation_controls, _request_messages(request))
            record = _record_reply(request, preflight.model, config.generation_controls, reply)
            write_json(cache_path, record)
        records.append(record)
        _require_spend_within_approval(preflight, records, approval)
    results_path = paths["results"] / f"{config.run_id}_results.jsonl"
    write_jsonl(results_path, records)
    valid_outputs = [record.generated_output for record in records if record.generated_output is not None]
    write_jsonl(generated_outputs_path, valid_outputs)
    summary = _summarize(config, approval, preflight, records, generated_outputs_path)
    write_json(paths["results"] / "summary.json", summary)
    _write_run_log(paths["logs"] / f"{config.run_id}_run.log", summary, results_path)
    return summary


def _require_generation_approval(approval: ScenarioGenerationApproval, estimate: ScenarioGenerationEstimate) -> None:
    """Reject an approval for any different batch, route, token ceiling, or estimate."""
    expected = (
        estimate.request_batch_sha256,
        estimate.request_count,
        estimate.model_slug,
        estimate.provider_name,
        estimate.input_token_estimate,
        estimate.output_token_ceiling,
        estimate.estimated_max_cost,
    )
    actual = (
        approval.generation_request_batch_sha256,
        approval.request_count,
        approval.model_slug,
        approval.provider_name,
        approval.input_token_estimate,
        approval.output_token_ceiling,
        approval.estimated_max_cost,
    )
    if actual != expected:
        raise PermissionError("scenario-generation approval does not match the exact request batch, route, and estimate")


def _scenario_response_format() -> dict[str, object]:
    """Return an OpenAI-compatible strict JSON schema without unsupported defaults."""
    fact_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "fact_id": {"type": "string", "pattern": "^[A-Z0-9_]+_F[1-6]$"},
            "pair_id": {"type": "string", "pattern": "^[A-Z0-9_]+_P[1-3]$"},
            "option_id": {"type": "string", "enum": ["OPTION_A", "OPTION_B"]},
            "text": {"type": "string"},
            "anchor": {"type": "string"},
        },
        "required": ["fact_id", "pair_id", "option_id", "text", "anchor"],
    }
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "schema_version": {"type": "string", "const": "4.0.0"},
            "scenario_id": {"type": "string", "pattern": "^[A-Z]{2,3}[0-9]{3}_R[1-5]$"},
            "facts": {"type": "array", "items": fact_schema, "minItems": 6, "maxItems": 6},
        },
        "required": ["schema_version", "scenario_id", "facts"],
    }
    return {"type": "json_schema", "json_schema": {"name": "generated_scenario_facts", "strict": True, "schema": schema}}


def _probe_controls() -> GenerationControls:
    """Use the final decoding controls with a minimal strict schema for compatibility."""
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"status": {"type": "string", "const": "PREFLIGHT_OK"}},
        "required": ["status"],
    }
    return GenerationControls(
        max_output_tokens=64,
        temperature=0.0,
        seed=7,
        reasoning_effort="none",
        extra_parameters={"response_format": {"type": "json_schema", "json_schema": {"name": "preflight", "strict": True, "schema": schema}}},
    )


def _load_or_create_config(path: Path, requests: List[GenerationRequest], approval: ScenarioGenerationApproval) -> ScenarioGenerationConfig:
    """Reuse only an identical immutable config or create it before paid execution."""
    if path.exists():
        config = ScenarioGenerationConfig.model_validate(read_json(path))
        estimate = build_generation_estimate(requests, estimated_at=config.estimate.estimated_at)
        _require_generation_approval(approval, estimate)
        if config.generation_request_batch_sha256 != estimate.request_batch_sha256 or config.approval_sha256 != approval.approval_sha256:
            raise FileExistsError("existing scenario-generation config belongs to another batch or approval")
        return config
    config = build_generation_config(requests, approval)
    write_json(path, config)
    return config


def _load_or_run_preflight(
    path: Path,
    config: ScenarioGenerationConfig,
    approval: ScenarioGenerationApproval,
    client: CompletionClient,
) -> ScenarioGenerationPreflight:
    """Reuse a matching probe or run one approved structured-output compatibility call."""
    if path.exists():
        preflight = ScenarioGenerationPreflight.model_validate(read_json(path))
        if preflight.approval_sha256 != approval.approval_sha256 or preflight.model.model_slug != config.candidate_model.model_slug:
            raise PermissionError("existing scenario-generation preflight belongs to another approval or model")
        return preflight
    provisional = config.candidate_model.model_copy(update={"preflight_passed": True})
    reply = client.complete(provisional, _probe_controls(), [{"role": "user", "content": "Return the structured preflight status."}])
    parsed = json.loads(reply.text)
    if parsed != {"status": "PREFLIGHT_OK"}:
        raise ValueError("scenario-generation structured-output preflight returned an unexpected payload")
    model = provisional.model_copy(update={"returned_model_version": reply.returned_model_version})
    base = {
        "schema_version": "4.0.0",
        "approval_sha256": approval.approval_sha256,
        "model": model,
        "provider_request_id": reply.provider_request_id,
        "raw_response": reply.text,
        "returned_model_version": reply.returned_model_version,
        "input_tokens": reply.input_tokens,
        "output_tokens": reply.output_tokens,
        "billed_cost": reply.billed_cost,
        "calculated_cost": _calculated_cost(reply),
        "completed_at": reply.received_at,
    }
    preflight = ScenarioGenerationPreflight.model_validate({**base, "preflight_sha256": artifact_sha256(base)})
    write_json(path, preflight)
    return preflight


def _request_messages(request: GenerationRequest) -> List[dict[str, str]]:
    """Render one request as byte-stable system and compact JSON user messages."""
    payload = json.dumps(request.seed_payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return [{"role": "system", "content": request.system_prompt}, {"role": "user", "content": payload}]


def _record_reply(
    request: GenerationRequest,
    model: ProviderSnapshot,
    controls: GenerationControls,
    reply: ProviderReply,
) -> ScenarioGenerationRecord:
    """Parse one semantic response once and retain any structural failure without retrying."""
    generated: Optional[GeneratedScenarioOutput] = None
    validation_error: Optional[str] = None
    try:
        generated = GeneratedScenarioOutput.model_validate(json.loads(reply.text))
        validate_generated_output_for_request(generated, request)
    except (json.JSONDecodeError, ValueError) as error:
        validation_error = f"{type(error).__name__}: {error}"
    return ScenarioGenerationRecord(
        request_id=request.request_id,
        request_sha256=request.request_sha256,
        scenario_id=request.scenario_id,
        model=model,
        generation_controls=controls,
        provider_request_id=reply.provider_request_id,
        returned_model_version=reply.returned_model_version,
        raw_response=reply.text,
        generated_output=generated,
        structurally_valid=generated is not None,
        validation_error=validation_error,
        finish_reason=reply.finish_reason,
        input_tokens=reply.input_tokens,
        output_tokens=reply.output_tokens,
        billed_cost=reply.billed_cost,
        calculated_cost=_calculated_cost(reply),
        received_at=reply.received_at,
        attempts=reply.attempts,
    )


def _load_generation_record(
    path: Path,
    request: GenerationRequest,
    model: ProviderSnapshot,
    controls: GenerationControls,
) -> Optional[ScenarioGenerationRecord]:
    """Reuse one matching semantic cache record and reject any conflicting content."""
    if not path.exists():
        return None
    record = ScenarioGenerationRecord.model_validate(read_json(path))
    if record.request_id != request.request_id or record.request_sha256 != request.request_sha256:
        raise FileExistsError("cached scenario-generation response belongs to another request")
    if record.model != model or record.generation_controls != controls:
        raise FileExistsError("cached scenario-generation response used different model controls")
    return record


def _calculated_cost(reply: ProviderReply) -> Decimal:
    """Calculate list-price cost from provider-reported token usage."""
    return Decimal(reply.input_tokens) * INPUT_PRICE_PER_MILLION / Decimal(1_000_000) + Decimal(
        reply.output_tokens
    ) * OUTPUT_PRICE_PER_MILLION / Decimal(1_000_000)


def _effective_cost(preflight: ScenarioGenerationPreflight, records: List[ScenarioGenerationRecord]) -> Decimal:
    """Use the larger of reported and list-price-calculated cumulative costs."""
    items = [(preflight.billed_cost, preflight.calculated_cost), *((record.billed_cost, record.calculated_cost) for record in records)]
    return sum((max(reported or Decimal(0), calculated) for reported, calculated in items), Decimal(0))


def _require_spend_within_approval(
    preflight: ScenarioGenerationPreflight,
    records: List[ScenarioGenerationRecord],
    approval: ScenarioGenerationApproval,
) -> None:
    """Stop before any further call if observed cumulative cost reaches the approved ceiling."""
    if _effective_cost(preflight, records) > approval.approved_max_cost:
        raise PermissionError("observed scenario-generation cost exceeded the approved maximum")


def _summarize(
    config: ScenarioGenerationConfig,
    approval: ScenarioGenerationApproval,
    preflight: ScenarioGenerationPreflight,
    records: List[ScenarioGenerationRecord],
    generated_outputs_path: Path,
) -> ScenarioGenerationSummary:
    """Aggregate provider usage and structural validity across the completed batch."""
    billed_items = [preflight.billed_cost, *(record.billed_cost for record in records)]
    return ScenarioGenerationSummary(
        request_batch_sha256=config.generation_request_batch_sha256,
        approval_sha256=approval.approval_sha256,
        request_count=config.request_count,
        semantic_response_count=len(records),
        valid_output_count=sum(record.structurally_valid for record in records),
        invalid_output_count=sum(not record.structurally_valid for record in records),
        input_tokens=preflight.input_tokens + sum(record.input_tokens for record in records),
        output_tokens=preflight.output_tokens + sum(record.output_tokens for record in records),
        reported_cost_record_count=sum(cost is not None for cost in billed_items),
        reported_billed_cost=sum((cost or Decimal(0) for cost in billed_items), Decimal(0)),
        calculated_cost=preflight.calculated_cost + sum((record.calculated_cost for record in records), Decimal(0)),
        approved_max_cost=approval.approved_max_cost,
        generated_outputs_path=generated_outputs_path,
        completed_at=utc_now(),
    )


def _write_run_log(path: Path, summary: ScenarioGenerationSummary, results_path: Path) -> None:
    """Write a stable human-readable run log without exposing credentials or prompt content."""
    lines = [
        f"workflow={summary.workflow}",
        f"request_batch_sha256={summary.request_batch_sha256}",
        f"semantic_response_count={summary.semantic_response_count}",
        f"valid_output_count={summary.valid_output_count}",
        f"invalid_output_count={summary.invalid_output_count}",
        f"input_tokens={summary.input_tokens}",
        f"output_tokens={summary.output_tokens}",
        f"reported_billed_cost_usd={summary.reported_billed_cost}",
        f"calculated_cost_usd={summary.calculated_cost}",
        f"results_path={results_path}",
        f"generated_outputs_path={summary.generated_outputs_path}",
    ]
    atomic_write_bytes(path, ("\n".join(lines) + "\n").encode("utf-8"))
