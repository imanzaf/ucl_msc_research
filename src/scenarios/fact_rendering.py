"""Render the four accepted material facts as the evaluated assistant's input."""

from __future__ import annotations

from typing import Dict, List

from src.data_models.common import sha256_bytes
from src.data_models.scenarios import (
    AcceptedScenario,
    CandidateScenario,
    DecisionOption,
    FactPolarity,
    MaterialFact,
    ScenarioHiddenDesign,
    SeedOptionId,
    alternative_seed_option,
)


def _decision_option_by_seed_option(design: ScenarioHiddenDesign) -> Dict[SeedOptionId, DecisionOption]:
    """Map neutral seed option IDs to the artifact's hidden decision coordinates."""
    return {
        design.owner_supporting_option: DecisionOption.OWNER_OPTION,
        alternative_seed_option(design.owner_supporting_option): DecisionOption.ALTERNATIVE_OPTION,
    }


def ordered_visible_facts(scenario: CandidateScenario | AcceptedScenario) -> List[MaterialFact]:
    """Return the four facts in the frozen option order with counterbalanced polarity order."""
    if not isinstance(scenario.hidden_design, ScenarioHiddenDesign):
        raise ValueError("direct fact rendering requires a V2.0.0 hidden design")
    fact_by_cell = {(fact.option, fact.polarity): fact for fact in scenario.material_facts}
    option_mapping = _decision_option_by_seed_option(scenario.hidden_design)
    benefit_first = int(sha256_bytes(f"fact-order-v1:{scenario.scenario_id}".encode("utf-8"))[:2], 16) % 2 == 0
    polarity_order = [FactPolarity.BENEFIT, FactPolarity.DOWNSIDE]
    if not benefit_first:
        polarity_order.reverse()
    facts: List[MaterialFact] = []
    for seed_option in scenario.hidden_design.presentation_order:
        decision_option = option_mapping[seed_option]
        facts.extend(fact_by_cell[(decision_option, polarity)] for polarity in polarity_order)
        polarity_order.reverse()
    return facts


def render_visible_facts(scenario: CandidateScenario | AcceptedScenario) -> str:
    """Render the exact four facts as an unlabelled bullet list."""
    return "\n".join(f"- {fact.canonical_proposition}" for fact in ordered_visible_facts(scenario))


def visible_facts_sha256(scenario: CandidateScenario | AcceptedScenario) -> str:
    """Hash the exact fact-list bytes shown to the evaluated assistant."""
    return sha256_bytes(render_visible_facts(scenario).encode("utf-8"))
