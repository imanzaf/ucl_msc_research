"""Scenario corpus, query, generation, and review tests."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from src.models.enums import Affect, QueryLength, ReviewState
from src.models.queries import AuthoredQueryFamily, QueryVariant
from src.models.scenarios import AcceptedScenario
from src.models.seeds import ScenarioSeedSet
from src.paths import SCENARIO_ROOT
from src.scenarios.generation import (
    PROGRAMMATIC_ARITHMETIC_EXPECTATIONS,
    GeneratedFact,
    GeneratedScenarioOutput,
    assemble_pending_corpus,
    build_generation_requests,
)
from src.scenarios.queries import (
    apply_query_protocol,
    assigned_fact_order,
    build_query_protocol_approval,
    build_user_state_queries,
    validate_query_corpus,
    validate_query_family,
)
from src.scenarios.review import ResearcherReviewRecord, accept_curated_scenarios, publish_scenarios
from src.scenarios.validation import audit_accepted_scenarios, audit_seed_set
from src.storage import read_json, read_jsonl


def test_corrected_corpus_has_all_required_balances(seed_set: ScenarioSeedSet) -> None:
    """Validate six domains, thirty scenarios, 180 briefs, and every planned balance."""
    audit = audit_seed_set(seed_set)
    assert audit.passed
    assert audit.model_dump(exclude={"schema_version", "violations"}) == {
        "domain_count": 6,
        "scenario_count": 30,
        "fact_count": 180,
        "pair_count": 90,
        "owner_supporting_count": 90,
        "countervailing_count": 90,
        "customer_favourable_count": 90,
        "customer_adverse_count": 90,
        "owner_option_a_count": 15,
        "owner_option_b_count": 15,
        "option_a_first_count": 15,
        "option_b_first_count": 15,
        "ownership_eligible_count": 11,
    }


def test_every_fact_brief_has_one_atomic_anchor(seed_set: ScenarioSeedSet) -> None:
    """Reject bundled anchors across all 180 generation briefs."""
    anchors = [
        fact.required_specificity
        for use_case in seed_set.use_cases
        for scenario in use_case.replications
        for pair in scenario.fact_pair_briefs
        for fact in (pair.owner_supporting_fact, pair.countervailing_fact)
    ]
    assert len(anchors) == 180
    assert all(" and " not in anchor.lower() and " plus " not in anchor.lower() and ";" not in anchor for anchor in anchors)


def test_generation_is_exactly_once_per_scenario(seed_set: ScenarioSeedSet) -> None:
    """Build one unique immutable generation request per scenario."""
    requests = build_generation_requests(seed_set)
    assert len(requests) == 30
    assert len({request.scenario_id for request in requests}) == 30
    assert len({request.request_sha256 for request in requests}) == 30


def test_generated_outputs_join_hidden_metadata_and_pass_corpus_audit(seed_set: ScenarioSeedSet) -> None:
    """Assemble one strict visible output per seed before researcher review."""
    outputs = []
    for use_case in seed_set.use_cases:
        for seed in use_case.replications:
            facts = []
            fact_number = 1
            for pair in seed.fact_pair_briefs:
                for brief in (pair.owner_supporting_fact, pair.countervailing_fact):
                    institution = next(option.company_name for option in seed.options if option.option_id == brief.option_id)
                    fact_id = f"{seed.scenario_id}_F{fact_number}"
                    expected_amount = PROGRAMMATIC_ARITHMETIC_EXPECTATIONS.get(fact_id, "")
                    facts.append(
                        GeneratedFact(
                            fact_id=fact_id,
                            pair_id=f"{seed.scenario_id}_{pair.pair_id}",
                            option_id=brief.option_id,
                            text=f"At {institution}, the relevant term is {brief.required_specificity}. {expected_amount}",
                            anchor=brief.required_specificity,
                        )
                    )
                    fact_number += 1
            outputs.append(GeneratedScenarioOutput(scenario_id=seed.scenario_id, facts=facts))
    pending = assemble_pending_corpus(seed_set, outputs)
    audit = audit_accepted_scenarios(pending)
    assert len(pending) == 30
    assert audit.passed
    assert all(scenario.review.state == ReviewState.PENDING for scenario in pending)


def test_user_state_query_matrix_is_semantically_bounded() -> None:
    """Build six natural controlled queries without distrust or an assumed option count."""
    family = AuthoredQueryFamily.model_validate(read_jsonl(SCENARIO_ROOT / "query_families.jsonl")[0])
    queries = build_user_state_queries(family)
    assert len(queries) == 6
    assert Counter(query.affect for query in queries) == {affect: 2 for affect in Affect}
    frustrated = [query.text.lower() for query in queries if query.affect == Affect.FRUSTRATED]
    validate_query_family(family, queries)
    assert all("trust" not in text for text in frustrated)
    assert all("two options" not in query.text.lower() for query in queries)


def test_all_scenarios_have_six_unique_approved_queries() -> None:
    """Validate the complete 30-scenario, 180-query authored corpus."""
    scenarios = [AcceptedScenario.model_validate(record) for record in read_jsonl(SCENARIO_ROOT / "accepted_scenarios.jsonl")]
    families = [AuthoredQueryFamily.model_validate(record) for record in read_jsonl(SCENARIO_ROOT / "query_families.jsonl")]
    validate_query_corpus([scenario.scenario_id for scenario in scenarios], families)
    variants = [query for family in families for query in build_user_state_queries(family)]
    assert len(variants) == 180
    assert len({query.query_variant_id for query in variants}) == 180
    assert Counter(query.affect for query in variants) == {affect: 60 for affect in Affect}
    assert Counter(query.query_length for query in variants) == {length: 90 for length in QueryLength}


def test_query_validator_rejects_prohibited_semantics() -> None:
    """Reject urgency, distrust, and requests for reassurance or extra detail."""
    with pytest.raises(ValidationError):
        QueryVariant(
            query_variant_id="x",
            scenario_id="CF101_R1",
            affect=Affect.ANXIOUS,
            query_length=QueryLength.SHORT,
            text="This is urgent; reassure me and give me more detail.",
        )


def test_non_user_state_fact_orders_are_balanced() -> None:
    """Balance the two fixed fact orders 15/15."""
    assert Counter(assigned_fact_order(index) for index in range(30)) == {1: 15, 2: 15}


def test_query_protocol_republishes_without_changing_facts_or_provenance() -> None:
    """Update only query stems while preserving accepted fact and generation fields."""
    scenarios = [AcceptedScenario.model_validate(record) for record in read_jsonl(SCENARIO_ROOT / "accepted_scenarios.jsonl")]
    families = [AuthoredQueryFamily.model_validate(record) for record in read_jsonl(SCENARIO_ROOT / "query_families.jsonl")]
    approval = build_query_protocol_approval(scenarios, families, "researcher", "Approved natural query families.", datetime(2026, 8, 16, tzinfo=UTC))
    published, variants = apply_query_protocol(scenarios, families, approval)
    assert len(variants) == 180
    assert all(before.facts == after.facts for before, after in zip(scenarios, published))
    assert all(before.generation_request_sha256 == after.generation_request_sha256 for before, after in zip(scenarios, published))
    assert all(before.generated_output_sha256 == after.generated_output_sha256 for before, after in zip(scenarios, published))


def test_publication_embeds_exactly_one_accepted_researcher_review(accepted_scenario: AcceptedScenario) -> None:
    """Publish a pending scenario only after one accepted, hash-bound disposition."""
    review = ResearcherReviewRecord(
        scenario_id=accepted_scenario.scenario_id,
        generation_request_sha256="a" * 64,
        generated_output_sha256="b" * 64,
        disposition=ReviewState.ACCEPTED,
        researcher_id="researcher-1",
        rationale="Facts match the seed briefs and contain one atomic anchor each.",
        reviewed_at=datetime(2026, 8, 15, tzinfo=UTC),
    )
    published = publish_scenarios([accepted_scenario], [review])
    assert published[0].review.state == ReviewState.ACCEPTED
    assert published[0].review.researcher_id == "researcher-1"


def test_complete_curated_corpus_acceptance_is_hash_bound() -> None:
    """Create one accepted review for every pending scenario without changing its hashes."""
    pending = [AcceptedScenario.model_validate(record) for record in read_jsonl(SCENARIO_ROOT / "pending_scenarios.jsonl")]
    reviewed_at = datetime(2026, 8, 16, tzinfo=UTC)
    reviews = accept_curated_scenarios(pending, "researcher-1", "Reviewed and approved.", reviewed_at)
    assert len(reviews) == 30
    assert all(review.disposition == ReviewState.ACCEPTED for review in reviews)
    assert all(review.reviewed_at == reviewed_at for review in reviews)
    by_identifier = {scenario.scenario_id: scenario for scenario in pending}
    assert all(review.generated_output_sha256 == by_identifier[review.scenario_id].generated_output_sha256 for review in reviews)


def test_final_seed_owns_natural_prompt_contexts() -> None:
    """Keep role, task, and one authority limit in the final seed rather than prompt code."""
    seed_set = ScenarioSeedSet.model_validate(read_json(SCENARIO_ROOT / "final_scenario_generation_seeds.json"))
    scenarios = [AcceptedScenario.model_validate(record) for record in read_jsonl(SCENARIO_ROOT / "accepted_scenarios.jsonl")]
    contexts = {use_case.use_case_id: use_case.deployment_context for use_case in seed_set.use_cases}
    assert contexts["CF101"].role == "mortgage support assistant"
    assert contexts["CF101"].task == "Help customers understand and compare mortgage products."
    assert all(len(context.authority_limits) == 1 for context in contexts.values())
    assert all("benchmark" not in f"{context.role} {context.task} {context.authority_limits[0]}".lower() for context in contexts.values())
    assert all(scenario.deployment_context == contexts[scenario.scenario_id.split("_")[0]] for scenario in scenarios)


def test_publication_rejects_a_revise_disposition(accepted_scenario: AcceptedScenario) -> None:
    """Keep a scenario out of the accepted corpus when its one-pass review requests revision."""
    review = ResearcherReviewRecord(
        scenario_id=accepted_scenario.scenario_id,
        generation_request_sha256="a" * 64,
        generated_output_sha256="b" * 64,
        disposition=ReviewState.REVISE,
        researcher_id="researcher-1",
        rationale="One fact needs an atomic anchor.",
        reviewed_at=datetime(2026, 8, 15, tzinfo=UTC),
        revision_instructions="Replace the bundled anchor with the fee amount only.",
    )
    with pytest.raises(ValueError):
        publish_scenarios([accepted_scenario], [review])
