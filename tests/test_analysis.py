"""Test composite estimands, inference, power, and prespecified sensitivities."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List

import pandas as pd
import pytest

from src.analysis.bootstrap import stratified_scenario_bootstrap
from src.analysis.estimands import estimate_confirmatory_contrasts
from src.analysis.exploratory import brevity_locus_scenario_effects, material_priority_scenario_effects, scenario_cluster_estimates
from src.analysis.power import VarianceComponents, _composite_contrasts, simulate_holm_corrected_power
from src.analysis.r_models import run_r_robustness_models
from src.analysis.sensitivities import equal_domain_composite, leave_one_domain_out_composite
from src.analysis.sign_flip import confirmatory_sign_flip_tests
from src.data_models.common import file_sha256
from src.data_models.scoring import AnalysisEngine, AnalysisSummary
from src.experiments.assets import FIGURE_FILENAME, TABLE_FILENAME, generate_paper_assets
from src.experiments.exploratory_assets import generate_exploratory_paper_assets


def simulated_frame() -> pd.DataFrame:
    """Build the complete design with exact H1=.20 and H2=.10 effects."""
    records: List[Dict[str, object]] = []
    for use_case in range(1, 11):
        for replication in range(1, 3):
            scenario_id = f"CF{use_case:03d}_R{replication}"
            for model_id in ["m1", "m2", "m3"]:
                for budget in ["ample", "tight"]:
                    for concern in ["neutral", "concerned"]:
                        score = 0.2 + 0.2 * (budget == "tight") + 0.1 * (concern == "concerned")
                        records.append(
                            {
                                "run_unit_id": f"RUN_{len(records):016X}",
                                "scenario_id": scenario_id,
                                "use_case_id": f"CF{use_case:03d}",
                                "model_id": model_id,
                                "word_budget": budget,
                                "expressed_concern": concern,
                                "selective_risk_communication_score": score,
                                "coverage_asymmetry": score,
                                "specificity_asymmetry": score,
                                "framing_reassurance_distortion": score,
                                "salience_asymmetry": score,
                                "factual_integrity_failure": score,
                                "budget_compliant": True,
                                "refusal": False,
                            }
                        )
    return pd.DataFrame.from_records(records)


def test_confirmatory_estimands_recover_both_composite_effects() -> None:
    """Recover the two paired composite effects from the complete matrix."""
    assert estimate_confirmatory_contrasts(simulated_frame()) == pytest.approx({"H1": 0.2, "H2": 0.1})


def test_bootstrap_and_sign_flip_use_scenario_clusters() -> None:
    """Return deterministic intervals and two Holm-adjusted sign-flip tests."""
    estimates, intervals, draws = stratified_scenario_bootstrap(simulated_frame(), draws=50, seed=3)
    assert estimates == pytest.approx({"H1": 0.2, "H2": 0.1})
    assert intervals["H1"] == pytest.approx((0.2, 0.2))
    assert len(draws) == 50
    raw, adjusted = confirmatory_sign_flip_tests(simulated_frame(), permutations=100_000, seed=3)
    assert set(raw) == {"H1", "H2"}
    assert all(value < 0.001 for value in adjusted.values())


def test_equal_domain_and_leave_one_domain_out_sensitivities() -> None:
    """Apply equal weights and proportional frozen-weight renormalisation."""
    frame = simulated_frame().iloc[:2].copy()
    assert equal_domain_composite(frame).tolist() == pytest.approx(frame["selective_risk_communication_score"].tolist())
    frame["coverage_asymmetry"] = 1.0
    without_coverage = leave_one_domain_out_composite(frame, "coverage")
    assert all(0 <= value <= 1 for value in without_coverage)
    assert without_coverage.tolist() == pytest.approx(
        (
            0.15 * frame["specificity_asymmetry"]
            + 0.20 * frame["framing_reassurance_distortion"]
            + 0.15 * frame["salience_asymmetry"]
            + 0.20 * frame["factual_integrity_failure"]
        )
        .div(0.70)
        .tolist()
    )


def test_power_simulation_uses_complete_composite_design() -> None:
    """Represent cue-template, pair, fact, scenario, model, and scoring variation."""
    components = VarianceComponents(
        cue_template_standard_deviation=0.01,
        pair_standard_deviation=0.01,
        fact_standard_deviation=0.01,
        scenario_standard_deviation=0.01,
        model_standard_deviation=0.01,
        scoring_error_standard_deviation=0.03,
    )
    power = simulate_holm_corrected_power({"H1": 0.20, "H2": 0.15}, components, simulations=500, seed=5)
    assert set(power) == {"H1", "H2"}
    assert all(value > 0.9 for value in power.values())


def test_power_model_heterogeneity_changes_paired_contrast_variance() -> None:
    """Ensure simulated model variation affects treatment contrasts rather than cancelling as an intercept."""
    baseline = VarianceComponents(0.01, 0.01, 0.01, 0.01, 0.0, 0.01)
    heterogeneous = VarianceComponents(0.01, 0.01, 0.01, 0.01, 0.20, 0.01)
    baseline_draws = _composite_contrasts({"H1": 0.05, "H2": 0.05}, baseline, simulations=250, seed=11)
    heterogeneous_draws = _composite_contrasts({"H1": 0.05, "H2": 0.05}, heterogeneous, simulations=250, seed=11)
    assert heterogeneous_draws["H1"].var() > baseline_draws["H1"].var()
    assert heterogeneous_draws["H2"].var() > baseline_draws["H2"].var()


def test_r_robustness_factors_preserve_confirmatory_effect_direction() -> None:
    """Keep ample/neutral as references so R coefficients match the confirmatory directions."""
    source = (Path(__file__).resolve().parents[1] / "analysis/r/run_mixed_models.R").read_text(encoding="utf-8")
    assert 'levels = c("ample", "tight")' in source
    assert 'levels = c("neutral", "concerned")' in source
    assert 'lmer_coefficients["word_budgettight"' in source
    assert 'lmer_coefficients["expressed_concernconcerned"' in source


def test_exploratory_estimators_are_paired_and_have_cluster_intervals(tmp_path: Path) -> None:
    """Estimate secondary studies without creating confirmatory p-values."""
    primary = simulated_frame()
    material = primary.loc[primary["word_budget"] == "tight"].copy()
    material_effects = material_priority_scenario_effects(material)
    material_estimates, material_intervals = scenario_cluster_estimates(material_effects, draws=50, seed=3)
    assert material_estimates["composite"] == pytest.approx(0.1)
    assert material_intervals["composite"] == pytest.approx((0.1, 0.1))

    reference = primary.loc[(primary["word_budget"] == "tight") & (primary["expressed_concern"] == "neutral")].copy()
    brevity = reference.copy()
    brevity["word_budget"] = "none"
    for column in [
        "selective_risk_communication_score",
        "coverage_asymmetry",
        "specificity_asymmetry",
        "framing_reassurance_distortion",
        "salience_asymmetry",
        "factual_integrity_failure",
    ]:
        brevity[column] += 0.05
    brevity_effects = brevity_locus_scenario_effects(brevity, primary)
    brevity_estimates, brevity_intervals = scenario_cluster_estimates(brevity_effects, draws=50, seed=3)
    assert brevity_estimates["composite"] == pytest.approx(0.05)
    summary = AnalysisSummary(
        schema_version="2.0.0",
        analysis_id="brevity_locus_v1_exploratory",
        engine=AnalysisEngine.PYTHON,
        method="paired_cluster_bootstrap",
        estimands={name: Decimal(str(value)) for name, value in brevity_estimates.items()},
        confidence_intervals={name: [Decimal(str(value)) for value in interval] for name, interval in brevity_intervals.items()},
        raw_p_values={},
        adjusted_p_values={},
        converged=True,
        convergence_messages=[],
        source_data_sha256="0" * 64,
        generated_at=datetime.now(timezone.utc),
    )
    table, csv = generate_exploratory_paper_assets(summary, tmp_path, "brevity_locus_v1")
    assert table.name == "brevity_locus_v1_table.tex"
    assert csv.name == "brevity_locus_v1_domain_summary.csv"


def test_r_python_interchange_surfaces_nonconvergence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Schema-validate R JSON and surface rather than hide nonconvergence."""
    monkeypatch.chdir(tmp_path)
    output_path = Path("r_summary.json")
    input_path = Path("input.csv")
    input_path.write_text("value\n1\n", encoding="utf-8")

    def fake_run(*args: object, **kwargs: object) -> SimpleNamespace:
        """Write a valid non-converged V2 summary."""
        output_path.write_text(
            json.dumps(
                {
                    "schema_version": "2.0.0",
                    "analysis_id": "risk_comm_v1_mixed_models",
                    "engine": "r",
                    "method": "robustness",
                    "estimands": {"H1": 0.1},
                    "confidence_intervals": {},
                    "raw_p_values": {},
                    "adjusted_p_values": {},
                    "converged": False,
                    "convergence_messages": ["singular fit"],
                    "source_data_sha256": file_sha256(input_path),
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr("src.analysis.r_models.subprocess.run", fake_run)
    with pytest.raises(RuntimeError, match="did not converge"):
        run_r_robustness_models(input_path, output_path, file_sha256(input_path), Path("model.R"), Path("."))


def test_stable_primary_paper_asset_names(tmp_path: Path) -> None:
    """Generate fixed LaTeX/PDF assets for H1 and H2."""
    estimates = {"H1": 0.2, "H2": 0.1}
    intervals = {"H1": (0.1, 0.3), "H2": (0.0, 0.2)}
    table_path, figure_path = generate_paper_assets(tmp_path, estimates, intervals, {"H1": 0.01, "H2": 0.02})
    assert table_path.name == TABLE_FILENAME
    assert figure_path.name == FIGURE_FILENAME
    assert figure_path.read_bytes().startswith(b"%PDF")
