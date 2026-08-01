"""Render the four accepted material facts as the evaluated assistant's input."""

from __future__ import annotations

from typing import List, Tuple

from src.data_models.common import sha256_bytes
from src.data_models.scenarios import AcceptedScenario, CandidateScenario, FactPolarity, ScenarioFactInformation, ScenarioHiddenDesign


def ordered_visible_fact_groups(
    scenario: CandidateScenario | AcceptedScenario,
) -> List[Tuple[str, List[ScenarioFactInformation]]]:
    """Return option-labelled fact groups in the frozen and counterbalanced order."""
    if not isinstance(scenario.hidden_design, ScenarioHiddenDesign):
        raise ValueError("direct fact rendering requires a V2.0.0 hidden design")
    option_name_by_id = {option.option_id: option.option_name for option in scenario.hidden_design.options}
    option_information_by_id = {option.option_id: option for option in scenario.options}
    benefit_first = int(sha256_bytes(f"fact-order-v1:{scenario.scenario_id}".encode("utf-8"))[:2], 16) % 2 == 0
    polarity_order = [FactPolarity.BENEFIT, FactPolarity.DOWNSIDE]
    if not benefit_first:
        polarity_order.reverse()
    groups: List[Tuple[str, List[ScenarioFactInformation]]] = []
    for seed_option in scenario.hidden_design.presentation_order:
        option_information = option_information_by_id[seed_option]
        fact_by_polarity = {
            FactPolarity.BENEFIT: option_information.favourable_fact,
            FactPolarity.DOWNSIDE: option_information.adverse_fact,
        }
        groups.append(
            (
                option_name_by_id[seed_option],
                [fact_by_polarity[polarity] for polarity in polarity_order],
            )
        )
        polarity_order.reverse()
    return groups


def ordered_visible_facts(scenario: CandidateScenario | AcceptedScenario) -> List[ScenarioFactInformation]:
    """Return the four plain facts in their grouped evaluated-prompt order."""
    return [fact for _, facts in ordered_visible_fact_groups(scenario) for fact in facts]


def render_visible_facts(scenario: CandidateScenario | AcceptedScenario) -> str:
    """Render the exact four facts beneath their human-readable option headings."""
    return "\n\n".join(
        "\n".join([f"### {option_name}", *(f"- {fact.fact_text}" for fact in facts)]) for option_name, facts in ordered_visible_fact_groups(scenario)
    )


def visible_facts_sha256(scenario: CandidateScenario | AcceptedScenario) -> str:
    """Hash the exact fact-list bytes shown to the evaluated assistant."""
    return sha256_bytes(render_visible_facts(scenario).encode("utf-8"))
