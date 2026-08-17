"""Shared final-protocol test fixtures."""

from __future__ import annotations

from typing import List, cast

import pytest

from srcv2.models.enums import CustomerValence, FactDirection, OwnershipEligibility
from srcv2.models.scenarios import AcceptedScenario, ScenarioFact, ScenarioOption
from srcv2.models.seeds import ScenarioSeedSet
from srcv2.paths import SCENARIO_ROOT
from srcv2.storage import read_json


@pytest.fixture(scope="session")
def seed_set() -> ScenarioSeedSet:
    """Load the active final-protocol seed set."""
    return ScenarioSeedSet.model_validate(read_json(SCENARIO_ROOT / "final_scenario_generation_seeds.json"))


@pytest.fixture()
def accepted_scenario(seed_set: ScenarioSeedSet) -> AcceptedScenario:
    """Build one valid accepted scenario from its corrected generation briefs."""
    use_case = seed_set.use_cases[0]
    seed = use_case.replications[0]
    facts: List[ScenarioFact] = []
    fact_number = 1
    for pair in seed.fact_pair_briefs:
        for direction, brief in (
            (FactDirection.OWNER_SUPPORTING, pair.owner_supporting_fact),
            (FactDirection.COUNTERVAILING, pair.countervailing_fact),
        ):
            facts.append(
                ScenarioFact(
                    fact_id=f"{seed.scenario_id}_F{fact_number}",
                    pair_id=f"{seed.scenario_id}_{pair.pair_id}",
                    option_id=brief.option_id,
                    text=f"{brief.required_specificity} applies to this fictional option.",
                    anchor=brief.required_specificity,
                    direction=direction,
                    customer_valence=(CustomerValence.FAVOURABLE if brief.customer_valence == "favourable" else CustomerValence.ADVERSE),
                    institutional_benefit=seed.owner_benefit_type,
                    materiality=seed.materiality_rationale,
                    rationale=pair.matching_requirement,
                )
            )
            fact_number += 1
    return AcceptedScenario(
        scenario_id=seed.scenario_id,
        generation_request_sha256="a" * 64,
        generated_output_sha256="b" * 64,
        domain=use_case.use_case_name,
        deployment_context=use_case.deployment_context,
        decision_context=seed.decision_context,
        query_stem=seed.customer_query_stem,
        options=[
            ScenarioOption(option_id=option.option_id, institution_name=option.company_name, product_name=option.option_name)
            for option in seed.options
        ],
        facts=facts,
        owner_supporting_option=seed.owner_supporting_option,
        ownership_eligibility=(OwnershipEligibility.ELIGIBLE if seed.comparison_scope == "provider_vs_external" else OwnershipEligibility.INELIGIBLE),
        presentation_order=cast(List[str], list(seed.presentation_order)),
    )
