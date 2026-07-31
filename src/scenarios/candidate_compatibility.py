"""Load option-centric scenarios while authenticating older flattened schemas."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal

from pydantic import Field, model_validator

from src.data_models.common import ImmutableModel, VersionedImmutableModel, artifact_sha256
from src.data_models.scenarios import (
    AcceptedScenario,
    ArtifactProvenance,
    CandidateScenario,
    CustomerMessages,
    DecisionOption,
    DeploymentContext,
    FactPolarity,
    MaterialFact,
    OptionDescription,
    ScenarioFactInformation,
    ScenarioHiddenDesign,
    ScenarioOptionInformation,
    ScenarioStage,
    SeedOptionId,
    SpecificityElement,
    alternative_seed_option,
    material_fact_pairs,
)


class _LegacyFactPair(ImmutableModel):
    """Validate one removed schema-6 pair manifest during compatibility loading."""

    pair_id: str = Field(pattern=r"^CF\d{3}_(C1|R[12])_P[12]$")
    pair_type: Literal["benefit_comparison", "downside_comparison"]
    owner_option_fact_id: str = Field(pattern=r"^CF\d{3}_(C1|R[12])_F[1-4]$")
    alternative_option_fact_id: str = Field(pattern=r"^CF\d{3}_(C1|R[12])_F[1-4]$")
    matching_rationale: str = Field(min_length=1)


class _LegacyMaterialFact(ImmutableModel):
    """Authenticate one pre-schema-8 fact containing redundant materiality metadata."""

    fact_id: str = Field(pattern=r"^CF\d{3}_(C1|R[12])_F[1-4]$")
    pair_id: str = Field(pattern=r"^CF\d{3}_(C1|R[12])_P[12]$")
    option: DecisionOption
    polarity: FactPolarity
    canonical_proposition: str = Field(min_length=1)
    materiality_rationale: str = Field(min_length=1)
    required_in_complete_response: bool
    materiality_rating: int = Field(ge=1, le=4)

    @model_validator(mode="after")
    def validate_legacy_materiality(self) -> "_LegacyMaterialFact":
        """Require the legacy fact to satisfy its original materiality invariants."""
        if not self.required_in_complete_response or self.materiality_rating < 3:
            raise ValueError("legacy material facts must be required and materially rated")
        return self


class _LegacyCandidateScenario(VersionedImmutableModel):
    """Validate a complete schema-6 candidate before deriving its current view."""

    schema_version: Literal["6.0.0"]
    scenario_id: str = Field(pattern=r"^CF\d{3}_(C1|R[12])$")
    use_case_id: str = Field(pattern=r"^CF\d{3}$")
    study_stage: ScenarioStage
    deployment_context: DeploymentContext
    customer_messages: CustomerMessages
    hidden_design: ScenarioHiddenDesign
    option_descriptions: List[OptionDescription] = Field(min_length=2, max_length=2)
    material_facts: List[_LegacyMaterialFact] = Field(min_length=4, max_length=4)
    fact_pairs: List[_LegacyFactPair] = Field(min_length=2, max_length=2)
    specificity_elements: List[SpecificityElement] = Field(max_length=12)
    provenance: ArtifactProvenance
    candidate_sha256: str

    @model_validator(mode="after")
    def validate_legacy_candidate(self) -> "_LegacyCandidateScenario":
        """Authenticate the original artifact and its now-derived pair manifest."""
        expected_hash = artifact_sha256(self.model_dump(mode="json", exclude={"candidate_sha256"}))
        if self.candidate_sha256 != expected_hash:
            raise ValueError("legacy candidate_sha256 does not match canonical candidate content")
        pair_by_id = {pair.pair_id: pair for pair in self.fact_pairs}
        if len(pair_by_id) != 2:
            raise ValueError("legacy candidate fact pair identifiers must be unique")
        for pair_number, (owner_fact, alternative_fact) in enumerate(material_fact_pairs(self.material_facts), start=1):
            pair_id = f"{self.scenario_id}_P{pair_number}"
            pair = pair_by_id.get(pair_id)
            expected_type = "benefit_comparison" if owner_fact.polarity == FactPolarity.BENEFIT else "downside_comparison"
            if (
                pair is None
                or pair.pair_type != expected_type
                or pair.owner_option_fact_id != owner_fact.fact_id
                or pair.alternative_option_fact_id != alternative_fact.fact_id
            ):
                raise ValueError("legacy fact pair manifest does not match its material facts")
        return self


class _PreviousCandidateScenario(VersionedImmutableModel):
    """Validate a complete schema-7 candidate before deriving its current view."""

    schema_version: Literal["7.0.0"]
    scenario_id: str = Field(pattern=r"^CF\d{3}_(C1|R[12])$")
    use_case_id: str = Field(pattern=r"^CF\d{3}$")
    study_stage: ScenarioStage
    deployment_context: DeploymentContext
    customer_messages: CustomerMessages
    hidden_design: ScenarioHiddenDesign
    option_descriptions: List[OptionDescription] = Field(min_length=2, max_length=2)
    material_facts: List[_LegacyMaterialFact] = Field(min_length=4, max_length=4)
    specificity_elements: List[SpecificityElement] = Field(max_length=12)
    provenance: ArtifactProvenance
    candidate_sha256: str

    @model_validator(mode="after")
    def validate_previous_candidate(self) -> "_PreviousCandidateScenario":
        """Authenticate the original schema-7 artifact before conversion."""
        expected_hash = artifact_sha256(self.model_dump(mode="json", exclude={"candidate_sha256"}))
        if self.candidate_sha256 != expected_hash:
            raise ValueError("schema-7 candidate_sha256 does not match canonical candidate content")
        return self


class _PreviousAcceptedScenario(VersionedImmutableModel):
    """Validate a complete schema-7 accepted artifact before deriving its current view."""

    schema_version: Literal["7.0.0"]
    artifact_version: str = Field(pattern=r"^v[1-9][0-9]*$")
    scenario_id: str = Field(pattern=r"^CF\d{3}_(C1|R[12])$")
    use_case_id: str = Field(pattern=r"^CF\d{3}$")
    study_stage: ScenarioStage
    deployment_context: DeploymentContext
    customer_messages: CustomerMessages
    hidden_design: ScenarioHiddenDesign
    option_descriptions: List[OptionDescription] = Field(min_length=2, max_length=2)
    material_facts: List[_LegacyMaterialFact] = Field(min_length=4, max_length=4)
    specificity_elements: List[SpecificityElement] = Field(max_length=12)
    review_history_sha256: str
    acceptance_record_sha256: str
    accepted_at: datetime
    accepted_by: str = Field(min_length=1)
    artifact_sha256: str

    @model_validator(mode="after")
    def validate_previous_accepted(self) -> "_PreviousAcceptedScenario":
        """Authenticate the original schema-7 accepted artifact before conversion."""
        expected_hash = artifact_sha256(self.model_dump(mode="json", exclude={"artifact_sha256"}))
        if self.artifact_sha256 != expected_hash:
            raise ValueError("schema-7 artifact_sha256 does not match canonical accepted content")
        return self


class _SchemaEightCandidateScenario(VersionedImmutableModel):
    """Authenticate one flattened schema-8 candidate before conversion."""

    schema_version: Literal["8.0.0"]
    scenario_id: str = Field(pattern=r"^CF\d{3}_(C1|R[12])$")
    use_case_id: str = Field(pattern=r"^CF\d{3}$")
    study_stage: ScenarioStage
    deployment_context: DeploymentContext
    customer_messages: CustomerMessages
    hidden_design: ScenarioHiddenDesign
    option_descriptions: List[OptionDescription] = Field(min_length=2, max_length=2)
    material_facts: List[MaterialFact] = Field(min_length=4, max_length=4)
    specificity_elements: List[SpecificityElement] = Field(max_length=12)
    provenance: ArtifactProvenance
    candidate_sha256: str

    @model_validator(mode="after")
    def validate_schema_eight_candidate(self) -> "_SchemaEightCandidateScenario":
        """Authenticate the original schema-8 candidate before conversion."""
        expected_hash = artifact_sha256(self.model_dump(mode="json", exclude={"candidate_sha256"}))
        if self.candidate_sha256 != expected_hash:
            raise ValueError("schema-8 candidate_sha256 does not match canonical candidate content")
        material_fact_pairs(self.material_facts)
        return self


class _SchemaEightAcceptedScenario(VersionedImmutableModel):
    """Authenticate one flattened schema-8 accepted artifact before conversion."""

    schema_version: Literal["8.0.0"]
    artifact_version: str = Field(pattern=r"^v[1-9][0-9]*$")
    scenario_id: str = Field(pattern=r"^CF\d{3}_(C1|R[12])$")
    use_case_id: str = Field(pattern=r"^CF\d{3}$")
    study_stage: ScenarioStage
    deployment_context: DeploymentContext
    customer_messages: CustomerMessages
    hidden_design: ScenarioHiddenDesign
    option_descriptions: List[OptionDescription] = Field(min_length=2, max_length=2)
    material_facts: List[MaterialFact] = Field(min_length=4, max_length=4)
    specificity_elements: List[SpecificityElement] = Field(max_length=12)
    review_history_sha256: str
    acceptance_record_sha256: str
    accepted_at: datetime
    accepted_by: str = Field(min_length=1)
    artifact_sha256: str

    @model_validator(mode="after")
    def validate_schema_eight_accepted(self) -> "_SchemaEightAcceptedScenario":
        """Authenticate the original schema-8 artifact before conversion."""
        expected_hash = artifact_sha256(self.model_dump(mode="json", exclude={"artifact_sha256"}))
        if self.artifact_sha256 != expected_hash:
            raise ValueError("schema-8 artifact_sha256 does not match canonical accepted content")
        material_fact_pairs(self.material_facts)
        return self


def _option_information(
    hidden_design: ScenarioHiddenDesign,
    option_descriptions: List[OptionDescription],
    material_facts: List[MaterialFact] | List[_LegacyMaterialFact],
    specificity_elements: List[SpecificityElement],
) -> List[ScenarioOptionInformation]:
    """Convert authenticated flattened facts into canonical option records."""
    description_by_option = {description.option_id: description.description for description in option_descriptions}
    fact_by_coordinate = {(fact.option, fact.polarity): fact for fact in material_facts}
    markers_by_fact = {
        fact.fact_id: [element.canonical_value for element in specificity_elements if element.fact_id == fact.fact_id] for fact in material_facts
    }
    decision_option_by_seed_option = {
        hidden_design.owner_supporting_option: DecisionOption.OWNER_OPTION,
        alternative_seed_option(hidden_design.owner_supporting_option): DecisionOption.ALTERNATIVE_OPTION,
    }
    option_name_by_id = {option.option_id: option.option_name for option in hidden_design.options}

    def directional_fact(seed_option: SeedOptionId, polarity: FactPolarity) -> ScenarioFactInformation:
        """Build one nested fact while removing a legacy visible-title prefix."""
        fact = fact_by_coordinate[(decision_option_by_seed_option[seed_option], polarity)]
        prefix = f"{option_name_by_id[seed_option]}: "
        fact_text = fact.canonical_proposition
        if fact_text.startswith(prefix):
            fact_text = fact_text[len(prefix) :]
        return ScenarioFactInformation(
            fact_text=fact_text,
            specificity_markers=markers_by_fact[fact.fact_id],
        )

    return [
        ScenarioOptionInformation(
            option_id=option_id,
            description=description_by_option[option_id],
            favourable_fact=directional_fact(option_id, FactPolarity.BENEFIT),
            adverse_fact=directional_fact(option_id, FactPolarity.DOWNSIDE),
        )
        for option_id in hidden_design.presentation_order
    ]


def _candidate_from_flattened(
    previous: _LegacyCandidateScenario | _PreviousCandidateScenario | _SchemaEightCandidateScenario,
) -> CandidateScenario:
    """Convert one authenticated flattened candidate into schema 9."""
    excluded_fields = {
        "schema_version",
        "option_descriptions",
        "material_facts",
        "specificity_elements",
        "candidate_sha256",
        "fact_pairs",
    }
    current_payload = {
        "schema_version": "9.0.0",
        **previous.model_dump(mode="json", exclude=excluded_fields),
        "options": _option_information(
            previous.hidden_design,
            previous.option_descriptions,
            previous.material_facts,
            previous.specificity_elements,
        ),
    }
    return CandidateScenario.model_validate({**current_payload, "candidate_sha256": artifact_sha256(current_payload)})


def candidate_scenario_from_payload(payload: Dict[str, Any]) -> CandidateScenario:
    """Validate a current candidate or derive a hash-valid schema-9 view of schemas 6-8."""
    if payload.get("schema_version") == "6.0.0":
        return _candidate_from_flattened(_LegacyCandidateScenario.model_validate(payload))
    elif payload.get("schema_version") == "7.0.0":
        return _candidate_from_flattened(_PreviousCandidateScenario.model_validate(payload))
    elif payload.get("schema_version") == "8.0.0":
        return _candidate_from_flattened(_SchemaEightCandidateScenario.model_validate(payload))
    return CandidateScenario.model_validate(payload)


def read_candidate_scenario(path: Path) -> CandidateScenario:
    """Read a candidate file with authenticated schema-6 and schema-7 compatibility."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"candidate artifact must be a JSON object: {path}")
    return candidate_scenario_from_payload(payload)


