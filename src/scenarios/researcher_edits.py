"""Apply persisted researcher fact edits to revision and acceptance workflows."""

from __future__ import annotations

import json
from typing import List

from src.data_models.scenario_review import FindingSeverity, ResearcherFactReview, ReviewFinding
from src.data_models.scenarios import (
    CandidateScenario,
    DecisionOption,
    FactPolarity,
    ScenarioFactInformation,
    ScenarioOptionInformation,
    alternative_seed_option,
    scenario_fact_items,
)


def apply_researcher_fact_reviews(
    candidate: CandidateScenario,
    fact_reviews: List[ResearcherFactReview],
) -> List[ScenarioOptionInformation]:
    """Return canonical option records with researcher fact and marker edits applied."""
    review_by_id = {fact_review.fact_id: fact_review for fact_review in fact_reviews}
    fact_items = scenario_fact_items(candidate)
    expected_ids = {coordinate.fact_id for coordinate, _ in fact_items}
    if set(review_by_id) != expected_ids:
        raise ValueError("researcher fact reviews must cover every candidate material fact exactly once")
    fact_by_coordinate = {(coordinate.option, coordinate.polarity): (coordinate, information) for coordinate, information in fact_items}
    decision_option_by_seed_option = {
        candidate.hidden_design.owner_supporting_option: DecisionOption.OWNER_OPTION,
        alternative_seed_option(candidate.hidden_design.owner_supporting_option): DecisionOption.ALTERNATIVE_OPTION,
    }

    def reviewed_fact(option: DecisionOption, polarity: FactPolarity) -> ScenarioFactInformation:
        """Build one canonical nested fact from its stable researcher review."""
        coordinate, _ = fact_by_coordinate[(option, polarity)]
        review = review_by_id[coordinate.fact_id]
        return ScenarioFactInformation(
            fact_text=review.fact_text,
            specificity_markers=review.specificity_markers,
        )

    return [
        ScenarioOptionInformation(
            option_id=option.option_id,
            description=option.description,
            favourable_fact=reviewed_fact(decision_option_by_seed_option[option.option_id], FactPolarity.BENEFIT),
            adverse_fact=reviewed_fact(decision_option_by_seed_option[option.option_id], FactPolarity.DOWNSIDE),
        )
        for option in candidate.options
    ]


def researcher_revision_findings(
    candidate: CandidateScenario,
    fact_reviews: List[ResearcherFactReview],
) -> List[ReviewFinding]:
    """Translate noted or edited facts into exact parent-linked regeneration findings."""
    original_fact_by_id = {coordinate.fact_id: information for coordinate, information in scenario_fact_items(candidate)}
    findings: List[ReviewFinding] = []
    for fact_review in fact_reviews:
        original_fact = original_fact_by_id.get(fact_review.fact_id)
        if original_fact is None:
            raise ValueError(f"researcher fact review refers to an unknown material fact: {fact_review.fact_id}")
        instructions = [fact_review.notes] if fact_review.notes else []
        if fact_review.fact_text != original_fact.fact_text:
            instructions.append(f"Use this researcher-edited fact text: {fact_review.fact_text}")
        if fact_review.specificity_markers != original_fact.specificity_markers:
            instructions.append("Use these researcher-edited specificity markers: " + json.dumps(fact_review.specificity_markers, ensure_ascii=False))
        if not instructions:
            continue
        findings.append(
            ReviewFinding(
                severity=FindingSeverity.MAJOR,
                fact_text=original_fact.fact_text,
                suggested_action="\n".join(instructions),
            )
        )
    return findings
