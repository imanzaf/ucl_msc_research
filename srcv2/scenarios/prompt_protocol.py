"""Approval and application of seed-owned evaluated-prompt deployment contexts."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import Field, model_validator

from srcv2.common import ImmutableModel, artifact_sha256, utc_now
from srcv2.models.scenarios import AcceptedScenario
from srcv2.models.seeds import DeploymentContext, ScenarioSeedSet, UseCaseSeed


class PromptContextSpec(ImmutableModel):
    """Define one natural use-case role, task, and short authority limit."""

    use_case_id: str = Field(pattern=r"^[A-Z]{2,3}[0-9]{3}$")
    role: str = Field(min_length=2)
    entity_name: str = Field(min_length=2)
    entity_type: str = Field(min_length=2)
    task: str = Field(min_length=2)
    authority_limit: str = Field(min_length=2)

    def deployment_context(self) -> DeploymentContext:
        """Convert the approved specification to the seed deployment-context model."""
        return DeploymentContext(
            role=self.role,
            entity_name=self.entity_name,
            entity_type=self.entity_type,
            task=self.task,
            authority_limits=[self.authority_limit],
        )


class PromptContextSet(ImmutableModel):
    """Store exactly one approved deployment context for each use case."""

    schema_version: str = Field(default="4.0.0", pattern=r"^4\.0\.0$")
    contexts: List[PromptContextSpec] = Field(min_length=6, max_length=6)

    @model_validator(mode="after")
    def validate_use_cases(self) -> "PromptContextSet":
        """Require the six final use-case identifiers exactly once."""
        identifiers = [context.use_case_id for context in self.contexts]
        expected = {f"CF{number}" for number in range(101, 107)}
        if len(set(identifiers)) != 6 or set(identifiers) != expected:
            raise ValueError("prompt contexts must cover CF101 through CF106 exactly once")
        if any(len(context.deployment_context().authority_limits) != 1 for context in self.contexts):
            raise ValueError("each prompt context must contain one authority-limit sentence")
        return self


class PromptProtocolApproval(ImmutableModel):
    """Bind explicit approval to the source corpus and six prompt contexts."""

    schema_version: str = Field(default="4.0.0", pattern=r"^4\.0\.0$")
    source_seed_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_scenarios_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt_contexts_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_by: str = Field(min_length=1)
    approval_note: str = Field(min_length=1)
    approved_at: datetime
    approval_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_approval_hash(self) -> "PromptProtocolApproval":
        """Require the approval digest to bind every other field."""
        expected = artifact_sha256(self.model_dump(mode="json", exclude={"approval_sha256"}))
        if self.approval_sha256 != expected:
            raise ValueError("prompt-protocol approval hash does not match its contents")
        return self


def validate_prompt_contexts(seed_set: ScenarioSeedSet, context_set: PromptContextSet) -> None:
    """Require approved contexts to retain each fictional deployment entity and type."""
    source = {use_case.use_case_id: use_case.deployment_context for use_case in seed_set.use_cases}
    for context in context_set.contexts:
        if context.entity_name != source[context.use_case_id].entity_name:
            raise ValueError(f"prompt context changes the deployment entity for {context.use_case_id}")
        if context.entity_type != source[context.use_case_id].entity_type:
            raise ValueError(f"prompt context changes the deployment entity type for {context.use_case_id}")
        if "benchmark" in f"{context.role} {context.task} {context.authority_limit}".lower():
            raise ValueError("evaluated prompt context cannot contain research-facing benchmark language")


def build_prompt_protocol_approval(
    seed_set: ScenarioSeedSet,
    scenario_records: List[Dict[str, object]],
    context_set: PromptContextSet,
    approved_by: str,
    approval_note: str,
    approved_at: Optional[datetime] = None,
) -> PromptProtocolApproval:
    """Create a hash-bound approval for the six seed-owned prompt contexts."""
    validate_prompt_contexts(seed_set, context_set)
    approval_time = approved_at or utc_now()
    source_seed_sha256 = artifact_sha256(seed_set)
    source_scenarios_sha256 = artifact_sha256(scenario_records)
    prompt_contexts_sha256 = artifact_sha256(context_set)
    payload = {
        "schema_version": "4.0.0",
        "source_seed_sha256": source_seed_sha256,
        "source_scenarios_sha256": source_scenarios_sha256,
        "prompt_contexts_sha256": prompt_contexts_sha256,
        "approved_by": approved_by,
        "approval_note": approval_note,
        "approved_at": approval_time,
    }
    return PromptProtocolApproval(
        source_seed_sha256=source_seed_sha256,
        source_scenarios_sha256=source_scenarios_sha256,
        prompt_contexts_sha256=prompt_contexts_sha256,
        approved_by=approved_by,
        approval_note=approval_note,
        approved_at=approval_time,
        approval_sha256=artifact_sha256(payload),
    )


def apply_prompt_protocol(
    seed_set: ScenarioSeedSet,
    scenario_records: List[Dict[str, object]],
    context_set: PromptContextSet,
    approval: PromptProtocolApproval,
) -> tuple[ScenarioSeedSet, List[AcceptedScenario]]:
    """Apply approved prompt contexts without changing scenario facts or generation provenance."""
    validate_prompt_contexts(seed_set, context_set)
    if artifact_sha256(seed_set) != approval.source_seed_sha256:
        raise PermissionError("prompt approval belongs to a different source seed")
    if artifact_sha256(scenario_records) != approval.source_scenarios_sha256:
        raise PermissionError("prompt approval belongs to a different accepted-scenario corpus")
    if artifact_sha256(context_set) != approval.prompt_contexts_sha256:
        raise PermissionError("prompt approval belongs to different deployment contexts")
    contexts = {context.use_case_id: context.deployment_context() for context in context_set.contexts}
    use_cases = [
        UseCaseSeed.model_validate(
            {
                **use_case.model_dump(mode="json", exclude={"deployment_context"}),
                "deployment_context": contexts[use_case.use_case_id],
            }
        )
        for use_case in seed_set.use_cases
    ]
    final_seed_set = ScenarioSeedSet.model_validate({**seed_set.model_dump(mode="json", exclude={"use_cases"}), "use_cases": use_cases})
    scenarios = attach_prompt_contexts(scenario_records, context_set)
    return final_seed_set, scenarios


def attach_prompt_contexts(scenario_records: List[Dict[str, object]], context_set: PromptContextSet) -> List[AcceptedScenario]:
    """Attach the six approved contexts to scenario records without altering other fields."""
    contexts = {context.use_case_id: context.deployment_context() for context in context_set.contexts}
    return [
        AcceptedScenario.model_validate(
            {
                **record,
                "deployment_context": contexts[str(record["scenario_id"]).split("_")[0]],
            }
        )
        for record in scenario_records
    ]
