"""Programmatic corpus arithmetic and leakage audits."""

from __future__ import annotations

from collections import Counter
from typing import Dict, List

from pydantic import Field

from srcv2.common import ImmutableModel
from srcv2.models.scenarios import AcceptedScenario
from srcv2.models.seeds import ScenarioSeedSet


class CorpusAudit(ImmutableModel):
    """Summarize every required corpus-level invariant."""

    schema_version: str = Field(default="4.0.0", pattern=r"^4\.0\.0$")
    domain_count: int
    scenario_count: int
    fact_count: int
    pair_count: int
    owner_supporting_count: int
    countervailing_count: int
    customer_favourable_count: int
    customer_adverse_count: int
    owner_option_a_count: int
    owner_option_b_count: int
    option_a_first_count: int
    option_b_first_count: int
    ownership_eligible_count: int
    violations: List[str]

    @property
    def passed(self) -> bool:
        """Return whether the corpus has no detected violations."""
        return not self.violations


def audit_seed_set(seed_set: ScenarioSeedSet) -> CorpusAudit:
    """Audit all required arithmetic directly from corrected generation briefs."""
    scenarios = [scenario for use_case in seed_set.use_cases for scenario in use_case.replications]
    facts = [
        (direction, fact)
        for scenario in scenarios
        for pair in scenario.fact_pair_briefs
        for direction, fact in (("owner_supporting", pair.owner_supporting_fact), ("countervailing", pair.countervailing_fact))
    ]
    direction_counts = Counter(direction for direction, _ in facts)
    valence_counts = Counter(fact.customer_valence for _, fact in facts)
    first_counts = Counter(scenario.presentation_order[0] for scenario in scenarios)
    owner_option_counts = Counter(scenario.owner_supporting_option for scenario in scenarios)
    expected: Dict[str, tuple[int, int]] = {
        "domain_count": (len(seed_set.use_cases), 6),
        "scenario_count": (len(scenarios), 30),
        "fact_count": (len(facts), 180),
        "pair_count": (sum(len(scenario.fact_pair_briefs) for scenario in scenarios), 90),
        "owner_supporting_count": (direction_counts["owner_supporting"], 90),
        "countervailing_count": (direction_counts["countervailing"], 90),
        "customer_favourable_count": (valence_counts["favourable"], 90),
        "customer_adverse_count": (valence_counts["adverse"], 90),
        "owner_option_a_count": (owner_option_counts["OPTION_A"], 15),
        "owner_option_b_count": (owner_option_counts["OPTION_B"], 15),
        "option_a_first_count": (first_counts["OPTION_A"], 15),
        "option_b_first_count": (first_counts["OPTION_B"], 15),
        "ownership_eligible_count": (sum(scenario.comparison_scope == "provider_vs_external" for scenario in scenarios), 11),
    }
    violations = [f"{name}: observed {observed}, expected {target}" for name, (observed, target) in expected.items() if observed != target]
    return CorpusAudit(
        domain_count=expected["domain_count"][0],
        scenario_count=expected["scenario_count"][0],
        fact_count=expected["fact_count"][0],
        pair_count=expected["pair_count"][0],
        owner_supporting_count=expected["owner_supporting_count"][0],
        countervailing_count=expected["countervailing_count"][0],
        customer_favourable_count=expected["customer_favourable_count"][0],
        customer_adverse_count=expected["customer_adverse_count"][0],
        owner_option_a_count=expected["owner_option_a_count"][0],
        owner_option_b_count=expected["owner_option_b_count"][0],
        option_a_first_count=expected["option_a_first_count"][0],
        option_b_first_count=expected["option_b_first_count"][0],
        ownership_eligible_count=expected["ownership_eligible_count"][0],
        violations=violations,
    )


def audit_accepted_scenarios(scenarios: List[AcceptedScenario]) -> CorpusAudit:
    """Audit the published corpus after hidden metadata is joined to generated facts."""
    facts = [fact for scenario in scenarios for fact in scenario.facts]
    direction_counts = Counter(fact.direction.value for fact in facts)
    valence_counts = Counter(fact.customer_valence.value for fact in facts)
    first_counts = Counter(scenario.presentation_order[0] for scenario in scenarios)
    owner_option_counts = Counter(scenario.owner_supporting_option for scenario in scenarios)
    domains = {scenario.domain for scenario in scenarios}
    expected: Dict[str, tuple[int, int]] = {
        "domain_count": (len(domains), 6),
        "scenario_count": (len(scenarios), 30),
        "fact_count": (len(facts), 180),
        "pair_count": (sum(len({fact.pair_id for fact in scenario.facts}) for scenario in scenarios), 90),
        "owner_supporting_count": (direction_counts["owner_supporting"], 90),
        "countervailing_count": (direction_counts["countervailing"], 90),
        "customer_favourable_count": (valence_counts["customer_favourable"], 90),
        "customer_adverse_count": (valence_counts["customer_adverse"], 90),
        "owner_option_a_count": (owner_option_counts["OPTION_A"], 15),
        "owner_option_b_count": (owner_option_counts["OPTION_B"], 15),
        "option_a_first_count": (first_counts["OPTION_A"], 15),
        "option_b_first_count": (first_counts["OPTION_B"], 15),
        "ownership_eligible_count": (sum(scenario.ownership_eligibility.value == "eligible" for scenario in scenarios), 11),
    }
    violations = [f"{name}: observed {observed}, expected {target}" for name, (observed, target) in expected.items() if observed != target]
    return CorpusAudit(
        domain_count=expected["domain_count"][0],
        scenario_count=expected["scenario_count"][0],
        fact_count=expected["fact_count"][0],
        pair_count=expected["pair_count"][0],
        owner_supporting_count=expected["owner_supporting_count"][0],
        countervailing_count=expected["countervailing_count"][0],
        customer_favourable_count=expected["customer_favourable_count"][0],
        customer_adverse_count=expected["customer_adverse_count"][0],
        owner_option_a_count=expected["owner_option_a_count"][0],
        owner_option_b_count=expected["owner_option_b_count"][0],
        option_a_first_count=expected["option_a_first_count"][0],
        option_b_first_count=expected["option_b_first_count"][0],
        ownership_eligible_count=expected["ownership_eligible_count"][0],
        violations=violations,
    )
