"""Run-plan materialization and pre-execution safety gates."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Sequence

from pydantic import Field, model_validator

from srcv2.common import ImmutableModel, artifact_sha256, utc_now
from srcv2.experiments.matrix import MatrixAssignment
from srcv2.models.enums import Affect, ExecutionStatus, QueryLength, ReviewState
from srcv2.models.experiments import GenerationControls, InformationBudgetCell, ProviderSnapshot, UserStateCell
from srcv2.models.manifests import CostApproval, ProtocolManifest
from srcv2.models.queries import QueryVariant
from srcv2.models.scenarios import AcceptedScenario
from srcv2.prompts.rendering import RenderedPrompt, render_prompt
from srcv2.storage import read_json, write_json


class CostEstimate(ImmutableModel):
    """Store the declared upper-bound cost estimate before approval."""

    schema_version: str = Field(default="4.0.0", pattern=r"^4\.0\.0$")
    protocol_manifest_sha256: str
    input_token_estimate: int = Field(ge=0)
    output_token_ceiling: int = Field(ge=0)
    model_costs: Dict[str, Decimal]
    estimated_max_cost: Decimal = Field(ge=0)
    currency: str = "USD"
    estimated_at: str


class ExecutionBundle(ImmutableModel):
    """Materialize everything needed to execute one immutable assignment."""

    schema_version: str = Field(default="4.0.0", pattern=r"^4\.0\.0$")
    protocol_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    assignment: MatrixAssignment
    prompt: RenderedPrompt
    model: ProviderSnapshot
    generation_controls: GenerationControls
    valid_fact_ids: List[str] = Field(min_length=6, max_length=6)

    @model_validator(mode="after")
    def validate_bindings(self) -> "ExecutionBundle":
        """Bind assignment, prompt, model, and six fact identifiers consistently."""
        if self.assignment.execution_status != ExecutionStatus.ACTIVE:
            raise ValueError("deferred assignments cannot be materialized for execution")
        if self.assignment.scenario_id != self.prompt.scenario_id or self.assignment.cell.kind != self.prompt.experiment:
            raise ValueError("execution bundle prompt does not match its assignment")
        if self.assignment.model_slug != self.model.model_slug:
            raise ValueError("execution bundle model does not match its assignment")
        if len(set(self.valid_fact_ids)) != 6:
            raise ValueError("execution bundle requires six unique valid fact identifiers")
        return self


def _assigned_query(assignment: MatrixAssignment, query_by_id: Dict[str, QueryVariant]) -> QueryVariant:
    """Resolve the exact controlled query for one matrix assignment."""
    affect: Affect
    length: QueryLength
    if isinstance(assignment.cell, UserStateCell):
        affect = assignment.cell.affect
        length = assignment.cell.query_length
    else:
        affect = assignment.cell.affect if isinstance(assignment.cell, InformationBudgetCell) else Affect.NEUTRAL
        length = QueryLength.SHORT
    identifier = f"{assignment.scenario_id}_{affect.value}_{length.value}"
    if identifier not in query_by_id:
        raise ValueError(f"missing controlled query variant {identifier}")
    return query_by_id[identifier]


def build_execution_bundles(
    assignments: Sequence[MatrixAssignment],
    scenarios: Sequence[AcceptedScenario],
    queries: Sequence[QueryVariant],
    manifest: ProtocolManifest,
) -> List[ExecutionBundle]:
    """Materialize accepted scenarios and frozen provider metadata into run bundles."""
    scenario_by_id = {scenario.scenario_id: scenario for scenario in scenarios}
    query_by_id = {query.query_variant_id: query for query in queries}
    model_by_slug = {model.model_slug: model for model in manifest.evaluated_models}
    if len(scenario_by_id) != len(scenarios) or len(query_by_id) != len(queries):
        raise ValueError("scenario and query identifiers must be unique")
    if any(scenario.review.state != ReviewState.ACCEPTED for scenario in scenarios):
        raise PermissionError("execution bundles require researcher-accepted scenarios")
    corpus_hash = artifact_sha256({"scenarios": list(scenarios), "queries": list(queries)})
    if corpus_hash != manifest.scenario_manifest_sha256:
        raise PermissionError("scenario and query artifacts differ from the frozen protocol manifest")
    bundles: List[ExecutionBundle] = []
    for assignment in assignments:
        if assignment.scenario_id not in scenario_by_id or assignment.model_slug not in model_by_slug:
            raise ValueError("assignment references a scenario or model outside the frozen protocol")
        scenario = scenario_by_id[assignment.scenario_id]
        query = _assigned_query(assignment, query_by_id)
        prompt = render_prompt(scenario, query, assignment.cell, assignment.fact_order)
        bundles.append(
            ExecutionBundle(
                protocol_manifest_sha256=manifest.manifest_sha256,
                assignment=assignment,
                prompt=prompt,
                model=model_by_slug[assignment.model_slug],
                generation_controls=manifest.generation_controls[assignment.model_slug],
                valid_fact_ids=[fact.fact_id for fact in scenario.facts],
            )
        )
    return bundles


def write_run_plan(path: Path, assignments: List[MatrixAssignment]) -> str:
    """Write a stable run plan and return its canonical digest."""
    payload = {
        "schema_version": "4.0.0",
        "response_count": len(assignments),
        "assignments": [assignment.model_dump(mode="json") for assignment in assignments],
    }
    digest = artifact_sha256(payload)
    write_json(path, {**payload, "run_plan_sha256": digest})
    return digest


def require_cost_approval(path: Path, protocol_manifest_sha256: str, estimated_cost: Decimal) -> CostApproval:
    """Fail closed unless an exact-manifest approval covers the estimated cost."""
    if not path.exists():
        raise PermissionError("paid execution requires an explicit cost approval artifact")
    approval = CostApproval.model_validate(read_json(path))
    if approval.protocol_manifest_sha256 != protocol_manifest_sha256:
        raise PermissionError("cost approval belongs to a different protocol manifest")
    if approval.approved_max_cost < estimated_cost:
        raise PermissionError("approved cost ceiling does not cover the current estimate")
    return approval


def build_cost_estimate(
    protocol_manifest_sha256: str,
    input_token_estimate: int,
    output_token_ceiling: int,
    model_costs: Dict[str, Decimal],
) -> CostEstimate:
    """Create a transparent cost estimate from caller-supplied current pricing."""
    total = sum(model_costs.values(), Decimal("0"))
    return CostEstimate(
        protocol_manifest_sha256=protocol_manifest_sha256,
        input_token_estimate=input_token_estimate,
        output_token_ceiling=output_token_ceiling,
        model_costs=model_costs,
        estimated_max_cost=total,
        estimated_at=utc_now().isoformat(),
    )
