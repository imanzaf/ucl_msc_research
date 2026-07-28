"""Tests for primary selective and interval-only secondary analyses."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from src.analysis.bootstrap import stratified_scenario_bootstrap
from src.analysis.estimands import estimate_confirmatory_contrasts, estimate_outcome_contrasts, scenario_level_contrasts
from src.analysis.power import VarianceComponents, _selective_contrasts, expected_secondary_interval_half_widths, simulate_holm_corrected_power
from src.analysis.sensitivities import estimate_sensitivities_with_messages
from src.data_models.scoring import ConstructValidationDiagnostics, EvaluationCheckpoint, FailedConstructAction, ScoringConstruct
from src.experiments.assets import generate_paper_assets
from src.scoring.disposition import build_validation_disposition_manifest
from src.scoring.reliability import build_scoring_validation_report
from tests.factories import NOW, ZERO_HASH


def _analysis_frame() -> pd.DataFrame:
    """Return a complete balanced 20-scenario repeated-design frame."""
    records = []
    for use_case in range(1, 11):
        for replication in range(1, 3):
            scenario_id = f"CF{use_case:03d}_R{replication}"
            for model_id in ["m1", "m2", "m3"]:
                for budget in ["baseline", "concise"]:
                    for concern in ["neutral", "concerned"]:
                        concise = float(budget == "concise")
                        concerned = float(concern == "concerned")
                        records.append(
                            {
                                "run_unit_id": f"{scenario_id}:{model_id}:{budget}:{concern}",
                                "scenario_id": scenario_id,
                                "use_case_id": f"CF{use_case:03d}",
                                "model_id": model_id,
                                "word_budget": budget,
                                "expressed_concern": concern,
                                "selective_communication_score": 0.2 + 0.1 * concise + 0.05 * concerned,
                                "presentation_style_score": 0.1 + 0.03 * concise - 0.02 * concerned,
                                "factual_inaccuracy_score": concise,
                                "coverage_asymmetry": 0.2,
                                "specificity_asymmetry": 0.2,
                                "owner_favouring_framing_rate": 0.1,
                                "ordering_asymmetry": 0.1,
                                "emphasis_asymmetry": 0.1,
                                "false_claim_present": bool(concise),
                                "unsupported_claim_present": False,
                            }
                        )
    return pd.DataFrame.from_records(records)


def test_confirmatory_contrasts_use_only_initial_selective_score() -> None:
    """H1 and H2 recover paired effects on the primary outcome."""
    estimates = estimate_confirmatory_contrasts(_analysis_frame())
    assert estimates["H1"] == pytest.approx(0.1)
    assert estimates["H2"] == pytest.approx(0.05)
    presentation = estimate_outcome_contrasts(
        _analysis_frame(),
        "presentation_style_score",
    )
    assert presentation["H1"] == pytest.approx(0.03)
    assert presentation["H2"] == pytest.approx(-0.02)


def test_bootstrap_supports_secondary_outcomes_without_p_values() -> None:
    """The same paired bootstrap can estimate either secondary score."""
    points, intervals, draws = stratified_scenario_bootstrap(
        _analysis_frame(),
        outcome="presentation_style_score",
        draws=25,
        seed=7,
    )
    assert points["H1"] == pytest.approx(0.03)
    assert set(intervals) == {"H1", "H2"}
    assert draws.shape == (25, 2)


def test_scenario_contrasts_cover_twenty_clusters() -> None:
    """Each analysis outcome yields one H1/H2 vector per scenario."""
    result = scenario_level_contrasts(
        _analysis_frame(),
        "factual_inaccuracy_score",
    )
    assert len(result) == 20
    assert result["use_case_id"].nunique() == 10
    assert result["H1"].tolist() == pytest.approx([1.0] * 20)


def test_sensitivities_exclude_old_domain_composites_and_spontaneous_change() -> None:
    """Only model/use-case and score/checkpoint estimates remain."""
    frame = _analysis_frame()
    estimates, messages = estimate_sensitivities_with_messages(
        frame,
        {
            EvaluationCheckpoint.FOLLOW_UP: frame,
            EvaluationCheckpoint.CUMULATIVE: frame,
        },
    )
    assert not messages
    assert any(name.startswith("secondary_initial=presentation_style_score") for name in estimates)
    assert any(name.startswith("secondary_checkpoint=follow_up:selective_communication_score") for name in estimates)
    assert not any("equal_domain" in name for name in estimates)
    assert not any("leave_domain" in name for name in estimates)
    assert not any("spontaneous" in name for name in estimates)


def test_power_simulates_two_equal_weight_selective_components() -> None:
    """Power uses coverage and specificity under the two-test Holm family."""
    components = VarianceComponents(
        pair_standard_deviation=0.05,
        fact_standard_deviation=0.05,
        scenario_standard_deviation=0.05,
        model_standard_deviation=0.02,
        scoring_error_standard_deviation=0.05,
    )
    contrasts = _selective_contrasts(
        {"H1": 0.08, "H2": 0.05},
        components,
        simulations=10,
        seed=7,
    )
    assert contrasts["H1"].shape == (10, 20)
    power = simulate_holm_corrected_power(
        {"H1": 0.08, "H2": 0.05},
        components,
        simulations=50,
        seed=7,
    )
    assert set(power) == {"H1", "H2"}
    assert all(0 <= value <= 1 for value in power.values())
    precision = expected_secondary_interval_half_widths(
        {
            "initial:presentation_style_score:H1": 0.2,
            "initial:presentation_style_score:H2": 0.1,
            "initial:factual_inaccuracy_score:H1": 0.3,
            "initial:factual_inaccuracy_score:H2": 0.25,
        }
    )
    assert precision["initial:presentation_style_score:H1"] == pytest.approx(1.96 * 0.2 / (20**0.5))


def test_failed_construct_dispositions_are_separate_by_score_family() -> None:
    """Removal reweights selective scoring while presentation withholding stays secondary."""
    failed = {
        ScoringConstruct.COVERAGE,
        ScoringConstruct.FRAMING,
        ScoringConstruct.ACCURACY,
    }
    diagnostics = {
        construct: ConstructValidationDiagnostics(
            prevalence=Decimal("0.5"),
            agreement=Decimal("0.9"),
            confusion_matrix={"absent": {"absent": 1}},
            precision=Decimal("0.9"),
            recall=Decimal("0.9"),
            f1=Decimal("0.9"),
            maximum_absolute_error=(
                Decimal("0.01")
                if construct
                in {
                    ScoringConstruct.ORDERING,
                    ScoringConstruct.EMPHASIS,
                }
                else None
            ),
            invalid_output_count=0,
            sample_size=10,
            uncertainty_interval=[Decimal("0.8"), Decimal("1")],
            gate_passed=construct not in failed,
        )
        for construct in ScoringConstruct
    }
    report = build_scoring_validation_report(
        diagnostics,
        sample_size=10,
        construct_gate_manifest_sha256=ZERO_HASH,
        validation_sample_manifest_sha256=ZERO_HASH,
        generated_at=NOW,
    )
    disposition = build_validation_disposition_manifest(
        report,
        {
            ScoringConstruct.COVERAGE: FailedConstructAction.REMOVE_AND_RENORMALISE,
            ScoringConstruct.FRAMING: FailedConstructAction.WITHHOLD_OUTCOME,
            ScoringConstruct.ACCURACY: FailedConstructAction.FULL_MANUAL_SCORING,
        },
        blinded_diagnostics_sha256=report.report_sha256,
        researcher_id="researcher",
        rationale="Apply the prespecified outcome-specific contingencies.",
        decided_at=NOW,
    )
    assert disposition.selective_weights == {
        ScoringConstruct.COVERAGE: Decimal("0"),
        ScoringConstruct.SPECIFICITY: Decimal("1"),
    }
    assert disposition.presentation_result_withheld is True
    assert disposition.factual_inaccuracy_result_withheld is False
    assert disposition.confirmatory_inference_withheld is False


def test_paper_assets_separate_confirmatory_and_secondary_panels(
    tmp_path: Path,
) -> None:
    """Only the confirmatory table receives Holm-adjusted p-values."""
    confirmatory, secondary, figure = generate_paper_assets(
        tmp_path,
        {"H1": 0.1, "H2": 0.05},
        {"H1": (0.02, 0.18), "H2": (0.0, 0.1)},
        {"H1": 0.02, "H2": 0.04},
        {"initial:presentation_style_score:H1": 0.03},
        {"initial:presentation_style_score:H1": (-0.01, 0.07)},
    )
    assert "Holm-adjusted" in confirmatory.read_text(encoding="utf-8")
    assert "Holm" not in secondary.read_text(encoding="utf-8")
    assert figure.exists()
