"""Direction-blind extractor request construction and hidden-metadata joining."""

from __future__ import annotations

from typing import List

from srcv2.models.scenarios import ScenarioFact
from srcv2.models.scoring import FactExtraction, FactExtractionRequest, ScoredFact


def extraction_request(response_text: str, fact: ScenarioFact) -> FactExtractionRequest:
    """Build the minimal direction-blind input for one candidate fact."""
    return FactExtractionRequest(response_text=response_text, candidate_fact_text=fact.text, anchor=fact.anchor)


def join_hidden_metadata(facts: List[ScenarioFact], extractions: List[FactExtraction]) -> List[ScoredFact]:
    """Join direction, pair, and option metadata only after all extractions are frozen."""
    if len(facts) != len(extractions):
        raise ValueError("each candidate fact requires exactly one frozen extraction")
    return [
        ScoredFact(
            fact_id=fact.fact_id,
            pair_id=fact.pair_id,
            option_id=fact.option_id,
            direction=fact.direction,
            fact_present=extraction.fact_present,
            anchor_present=extraction.anchor_present,
            first_character_offset=extraction.first_character_offset,
        )
        for fact, extraction in zip(facts, extractions)
    ]