def accepted_scenario_from_payload(payload: Dict[str, Any]) -> AcceptedScenario:
    """Validate a current accepted artifact or derive a schema-9 view of schemas 7-8."""
    if payload.get("schema_version") == "7.0.0":
        previous: _PreviousAcceptedScenario | _SchemaEightAcceptedScenario = _PreviousAcceptedScenario.model_validate(payload)
    elif payload.get("schema_version") == "8.0.0":
        previous = _SchemaEightAcceptedScenario.model_validate(payload)
    else:
        return AcceptedScenario.model_validate(payload)
    converted_payload = previous.model_dump(
        mode="json",
        exclude={"schema_version", "option_descriptions", "material_facts", "specificity_elements", "artifact_sha256"},
    )
    current_payload = {
        "schema_version": "9.0.0",
        **converted_payload,
        "options": _option_information(
            previous.hidden_design,
            previous.option_descriptions,
            previous.material_facts,
            previous.specificity_elements,
        ),
    }
    return AcceptedScenario.model_validate(
        {
            **current_payload,
            "artifact_sha256": artifact_sha256(current_payload),
        }
    )


def read_accepted_scenario(path: Path) -> AcceptedScenario:
    """Read an accepted artifact with authenticated flattened-schema compatibility."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"accepted scenario artifact must be a JSON object: {path}")
    return accepted_scenario_from_payload(payload)
