"""Immutable final-protocol manifest and approval models."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional

from pydantic import Field, model_validator

from srcv2.common import ImmutableModel, artifact_sha256
from srcv2.models.enums import ExperimentKind
from srcv2.models.experiments import GenerationControls, ProviderSnapshot


class ProtocolManifest(ImmutableModel):
    """Freeze the active experiments, models, controls, corpus, and expected count."""

    schema_version: str = Field(default="4.0.0", pattern=r"^4\.0\.0$")
    protocol_id: str = Field(default="final_protocol", pattern=r"^final_protocol$")
    scenario_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    experiments: List[ExperimentKind]
    expected_response_counts: Dict[ExperimentKind, int]
    evaluated_models: List[ProviderSnapshot] = Field(min_length=7, max_length=7)
    scorer_model: ProviderSnapshot
    generation_controls: Dict[str, GenerationControls]
    frozen_at: datetime
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_manifest(self) -> "ProtocolManifest":
        """Enforce the active 3,822-response matrix and bind the manifest hash."""
        expected_counts = {
            ExperimentKind.USER_STATE: 1260,
            ExperimentKind.INFORMATION_BUDGET: 1050,
            ExperimentKind.WORD_BUDGET: 630,
            ExperimentKind.SINGLE_FACT: 210,
            ExperimentKind.OWNERSHIP: 462,
            ExperimentKind.OPTION_FIRST: 210,
        }
        if self.expected_response_counts != expected_counts or set(self.experiments) != set(expected_counts):
            raise ValueError("manifest must contain exactly the six active experiments and their 3,822 planned responses")
        model_slugs = [model.model_slug for model in self.evaluated_models]
        if len(set(model_slugs)) != 7 or self.scorer_model.model_slug in model_slugs:
            raise ValueError("manifest must contain seven unique evaluated models and a distinct scorer")
        if set(self.generation_controls) != {*model_slugs, self.scorer_model.model_slug}:
            raise ValueError("manifest generation controls must cover exactly the frozen models and scorer")
        if not all(model.preflight_passed for model in [*self.evaluated_models, self.scorer_model]):
            raise ValueError("every frozen model and scorer must have passed operational preflight")
        expected_hash = artifact_sha256(self.model_dump(mode="json", exclude={"manifest_sha256"}))
        if self.manifest_sha256 != expected_hash:
            raise ValueError("protocol manifest hash does not match canonical content")
        return self


class CostApproval(ImmutableModel):
    """Require explicit, bounded authorization before any evaluated paid execution."""

    schema_version: str = Field(default="4.0.0", pattern=r"^4\.0\.0$")
    protocol_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    estimated_max_cost: Decimal = Field(gt=0)
    currency: str = Field(default="USD", pattern=r"^USD$")
    approved_max_cost: Decimal = Field(gt=0)
    approved_by: str = Field(min_length=2)
    approved_at: datetime
    approval_note: str = Field(min_length=2)
    approval_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_approval(self) -> "CostApproval":
        """Ensure the approved ceiling covers the estimate and bind the approval hash."""
        if self.approved_max_cost < self.estimated_max_cost:
            raise ValueError("approved maximum cost is below the estimated maximum")
        expected_hash = artifact_sha256(self.model_dump(mode="json", exclude={"approval_sha256"}))
        if self.approval_sha256 != expected_hash:
            raise ValueError("cost approval hash does not match canonical content")
        return self


class PreflightApproval(ImmutableModel):
    """Authorize the bounded compatibility probes needed before protocol freezing."""

    schema_version: str = Field(default="4.0.0", pattern=r"^4\.0\.0$")
    model_catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    estimated_max_cost: Decimal = Field(gt=0)
    approved_max_cost: Decimal = Field(gt=0)
    currency: str = Field(default="USD", pattern=r"^USD$")
    approved_by: str = Field(min_length=2)
    approved_at: datetime
    approval_note: str = Field(min_length=2)
    approval_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_approval(self) -> "PreflightApproval":
        """Bind the exact catalog and ensure the approval covers the preflight estimate."""
        if self.approved_max_cost < self.estimated_max_cost:
            raise ValueError("approved maximum cost is below the preflight estimate")
        expected_hash = artifact_sha256(self.model_dump(mode="json", exclude={"approval_sha256"}))
        if self.approval_sha256 != expected_hash:
            raise ValueError("preflight approval hash does not match canonical content")
        return self


class ScenarioGenerationApproval(ImmutableModel):
    """Bind bounded paid authorization to one scenario request batch and route."""

    schema_version: str = Field(default="4.0.0", pattern=r"^4\.0\.0$")
    generation_request_batch_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_count: int = Field(default=30, ge=1)
    model_slug: str = Field(min_length=3)
    provider_name: str = Field(min_length=1)
    input_token_estimate: int = Field(ge=1)
    output_token_ceiling: int = Field(ge=1)
    estimated_max_cost: Decimal = Field(gt=0)
    currency: str = Field(default="USD", pattern=r"^USD$")
    approved_max_cost: Decimal = Field(gt=0)
    approved_by: str = Field(min_length=2)
    approved_at: datetime
    approval_note: str = Field(min_length=2)
    approval_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_approval(self) -> "ScenarioGenerationApproval":
        """Ensure the bounded approval covers the estimate and its canonical content."""
        if self.approved_max_cost < self.estimated_max_cost:
            raise ValueError("approved maximum cost is below the generation estimate")
        expected_hash = artifact_sha256(self.model_dump(mode="json", exclude={"approval_sha256"}))
        if self.approval_sha256 != expected_hash:
            raise ValueError("scenario-generation approval hash does not match canonical content")
        return self


class ExecutionCheckpoint(ImmutableModel):
    """Record resumable progress without changing a frozen run plan."""

    schema_version: str = Field(default="4.0.0", pattern=r"^4\.0\.0$")
    experiment: ExperimentKind
    run_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    completed_run_unit_ids: List[str]
    updated_at: datetime
    last_error: Optional[str] = None
