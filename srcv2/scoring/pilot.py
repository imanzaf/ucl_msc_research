"""Stratified sampling for the frozen judge-prompt development set."""

from __future__ import annotations

import random
from collections import defaultdict
from math import ceil
from typing import Dict, List, Sequence

from srcv2.common import ImmutableModel, artifact_sha256
from srcv2.models.experiments import RunUnit
from srcv2.models.scoring import JudgePilotSample

PILOT_FRACTION = 0.05


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
    """Build one experiment's stratified sampling frame from semantic responses."""
    identifiers = [run.run_unit_id for run in runs]
    if not runs or len(set(identifiers)) != len(runs):
        raise ValueError("judge sampling requires a non-empty set of unique evaluated responses")
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


def stratified_sample(records: Sequence[SamplingRecord], sample_size: int, random_seed: int = 410191) -> List[str]:
    """Draw a reproducible approximately proportional sample across declared strata."""
    if sample_size < 1 or sample_size > len(records):
        raise ValueError("pilot sample size must be between one and the source response count")
    if len({record.response_id for record in records}) != len(records):
        raise ValueError("eligible response identifiers must be unique")
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


def build_pilot_sample(records: Sequence[SamplingRecord], sample_size: int | None = None, random_seed: int = 410191) -> JudgePilotSample:
    """Create one hash-bound five-percent judge-development sample."""
    resolved_size = sample_size if sample_size is not None else max(1, ceil(len(records) * PILOT_FRACTION))
    base = {
        "schema_version": "4.0.0",
        "source_response_count": len(records),
        "response_ids": stratified_sample(records, resolved_size, random_seed=random_seed),
        "random_seed": random_seed,
    }
    return JudgePilotSample.model_validate({**base, "sample_sha256": artifact_sha256(base)})
