"""Known-effect recovery, clustered bootstrap, Holm, sensitivity, R interchange, and assets."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List

import numpy as np
import pandas as pd
import pytest

from src.analysis.bootstrap import resample_scenarios_within_use_case, stratified_scenario_bootstrap
from src.analysis.estimands import estimate_confirmatory_contrasts
from src.analysis.multiplicity import holm_adjust
from src.analysis.power import VarianceComponents, simulate_holm_corrected_power
from src.analysis.r_models import run_r_robustness_models
from src.analysis.sensitivities import _binary_threshold_estimates
from src.data_models.common import file_sha256
from src.experiments.assets import FIGURE_FILENAME, TABLE_FILENAME, generate_paper_assets


def simulated_frame() -> pd.DataFrame:
    """Build complete repeated cells with exactly known confirmatory effects."""
    records: List[Dict[str, object]] = []
    for scenario_index in range(1, 41):
        use_case_id = f"CF{((scenario_index - 1) // 4) + 1:03d}"
        scenario_id = f"{use_case_id}_R{((scenario_index - 1) % 4) + 1}"
        for model_id in ["m1", "m2", "m3"]:
            for source_order in ["A", "B"]:
                for integrity in ["absent", "targeted"]:
                    for word_budget in ["ample", "tight"]:
                        for cue in ["neutral", "worried"]:
                            run_unit_id = f"RUN_{len(records):016X}"
                            gap = 0.0
                            if word_budget == "tight":
                                gap = 0.2 if integrity == "absent" else 0.1
                            records.append(
                                {
                                    "run_unit_id": run_unit_id,
                                    "scenario_id": scenario_id,
                                    "use_case_id": use_case_id,
                                    "model_id": model_id,
                                    "source_order": source_order,
                                    "word_budget": word_budget,
                                    "emotional_cue": cue,
                                    "integrity": integrity,
                                    "pairwise_disclosure_gap": gap,
                                    "adverse_coverage": 0.6 if cue == "worried" else 0.5,
                                    "unsupported_reassurance": 1.0 if cue == "worried" else 0.0,
                                    "material_coverage": 0.5,
                                    "response_word_count": 80,
                                    "budget_compliant": True,
                                    "refusal": False,
                                }
                            )
    return pd.DataFrame.from_records(records)


def test_confirmatory_estimands_recover_known_effects() -> None:
    """Recover all five effects from a complete deterministic repeated design."""
    estimates = estimate_confirmatory_contrasts(simulated_frame())
    assert estimates == pytest.approx({"H1": 0.2, "H2a": 0.1, "H2b": 1.0, "M1": -0.1, "M2": -0.1})


def test_primary_estimates_ignore_any_mitigation_row_changes() -> None:
    """Prove H1/H2a/H2b are unchanged when mitigation outcomes are perturbed."""
    frame = simulated_frame()
    original = estimate_confirmatory_contrasts(frame)
    changed = frame.copy()
    changed.loc[changed["integrity"] == "targeted", ["pairwise_disclosure_gap", "adverse_coverage", "unsupported_reassurance"]] = 99
    perturbed = estimate_confirmatory_contrasts(changed)
    assert {name: original[name] for name in ["H1", "H2a", "H2b"]} == {name: perturbed[name] for name in ["H1", "H2a", "H2b"]}


def test_binary_sensitivity_rebuilds_conversation_outcomes_from_facts() -> None:
    """Threshold four material-fact rows rather than thresholding conversation aggregates."""
    frame = simulated_frame()
    fact_records: List[Dict[str, object]] = []
    for row in frame.to_dict(orient="records"):
        for index in range(2):
            fact_records.append(
                {
                    "run_unit_id": row["run_unit_id"],
                    "fact_id": f"A{index}",
                    "fact_valence": "adverse",
                    "disclosure_ordinal": 2 if row["emotional_cue"] == "worried" else 0,
                }
            )
            fact_records.append(
                {
                    "run_unit_id": row["run_unit_id"],
                    "fact_id": f"F{index}",
                    "fact_valence": "favourable",
                    "disclosure_ordinal": 2,
                }
            )
    estimates = _binary_threshold_estimates(frame, pd.DataFrame.from_records(fact_records), "full")
    assert estimates == pytest.approx({"H1": 0.0, "H2a": 1.0, "H2b": 1.0, "M1": 0.0, "M2": 0.0})


def test_bootstrap_resamples_scenarios_within_use_cases_not_rows() -> None:
    """Preserve complete eight-cell clusters during stratified resampling."""
    frame = simulated_frame()
    sampled = resample_scenarios_within_use_case(frame, np.random.default_rng(3))
    assert len(sampled) == len(frame)
    assert sampled["scenario_id"].str.contains("__BOOT").all()
    assert set(sampled.groupby("scenario_id").size()) == {3 * 2 * 2 * 2 * 2}
    estimates, intervals, draws = stratified_scenario_bootstrap(frame, draws=50, seed=3)
    assert len(draws) == 50
    assert intervals["H1"] == pytest.approx((0.2, 0.2))
    assert estimates["M2"] == pytest.approx(-0.1)


def test_holm_matches_monotone_fixture() -> None:
    """Reproduce a hand-checkable five-test Holm correction fixture."""
    adjusted = holm_adjust({"H1": 0.001, "H2a": 0.01, "H2b": 0.03, "M1": 0.04, "M2": 0.2})
    assert adjusted == pytest.approx({"H1": 0.005, "H2a": 0.04, "H2b": 0.09, "M1": 0.09, "M2": 0.2})


def test_power_simulation_uses_repeated_design_and_holm_family() -> None:
    """Recover low null rejection and high power for large effects across clustered use cases."""
    names = {"H1", "H2a", "H2b", "M1", "M2"}
    components = {
        name: VarianceComponents(
            use_case_standard_deviation=0.10,
            scenario_standard_deviation=0.10,
            model_standard_deviation=0.05,
            source_order_standard_deviation=0.03,
            scoring_error_standard_deviation=0.10,
        )
        for name in names
    }
    null_power = simulate_holm_corrected_power({name: 0.0 for name in names}, components, simulations=1_000, seed=11)
    large_power = simulate_holm_corrected_power({name: 1.0 for name in names}, components, simulations=1_000, seed=11)
    assert all(value < 0.08 for value in null_power.values())
    assert all(value > 0.95 for value in large_power.values())


def test_r_python_interchange_surfaces_nonconvergence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Schema-validate R JSON and raise rather than hiding a convergence failure."""
    monkeypatch.chdir(tmp_path)
    output_path = Path("r_summary.json")
    input_path = Path("input.csv")
    input_path.write_text("value\n1\n", encoding="utf-8")

    def fake_run(*args: object, **kwargs: object) -> SimpleNamespace:
        """Write a valid non-converged R summary and report process success."""
        command = args[0]
        assert isinstance(command, list)
        assert all(Path(value).is_absolute() for value in command[1:4])
        output_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0.0",
                    "analysis_id": "risk_comm_v1_mixed_models",
                    "engine": "r",
                    "method": "lmer_glmer_clmm_robustness",
                    "estimands": {"H1": 0.1},
                    "confidence_intervals": {},
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


def test_stable_paper_asset_names_and_content(tmp_path: Path) -> None:
    """Generate the fixed LaTeX table and PDF figure required by the dissertation."""
    estimates = {name: index / 10 for index, name in enumerate(["H1", "H2a", "H2b", "M1", "M2"], start=1)}
    intervals = {name: (value - 0.05, value + 0.05) for name, value in estimates.items()}
    adjusted = {name: 0.05 for name in estimates}
    table_path, figure_path = generate_paper_assets(tmp_path, estimates, intervals, adjusted)
    assert table_path.name == TABLE_FILENAME
    assert figure_path.name == FIGURE_FILENAME
    assert "Holm-adjusted" in table_path.read_text(encoding="utf-8")
    assert figure_path.read_bytes().startswith(b"%PDF")
