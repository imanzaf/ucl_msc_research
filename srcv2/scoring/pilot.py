"""Stratified five-percent sampling for judge-prompt development."""

from __future__ import annotations

import random
from collections import defaultdict
from typing import Dict, List, Sequence

from srcv2.common import ImmutableModel, artifact_sha256
from srcv2.models.experiments import RunUnit
from srcv2.models.scoring import JudgePilotSample

PILOT_RESPONSE_COUNT = 191
FROZEN_RESPONSE_COUNT = 3822


class SamplingRecord(ImmutableModel):
    """Represent an eligible frozen response and its sampling strata."""

    response_id: str
    experiment: str
    model_slug: str
    response_length_band: str


def response_length_band(response_text: str) -> str:
    """Assign an interpretable length band aligned with the word-budget treatments."""
    word_count = len(response_text.split())
    if word_count <= 80:
        return "short_0_80"
    if word_count <= 160:
        return "medium_81_160"
    return "long_161_plus"


def build_sampling_frame(runs: Sequence[RunUnit]) -> List[SamplingRecord]:
    """Build the complete stratified sampling frame from frozen semantic responses."""
    identifiers = [run.run_unit_id for run in runs]
    if len(runs) != FROZEN_RESPONSE_COUNT or len(set(identifiers)) != FROZEN_RESPONSE_COUNT:
        raise ValueError("judge sampling requires all 3,822 unique evaluated responses")
    records: List[SamplingRecord] = []
    for run in runs:
        if run.response is None:
            raise ValueError("judge sampling cannot include a run without a semantic response")
        response_text = run.response.answer_text if run.response.answer_text is not None else run.response.raw_response
        records.append(
            SamplingRecord(
                response_id=run.run_unit_id,
                experiment=run.experiment.value,
                model_slug=run.model.model_slug,
                response_length_band=response_length_band(response_text),
            )
        )
    return records


def stratified_sample(records: Sequence[SamplingRecord], sample_size: int = PILOT_RESPONSE_COUNT, random_seed: int = 410191) -> List[str]:
    """Draw a reproducible approximately proportional sample across declared strata."""
    if sample_size != PILOT_RESPONSE_COUNT:
        raise ValueError("the judge-development pilot requires exactly 191 responses")
    if len({record.response_id for record in records}) != len(records) or len(records) < sample_size:
        raise ValueError("eligible response identifiers must be unique and number at least 191")
    groups: Dict[tuple[str, str, str], List[str]] = defaultdict(list)
    for record in records:
        groups[(record.experiment, record.model_slug, record.response_length_band)].append(record.response_id)
    randomizer = random.Random(random_seed)
    for identifiers in groups.values():
        randomizer.shuffle(identifiers)
    exact_allocations = {key: sample_size * len(values) / len(records) for key, values in groups.items()}
    allocations = {key: min(len(groups[key]), int(value)) for key, value in exact_allocations.items()}
    remaining = sample_size - sum(allocations.values())
    priorities = sorted(groups, key=lambda key: (exact_allocations[key] - allocations[key], len(groups[key]), key), reverse=True)
    while remaining:
        progressed = False
        for key in priorities:
            if allocations[key] < len(groups[key]) and remaining:
                allocations[key] += 1
                remaining -= 1
                progressed = True
        if not progressed:
            raise ValueError("unable to allocate requested stratified sample")
    selected = [identifier for key in sorted(groups) for identifier in groups[key][: allocations[key]]]
    randomizer.shuffle(selected)
    return selected


def build_pilot_sample(records: Sequence[SamplingRecord], random_seed: int = 410191) -> JudgePilotSample:
    """Create the hash-bound 191-response judge-development sample."""
    base = {
        "schema_version": "4.0.0",
        "source_response_count": FROZEN_RESPONSE_COUNT,
        "response_ids": stratified_sample(records, random_seed=random_seed),
        "random_seed": random_seed,
    }
    return JudgePilotSample.model_validate({**base, "sample_sha256": artifact_sha256(base)})
