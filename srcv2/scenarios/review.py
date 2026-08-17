"""Single-pass researcher review and accepted-corpus publication."""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import Field, model_validator

from srcv2.common import ImmutableModel, utc_now
from srcv2.models.enums import ReviewState
from srcv2.models.scenarios import AcceptedScenario, ScenarioReview


class ResearcherReviewRecord(ImmutableModel):
    """Record exactly one accept-or-revise disposition for a generated scenario."""

    schema_version: str = Field(default="4.0.0", pattern=r"^4\.0\.0$")
    scenario_id: str
    generation_request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    generated_output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    disposition: Literal[ReviewState.ACCEPTED, ReviewState.REVISE]
    researcher_id: str
    rationale: str
    reviewed_at: datetime
    revision_instructions: Optional[str] = None

    @model_validator(mode="after")
    def validate_revision(self) -> "ResearcherReviewRecord":
        """Require revision instructions only when the scenario needs revision."""
        if self.disposition == ReviewState.REVISE and not self.revision_instructions:
            raise ValueError("revise disposition requires revision instructions")
        if self.disposition == ReviewState.ACCEPTED and self.revision_instructions is not None:
            raise ValueError("accepted disposition cannot include revision instructions")
        return self


def accept_curated_scenarios(
    scenarios: List[AcceptedScenario],
    researcher_id: str,
    rationale: str,
    reviewed_at: Optional[datetime] = None,
) -> List[ResearcherReviewRecord]:
    """Create one accepted, hash-bound researcher disposition per curated scenario."""
    if len(scenarios) != 30 or len({scenario.scenario_id for scenario in scenarios}) != 30:
        raise ValueError("corpus acceptance requires thirty unique scenarios")
    if any(scenario.review.state != ReviewState.PENDING for scenario in scenarios):
        raise ValueError("corpus acceptance requires pending scenarios")
    timestamp = reviewed_at or utc_now()
    return [
        ResearcherReviewRecord(
            scenario_id=scenario.scenario_id,
            generation_request_sha256=scenario.generation_request_sha256,
            generated_output_sha256=scenario.generated_output_sha256,
            disposition=ReviewState.ACCEPTED,
            researcher_id=researcher_id,
            rationale=rationale,
            reviewed_at=timestamp,
        )
        for scenario in scenarios
    ]


def publish_scenarios(scenarios: List[AcceptedScenario], reviews: List[ResearcherReviewRecord]) -> List[AcceptedScenario]:
    """Return the corpus only when every scenario has one accepted review."""
    scenario_ids = [scenario.scenario_id for scenario in scenarios]
    review_ids = [review.scenario_id for review in reviews]
    if len(set(scenario_ids)) != len(scenarios):
        raise ValueError("scenario identifiers must be unique before publication")
    if sorted(review_ids) != sorted(scenario_ids) or len(set(review_ids)) != len(reviews):
        raise ValueError("each scenario must have exactly one accepted researcher review")
    by_scenario = {review.scenario_id: review for review in reviews}
    if any(review.disposition != ReviewState.ACCEPTED for review in reviews):
        raise ValueError("revised scenarios cannot be published until their corrected output is accepted")
    if any(scenario.review.state != ReviewState.PENDING for scenario in scenarios):
        raise ValueError("only pending scenarios can enter the one-pass publication review")
    if any(
        by_scenario[scenario.scenario_id].generation_request_sha256 != scenario.generation_request_sha256
        or by_scenario[scenario.scenario_id].generated_output_sha256 != scenario.generated_output_sha256
        for scenario in scenarios
    ):
        raise ValueError("researcher reviews must bind the exact generation request and semantic output")
    return [
        AcceptedScenario.model_validate(
            {
                **scenario.model_dump(mode="json", exclude={"review"}),
                "review": ScenarioReview(
                    state=ReviewState.ACCEPTED,
                    researcher_id=by_scenario[scenario.scenario_id].researcher_id,
                    rationale=by_scenario[scenario.scenario_id].rationale,
                    reviewed_at=by_scenario[scenario.scenario_id].reviewed_at.isoformat(),
                ),
            }
        )
        for scenario in scenarios
    ]
