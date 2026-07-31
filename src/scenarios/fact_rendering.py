"""Render the four accepted material facts as the evaluated assistant's input."""

from __future__ import annotations

from typing import Dict, List, Tuple

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


def material_facts_without_option_prefix(scenario: CandidateScenario | AcceptedScenario) -> List[MaterialFact]:
    """Return material facts with any legacy backend-added option prefix removed."""
    if not isinstance(scenario.hidden_design, ScenarioHiddenDesign):
        raise ValueError("direct fact rendering requires a V2.0.0 hidden design")
    option_name_by_seed_option = {option.option_id: option.option_name for option in scenario.hidden_design.options}
    decision_option_by_seed_option = _decision_option_by_seed_option(scenario.hidden_design)
    option_name_by_decision_option = {
        decision_option_by_seed_option[seed_option]: option_name for seed_option, option_name in option_name_by_seed_option.items()
    }
    normalised_facts = []
    for fact in scenario.material_facts:
        prefix = f"{option_name_by_decision_option[fact.option]}: "
        proposition = fact.canonical_proposition
        if proposition.startswith(prefix):
            proposition = proposition[len(prefix) :]
        normalised_facts.append(fact.model_copy(update={"canonical_proposition": proposition}))
    return normalised_facts


def ordered_visible_fact_groups(
    scenario: CandidateScenario | AcceptedScenario,
) -> List[Tuple[str, List[MaterialFact]]]:
    """Return option-labelled fact groups in the frozen and counterbalanced order."""
    if not isinstance(scenario.hidden_design, ScenarioHiddenDesign):
        raise ValueError("direct fact rendering requires a V2.0.0 hidden design")
    option_name_by_id = {option.option_id: option.option_name for option in scenario.hidden_design.options}
    normalised_facts = material_facts_without_option_prefix(scenario)
    fact_by_cell = {(fact.option, fact.polarity): fact for fact in normalised_facts}
    option_mapping = _decision_option_by_seed_option(scenario.hidden_design)
    benefit_first = int(sha256_bytes(f"fact-order-v1:{scenario.scenario_id}".encode("utf-8"))[:2], 16) % 2 == 0
    polarity_order = [FactPolarity.BENEFIT, FactPolarity.DOWNSIDE]
    if not benefit_first:
        polarity_order.reverse()
    groups: List[Tuple[str, List[MaterialFact]]] = []
    for seed_option in scenario.hidden_design.presentation_order:
        decision_option = option_mapping[seed_option]
        groups.append(
            (
                option_name_by_id[seed_option],
                [fact_by_cell[(decision_option, polarity)] for polarity in polarity_order],
            )
        )
        polarity_order.reverse()
    return groups


def ordered_visible_facts(scenario: CandidateScenario | AcceptedScenario) -> List[MaterialFact]:
    """Return the four plain facts in their grouped evaluated-prompt order."""
    return [fact for _, facts in ordered_visible_fact_groups(scenario) for fact in facts]


def render_visible_facts(scenario: CandidateScenario | AcceptedScenario) -> str:
    """Render the exact four facts beneath their human-readable option headings."""
    return "\n\n".join(
        "\n".join([f"### {option_name}", *(f"- {fact.canonical_proposition}" for fact in facts)])
        for option_name, facts in ordered_visible_fact_groups(scenario)
    )


def visible_facts_sha256(scenario: CandidateScenario | AcceptedScenario) -> str:
    """Hash the exact fact-list bytes shown to the evaluated assistant."""
    return sha256_bytes(render_visible_facts(scenario).encode("utf-8"))
