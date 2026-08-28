"""Accepted-scenario models for the six-fact matched-pair corpus."""

from __future__ import annotations

from typing import List, Optional

from pydantic import Field, model_validator

from src.common import ImmutableModel
from src.models.enums import CustomerValence, FactDirection, OwnershipEligibility, ReviewState
from src.models.seeds import DeploymentContext


class ScenarioOption(ImmutableModel):
    """Store a named fictional option visible to evaluated models."""

    option_id: str = Field(pattern=r"^OPTION_[AB]$")
    institution_name: str = Field(min_length=2)
    product_name: str = Field(min_length=2)


class ScenarioFact(ImmutableModel):
    """Store one visible fact and its hidden matched-pair metadata."""

    fact_id: str = Field(pattern=r"^[A-Z0-9_]+_F[1-6]$")
    pair_id: str = Field(pattern=r"^[A-Z0-9_]+_P[1-3]$")
    option_id: str = Field(pattern=r"^OPTION_[AB]$")
    text: str = Field(min_length=3)
    anchor: str = Field(min_length=1)
    direction: FactDirection
    customer_valence: CustomerValence
    institutional_benefit: str = Field(min_length=2)
    materiality: str = Field(min_length=2)
    rationale: str = Field(min_length=2)

    @model_validator(mode="after")
    def validate_atomic_anchor(self) -> "ScenarioFact":
        """Require the one declared specificity anchor to occur in the visible fact."""
        if self.anchor not in self.text:
            raise ValueError("specificity anchor must occur verbatim in the visible fact")
        if " and " in self.anchor.lower() or " plus " in self.anchor.lower() or ";" in self.anchor:
            raise ValueError("specificity anchor must be atomic")
        prohibited = ("our product", "competitor", "preferred option")
        if any(phrase in self.text.lower() for phrase in prohibited):
            raise ValueError("visible facts must use named fictional institutions and neutral option wording")
        return self


class ScenarioReview(ImmutableModel):
    """Record the one researcher accept-or-revise disposition."""

    state: ReviewState = ReviewState.PENDING
    researcher_id: Optional[str] = None
    rationale: Optional[str] = None
    reviewed_at: Optional[str] = None

    @model_validator(mode="after")
    def validate_completed_review(self) -> "ScenarioReview":
        """Require reviewer metadata only for completed dispositions."""
        completed = self.state in {ReviewState.ACCEPTED, ReviewState.REVISE}
        if completed and (not self.researcher_id or not self.rationale or not self.reviewed_at):
            raise ValueError("completed review requires researcher, rationale, and timestamp")
        if not completed and any((self.researcher_id, self.rationale, self.reviewed_at)):
            raise ValueError("pending review cannot contain completed-review metadata")
        return self


class AcceptedScenario(ImmutableModel):
    """Represent one final accepted scenario with exactly three fact pairs."""

    schema_version: str = Field(default="10.0.0", pattern=r"^10\.0\.0$")
    scenario_id: str = Field(pattern=r"^[A-Z]{2,3}[0-9]{3}_R[1-5]$")
    generation_request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    generated_output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    domain: str = Field(min_length=2)
    deployment_context: DeploymentContext
    decision_context: str = Field(min_length=2)
    query_stem: str = Field(min_length=2)
    options: List[ScenarioOption] = Field(min_length=2, max_length=2)
    facts: List[ScenarioFact] = Field(min_length=6, max_length=6)
    owner_supporting_option: str = Field(pattern=r"^OPTION_[AB]$")
    ownership_eligibility: OwnershipEligibility
    presentation_order: List[str] = Field(min_length=2, max_length=2)
    review: ScenarioReview = Field(default_factory=ScenarioReview)

    @model_validator(mode="after")
    def validate_design(self) -> "AcceptedScenario":
        """Enforce the per-scenario six-fact, pair, direction, and option invariants."""
        option_ids = {option.option_id for option in self.options}
        if option_ids != {"OPTION_A", "OPTION_B"} or set(self.presentation_order) != option_ids:
            raise ValueError("scenario must define and order OPTION_A and OPTION_B exactly once")
        if any(fact.option_id not in option_ids for fact in self.facts):
            raise ValueError("every fact must refer to a defined option")
        if len({fact.fact_id for fact in self.facts}) != 6:
            raise ValueError("fact identifiers must be unique")
        if {fact.fact_id for fact in self.facts} != {f"{self.scenario_id}_F{number}" for number in range(1, 7)}:
            raise ValueError("fact identifiers must form the scenario-specific F1--F6 set")
        pair_ids = {fact.pair_id for fact in self.facts}
        if pair_ids != {f"{self.scenario_id}_P{number}" for number in range(1, 4)}:
            raise ValueError("scenario must contain its scenario-specific P1--P3 fact pairs")
        for pair_id in pair_ids:
            pair = [fact for fact in self.facts if fact.pair_id == pair_id]
            if len(pair) != 2 or {fact.option_id for fact in pair} != option_ids:
                raise ValueError("each fact pair must contain one fact for each option")
            if len({fact.customer_valence for fact in pair}) != 1:
                raise ValueError("facts within a pair must have the same customer valence")
            if {fact.direction for fact in pair} != {FactDirection.OWNER_SUPPORTING, FactDirection.COUNTERVAILING}:
                raise ValueError("each fact pair must contain one fact in each hidden direction")
        if any(sum(fact.option_id == option_id for fact in self.facts) != 3 for option_id in option_ids):
            raise ValueError("each option must have exactly three facts")
        directions = [fact.direction for fact in self.facts]
        if directions.count(FactDirection.OWNER_SUPPORTING) != 3 or directions.count(FactDirection.COUNTERVAILING) != 3:
            raise ValueError("scenario must contain three owner-supporting and three countervailing facts")
        return self
