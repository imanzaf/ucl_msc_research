"""Apply persisted researcher fact edits to revision and acceptance workflows."""

from __future__ import annotations

import json
from typing import Dict, List

from src.data_models.scenario_review import FindingSeverity, ResearcherFactReview, ReviewFinding
from src.data_models.scenarios import CandidateScenario, MaterialFact, SpecificityElement


def apply_researcher_fact_reviews(
    candidate: CandidateScenario,
    fact_reviews: List[ResearcherFactReview],
) -> List[MaterialFact]:
    """Return candidate material facts with researcher-edited text applied."""
    review_by_id = {fact_review.fact_id: fact_review for fact_review in fact_reviews}
    expected_ids = {fact.fact_id for fact in candidate.material_facts}
    if set(review_by_id) != expected_ids:
        raise ValueError("researcher fact reviews must cover every candidate material fact exactly once")
    return [
        MaterialFact.model_validate(
            {
                **fact.model_dump(mode="json"),
                "canonical_proposition": review_by_id[fact.fact_id].fact_text,
            }
        )
        for fact in candidate.material_facts
    ]


def specificity_elements_from_fact_reviews(fact_reviews: List[ResearcherFactReview]) -> List[SpecificityElement]:
    """Build stable specificity elements from the researcher-edited marker lists."""
    return [
        SpecificityElement(
            element_id=f"{fact_review.fact_id}_S{index}",
            fact_id=fact_review.fact_id,
            canonical_value=marker,
        )
        for fact_review in fact_reviews
        for index, marker in enumerate(fact_review.specificity_markers, start=1)
    ]


def researcher_revision_findings(
    candidate: CandidateScenario,
    fact_reviews: List[ResearcherFactReview],
) -> List[ReviewFinding]:
    """Translate noted or edited facts into exact parent-linked regeneration findings."""
    original_fact_by_id = {fact.fact_id: fact for fact in candidate.material_facts}
    original_markers_by_fact: Dict[str, List[str]] = {
        fact_id: [element.canonical_value for element in candidate.specificity_elements if element.fact_id == fact_id]
        for fact_id in original_fact_by_id
    }
    findings: List[ReviewFinding] = []
    for fact_review in fact_reviews:
        original_fact = original_fact_by_id.get(fact_review.fact_id)
        if original_fact is None:
            raise ValueError(f"researcher fact review refers to an unknown material fact: {fact_review.fact_id}")
        instructions = [fact_review.notes] if fact_review.notes else []
        if fact_review.fact_text != original_fact.canonical_proposition:
            instructions.append(f"Use this researcher-edited fact text: {fact_review.fact_text}")
        if fact_review.specificity_markers != original_markers_by_fact[fact_review.fact_id]:
            instructions.append("Use these researcher-edited specificity markers: " + json.dumps(fact_review.specificity_markers, ensure_ascii=False))
        if not instructions:
            continue
        findings.append(
            ReviewFinding(
                severity=FindingSeverity.MAJOR,
                fact_text=original_fact.canonical_proposition,
                suggested_action="\n".join(instructions),
            )
        )
    return findings
