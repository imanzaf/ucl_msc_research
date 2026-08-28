"""Typed import models for the supplied six-domain scenario seed package."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import Field, model_validator

from src.common import ImmutableModel


class SeedOption(ImmutableModel):
    """Represent one fictional option in a scenario seed."""

    option_id: Literal["OPTION_A", "OPTION_B"]
    company_name: str
    option_name: str


class SeedFactBrief(ImmutableModel):
    """Represent one directional fact-generation brief and one atomic anchor."""

    option_id: Literal["OPTION_A", "OPTION_B"]
    customer_valence: Literal["favourable", "adverse"]
    brief: str
    required_specificity: str

    @model_validator(mode="after")
    def validate_atomic_specificity(self) -> "SeedFactBrief":
        """Reject bundled required-specificity declarations."""
        anchor = self.required_specificity.lower()
        if " and " in anchor or " plus " in anchor or ";" in anchor:
            raise ValueError("required specificity must declare exactly one atomic anchor")
        return self


class SeedFactPair(ImmutableModel):
    """Represent one same-valence pair with one fact for each option."""

    pair_id: Literal["P1", "P2", "P3"]
    pair_type: Literal["benefit", "drawback"]
    dimension: str
    owner_supporting_fact: SeedFactBrief
    countervailing_fact: SeedFactBrief
    matching_requirement: str

    @model_validator(mode="after")
    def validate_pair(self) -> "SeedFactPair":
        """Enforce one option per side and matched customer valence."""
        if self.owner_supporting_fact.option_id == self.countervailing_fact.option_id:
            raise ValueError("paired briefs must cover different options")
        if self.owner_supporting_fact.customer_valence != self.countervailing_fact.customer_valence:
            raise ValueError("paired briefs must have the same customer valence")
        return self


class ScenarioSeed(ImmutableModel):
    """Represent one scenario-generation seed in the final corpus."""

    scenario_id: str = Field(pattern=r"^[A-Z]{2,3}[0-9]{3}_R[1-5]$")
    study_stage: Literal["evaluation"]
    decision_type: str
    decision_context: str
    customer_query_stem: str
    options: List[SeedOption] = Field(min_length=2, max_length=2)
    owner_supporting_option: Literal["OPTION_A", "OPTION_B"]
    owner_benefit_type: str
    owner_benefit_mechanism: str
    comparison_scope: Literal["provider_vs_external", "intra_provider"]
    external_option_id: Optional[Literal["OPTION_A", "OPTION_B"]]
    presentation_order: List[Literal["OPTION_A", "OPTION_B"]] = Field(min_length=2, max_length=2)
    mutual_exclusivity_rationale: str
    materiality_rationale: str
    fact_pair_briefs: List[SeedFactPair] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def validate_seed(self) -> "ScenarioSeed":
        """Enforce identifiers, directions, scope, and the six-brief structure."""
        if {option.option_id for option in self.options} != {"OPTION_A", "OPTION_B"}:
            raise ValueError("seed must define OPTION_A and OPTION_B")
        if set(self.presentation_order) != {"OPTION_A", "OPTION_B"}:
            raise ValueError("presentation order must contain each option exactly once")
        if {pair.pair_id for pair in self.fact_pair_briefs} != {"P1", "P2", "P3"}:
            raise ValueError("seed must define P1, P2, and P3")
        if self.comparison_scope == "provider_vs_external" and self.external_option_id is None:
            raise ValueError("external comparison requires an external option")
        if self.comparison_scope == "intra_provider" and self.external_option_id is not None:
            raise ValueError("intra-provider comparison cannot declare an external option")
        return self


class DeploymentContext(ImmutableModel):
    """Describe the seed-owned role, task, and authority shown to evaluated models."""

    role: str
    entity_name: str
    entity_type: str
    task: str
    authority_limits: List[str]


class UseCaseSeed(ImmutableModel):
    """Group five scenario replications within one financial domain."""

    use_case_id: str = Field(pattern=r"^[A-Z]{2,3}[0-9]{3}$")
    use_case_name: str
    deployment_context: DeploymentContext
    replications: List[ScenarioSeed] = Field(min_length=5, max_length=5)


class ScenarioSeedSet(ImmutableModel):
    """Represent the corrected six-domain, thirty-scenario generation seed set."""

    schema_version: str = Field(default="4.0.1", pattern=r"^4\.0\.1$")
    scenario_set_id: str = Field(default="financial_risk_communication_scenarios_v4.0.1", pattern=r".*v4\.0\.1$")
    all_entities_fictional: bool
    fictional_entity_notice: str
    notice: str
    design_defaults: dict[str, object]
    use_cases: List[UseCaseSeed] = Field(min_length=6, max_length=6)

    @model_validator(mode="after")
    def validate_corpus(self) -> "ScenarioSeedSet":
        """Enforce all global corpus balances before generation."""
        scenarios = [scenario for use_case in self.use_cases for scenario in use_case.replications]
        if len(scenarios) != 30 or len({scenario.scenario_id for scenario in scenarios}) != 30:
            raise ValueError("seed set must contain thirty unique scenarios")
        if not self.all_entities_fictional:
            raise ValueError("all institutions must be explicitly fictional")
        owner_options = [scenario.owner_supporting_option for scenario in scenarios]
        if owner_options.count("OPTION_A") != 15 or owner_options.count("OPTION_B") != 15:
            raise ValueError("owner-supporting option must be balanced 15/15")
        first_options = [scenario.presentation_order[0] for scenario in scenarios]
        if first_options.count("OPTION_A") != 15 or first_options.count("OPTION_B") != 15:
            raise ValueError("option presentation order must be balanced 15/15")
        if sum(scenario.comparison_scope == "provider_vs_external" for scenario in scenarios) != 11:
            raise ValueError("exactly eleven scenarios must be ownership eligible")
        briefs = [
            fact for scenario in scenarios for pair in scenario.fact_pair_briefs for fact in (pair.owner_supporting_fact, pair.countervailing_fact)
        ]
        if len(briefs) != 180:
            raise ValueError("seed set must contain 180 fact briefs")
        valences = [fact.customer_valence for fact in briefs]
        if valences.count("favourable") != 90 or valences.count("adverse") != 90:
            raise ValueError("customer valence must be balanced 90/90")
        return self
