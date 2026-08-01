"""Build blinded descriptive diagnostics for researcher pair review."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import List, Set

from src.data_models.common import sha256_bytes
from src.data_models.scenario_review import PairDiagnostics
from src.data_models.scenarios import AcceptedScenario, CandidateScenario, ScenarioFactInformation, scenario_fact_pairs
from src.scenarios.word_count import count_words

NUMBER_PATTERN = re.compile(r"(?:£|\$|€)?\d+(?:[.,]\d+)?%?")
CONDITION_PATTERN = re.compile(r"\b(if|unless|when|after|before|provided|except|subject to|only)\b", re.IGNORECASE)
HEDGING_PATTERN = re.compile(r"\b(may|might|could|potentially|typically|generally|approximately|around|up to)\b", re.IGNORECASE)


def _readability(text: str) -> Decimal:
    """Return a deterministic Flesch-style readability estimate."""
    words = re.findall(r"[A-Za-z]+", text)
    sentences = max(1, len(re.findall(r"[.!?]", text)))
    syllables = sum(max(1, len(re.findall(r"[aeiouy]+", word.lower()))) for word in words)
    if not words:
        return Decimal("0")
    value = 206.835 - 1.015 * (len(words) / sentences) - 84.6 * (syllables / len(words))
    return Decimal(str(round(value, 3)))


def _quantities(fact: ScenarioFactInformation) -> Set[str]:
    """Return literal number-like strings present in one visible fact."""
    return set(NUMBER_PATTERN.findall(fact.fact_text))


def _blinded_pair_facts(
    pair_id: str,
    owner_option_fact: ScenarioFactInformation,
    alternative_option_fact: ScenarioFactInformation,
) -> List[ScenarioFactInformation]:
    """Assign the two option facts to opaque sides without a fixed mapping."""
    facts = [owner_option_fact, alternative_option_fact]
    if int(sha256_bytes(f"pair-diagnostic-v1:{pair_id}".encode("utf-8"))[:2], 16) % 2:
        facts.reverse()
    return facts


def build_pair_diagnostics(scenario: CandidateScenario | AcceptedScenario) -> List[PairDiagnostics]:
    """Build both diagnostics without applying an automatic balance threshold."""
    diagnostics: List[PairDiagnostics] = []
    for owner_item, alternative_item in scenario_fact_pairs(scenario):
        owner_coordinate, owner_option_fact = owner_item
        _, alternative_option_fact = alternative_item
        facts = _blinded_pair_facts(
            owner_coordinate.pair_id,
            owner_option_fact,
            alternative_option_fact,
        )
        keys = ["side_a", "side_b"]
        visible_text = [fact.fact_text for fact in facts]
        diagnostics.append(
            PairDiagnostics(
                pair_id=owner_coordinate.pair_id,
                proposition_word_counts={key: count_words(fact.fact_text) for key, fact in zip(keys, facts)},
                numeric_burden={key: len(NUMBER_PATTERN.findall(text)) for key, text in zip(keys, visible_text)},
                conditional_burden={key: len(CONDITION_PATTERN.findall(text)) for key, text in zip(keys, visible_text)},
                hedging_burden={key: len(HEDGING_PATTERN.findall(text)) for key, text in zip(keys, visible_text)},
                readability={key: _readability(text) for key, text in zip(keys, visible_text)},
                arithmetic_dependency={key: False for key in keys},
                shared_quantities=sorted(_quantities(facts[0]) & _quantities(facts[1])),
            )
        )
    return diagnostics
