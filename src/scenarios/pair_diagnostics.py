"""Build blinded descriptive diagnostics for researcher pair review."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import List, Set

from src.data_models.common import sha256_bytes
from src.data_models.scenario_review import PairDiagnostics
from src.data_models.scenarios import AcceptedScenario, CandidateScenario, MaterialFact
from src.scenarios.word_count import count_words

NUMBER_PATTERN = re.compile(r"(?:£|\$|€)?\d+(?:[.,]\d+)?%?")
CONDITION_PATTERN = re.compile(r"\b(if|unless|when|after|before|provided|except|subject to|only)\b", re.IGNORECASE)


def _readability(text: str) -> Decimal:
    """Return a deterministic Flesch-style readability estimate."""
    words = re.findall(r"[A-Za-z]+", text)
    sentences = max(1, len(re.findall(r"[.!?]", text)))
    syllables = sum(max(1, len(re.findall(r"[aeiouy]+", word.lower()))) for word in words)
    if not words:
        return Decimal("0")
    value = 206.835 - 1.015 * (len(words) / sentences) - 84.6 * (syllables / len(words))
    return Decimal(str(round(value, 3)))


def _fact_evidence_text(fact: MaterialFact) -> str:
    """Join the exact evidence spans used by one material fact."""
    return " ".join(span.exact_text for span in fact.source_support)


def _quantities(fact: MaterialFact) -> Set[str]:
    """Return predefined numeric and conditional specificity values."""
    return {element.canonical_value for element in fact.specificity_elements}


def _blinded_pair_facts(pair_id: str, provider_fact: MaterialFact, customer_fact: MaterialFact) -> List[MaterialFact]:
    """Assign provider/customer option facts to opaque sides without a fixed mapping."""
    facts = [provider_fact, customer_fact]
    if int(sha256_bytes(f"pair-diagnostic-v1:{pair_id}".encode("utf-8"))[:2], 16) % 2:
        facts.reverse()
    return facts


def build_pair_diagnostics(scenario: CandidateScenario | AcceptedScenario) -> List[PairDiagnostics]:
    """Build both diagnostics without applying an automatic balance threshold."""
    fact_by_id = {fact.fact_id: fact for fact in scenario.material_facts}
    source_positions = {item.source_item_id: index for index, item in enumerate(scenario.source_packet.items, start=1)}
    computed_ids = {value.value_id for value in scenario.numeric_registry.computed_values}
    diagnostics: List[PairDiagnostics] = []
    for pair in scenario.fact_pairs:
        facts = _blinded_pair_facts(
            pair.pair_id,
            fact_by_id[pair.provider_option_fact_id],
            fact_by_id[pair.customer_option_fact_id],
        )
        keys = ["side_a", "side_b"]
        evidence = [_fact_evidence_text(fact) for fact in facts]
        diagnostics.append(
            PairDiagnostics(
                pair_id=pair.pair_id,
                proposition_word_counts={key: count_words(fact.canonical_proposition) for key, fact in zip(keys, facts)},
                evidence_word_counts={key: count_words(text) for key, text in zip(keys, evidence)},
                numeric_burden={key: len(NUMBER_PATTERN.findall(text)) for key, text in zip(keys, evidence)},
                conditional_burden={key: len(CONDITION_PATTERN.findall(text)) for key, text in zip(keys, evidence)},
                readability={key: _readability(text) for key, text in zip(keys, evidence)},
                source_positions={key: min(source_positions[span.source_item_id] for span in fact.source_support) for key, fact in zip(keys, facts)},
                arithmetic_dependency={
                    key: any(
                        value_id in computed_ids
                        for item in scenario.source_packet.items
                        if item.source_item_id in {span.source_item_id for span in fact.source_support}
                        for value_id in item.numeric_value_ids
                    )
                    for key, fact in zip(keys, facts)
                },
                shared_quantities=sorted(_quantities(facts[0]) & _quantities(facts[1])),
                blinded_materiality_ratings={key: fact.materiality_rating for key, fact in zip(keys, facts)},
            )
        )
    return diagnostics
