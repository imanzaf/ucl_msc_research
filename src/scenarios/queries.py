"""Validation and materialization of explicitly authored natural query families."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import Field, model_validator

from src.common import ImmutableModel, artifact_sha256, utc_now
from src.models.enums import Affect, QueryLength
from src.models.queries import AuthoredQueryFamily, QueryVariant
from src.models.scenarios import AcceptedScenario


class QueryProtocolApproval(ImmutableModel):
    """Bind researcher approval to the accepted corpus and its authored query families."""

    schema_version: str = Field(default="4.0.0", pattern=r"^4\.0\.0$")
    source_scenarios_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    query_families_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    query_variants_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_by: str = Field(min_length=1)
    approval_note: str = Field(min_length=1)
    approved_at: datetime
    approval_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_approval_hash(self) -> "QueryProtocolApproval":
        """Require the approval digest to bind every other approval field."""
        expected = artifact_sha256(self.model_dump(mode="json", exclude={"approval_sha256"}))
        if self.approval_sha256 != expected:
            raise ValueError("query-protocol approval hash does not match its contents")
        return self


def build_query_variant(family: AuthoredQueryFamily, affect: Affect, query_length: QueryLength) -> QueryVariant:
    """Build one query variant from researcher-approved scenario-specific wording."""
    return QueryVariant(
        query_variant_id=f"{family.scenario_id}_{affect.value}_{query_length.value}",
        scenario_id=family.scenario_id,
        affect=affect,
        query_length=query_length,
        text=family.text_for(affect, query_length),
    )


def build_user_state_queries(family: AuthoredQueryFamily) -> List[QueryVariant]:
    """Build the six affect-by-length variants for one scenario."""
    return [build_query_variant(family, affect, query_length) for affect in Affect for query_length in QueryLength]


def validate_query_family(family: AuthoredQueryFamily, variants: List[QueryVariant]) -> None:
    """Require a query family to equal its six authored treatment coordinates exactly."""
    expected = {variant.query_variant_id: variant for variant in build_user_state_queries(family)}
    observed = {variant.query_variant_id: variant for variant in variants}
    if len(variants) != 6 or len(observed) != 6 or set(observed) != set(expected):
        raise ValueError("query family must contain the six unique authored treatment coordinates")
    mismatches = [identifier for identifier in expected if observed[identifier] != expected[identifier]]
    if mismatches:
        raise ValueError("query variants differ from the approved authored texts: " + ", ".join(sorted(mismatches)))


def validate_query_corpus(scenario_ids: List[str], families: List[AuthoredQueryFamily]) -> None:
    """Require one complete authored query family for every corpus scenario."""
    family_ids = [family.scenario_id for family in families]
    if len(scenario_ids) != 30 or len(set(scenario_ids)) != 30:
        raise ValueError("query corpus validation requires thirty unique scenario identifiers")
    if len(family_ids) != 30 or len(set(family_ids)) != 30 or set(family_ids) != set(scenario_ids):
        raise ValueError("query corpus must contain one unique family for every scenario")
    for family in families:
        validate_query_family(family, build_user_state_queries(family))


def build_query_protocol_approval(
    scenarios: List[AcceptedScenario],
    families: List[AuthoredQueryFamily],
    approved_by: str,
    approval_note: str,
    approved_at: Optional[datetime] = None,
) -> QueryProtocolApproval:
    """Create a hash-bound approval for the six-query family attached to every scenario."""
    validate_query_corpus([scenario.scenario_id for scenario in scenarios], families)
    variants = [query for family in families for query in build_user_state_queries(family)]
    approval_time = approved_at or utc_now()
    source_scenarios_sha256 = artifact_sha256(scenarios)
    query_families_sha256 = artifact_sha256(families)
    query_variants_sha256 = artifact_sha256(variants)
    payload = {
        "schema_version": "4.0.0",
        "source_scenarios_sha256": source_scenarios_sha256,
        "query_families_sha256": query_families_sha256,
        "query_variants_sha256": query_variants_sha256,
        "approved_by": approved_by,
        "approval_note": approval_note,
        "approved_at": approval_time,
    }
    return QueryProtocolApproval(
        source_scenarios_sha256=source_scenarios_sha256,
        query_families_sha256=query_families_sha256,
        query_variants_sha256=query_variants_sha256,
        approved_by=approved_by,
        approval_note=approval_note,
        approved_at=approval_time,
        approval_sha256=artifact_sha256(payload),
    )


def apply_query_protocol(
    scenarios: List[AcceptedScenario],
    families: List[AuthoredQueryFamily],
    approval: QueryProtocolApproval,
) -> tuple[List[AcceptedScenario], List[QueryVariant]]:
    """Republish accepted scenarios with approved natural queries while preserving their facts and provenance."""
    validate_query_corpus([scenario.scenario_id for scenario in scenarios], families)
    variants = [query for family in families for query in build_user_state_queries(family)]
    if artifact_sha256(scenarios) != approval.source_scenarios_sha256:
        raise PermissionError("query approval belongs to a different accepted-scenario corpus")
    if artifact_sha256(families) != approval.query_families_sha256 or artifact_sha256(variants) != approval.query_variants_sha256:
        raise PermissionError("query approval belongs to different authored query content")
    family_by_id = {family.scenario_id: family for family in families}
    republished = [
        AcceptedScenario.model_validate(
            {
                **scenario.model_dump(mode="json", exclude={"query_stem"}),
                "query_stem": family_by_id[scenario.scenario_id].neutral_short,
            }
        )
        for scenario in scenarios
    ]
    return republished, variants


def assigned_fact_order(scenario_index: int) -> int:
    """Assign one of two fixed fact orders with a 15/15 corpus balance."""
    if not 0 <= scenario_index < 30:
        raise ValueError("scenario index must be between zero and twenty-nine")
    return 1 if scenario_index < 15 else 2
