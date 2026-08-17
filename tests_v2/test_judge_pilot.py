"""Judge-development pilot sampling tests."""

from __future__ import annotations

from srcv2.scoring.pilot import PILOT_RESPONSE_COUNT, SamplingRecord, build_pilot_sample, stratified_sample


def _sampling_records() -> list[SamplingRecord]:
    """Build a fully eligible synthetic sampling frame."""
    return [
        SamplingRecord(
            response_id=f"response_{experiment}_{model}_{length_band}_{replicate}",
            experiment=f"experiment_{experiment}",
            model_slug=f"model_{model}",
            response_length_band=length_band,
        )
        for experiment in range(6)
        for model in range(7)
        for length_band in ("short", "medium", "long")
        for replicate in range(10)
    ]


def test_five_percent_pilot_is_reproducible() -> None:
    """Draw 191 unique responses from the full frozen corpus."""
    first = stratified_sample(_sampling_records(), random_seed=9)
    second = stratified_sample(_sampling_records(), random_seed=9)
    assert first == second
    assert len(first) == PILOT_RESPONSE_COUNT == 191
    assert len(set(first)) == 191


def test_pilot_sample_binds_identifiers_and_seed() -> None:
    """Hash the exact selected response identifiers and sampling seed."""
    sample = build_pilot_sample(_sampling_records(), random_seed=410191)
    assert sample.source_response_count == 3822
    assert len(sample.response_ids) == 191
    assert len(sample.sample_sha256) == 64
