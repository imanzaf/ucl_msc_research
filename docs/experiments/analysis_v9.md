# V9 analysis and paper assets

Python owns the five estimands, use-case-stratified scenario bootstrap, Holm correction, power simulation, equivalence checks, sensitivities, and assets. Facts are never resampled as independent units. The default bootstrap uses 10,000 draws.

Before preregistration, freeze calibration-derived variance components and the five smallest effects, then simulate the repeated 10-use-case × 4-scenario × 3-model × 2-order design:

```bash
uv run python scripts/build_analysis_assumption_manifests.py \
  --assumptions-json <analysis_assumptions.json> \
  --calibration-source <frozen_calibration_analysis.json> \
  --frozen-by <researcher_id> \
  --smallest-output data/outputs/experiments/risk_comm_v1/checkpoints/smallest_effect_manifest.json \
  --power-output data/outputs/experiments/risk_comm_v1/checkpoints/power_assumption_manifest.json

uv run python scripts/simulate_power.py \
  --smallest-effect-manifest data/outputs/experiments/risk_comm_v1/checkpoints/smallest_effect_manifest.json \
  --power-assumption-manifest data/outputs/experiments/risk_comm_v1/checkpoints/power_assumption_manifest.json \
  --output data/outputs/experiments/risk_comm_v1/checkpoints/power_simulation_report.json \
  --simulations 5000
```

`analysis_assumptions.json` is a strict `1.0.0` object containing `absolute_bounds`, `rationales`, and `variance_components`, each keyed by exactly `H1`, `H2a`, `H2b`, `M1`, and `M2`.

The report applies Holm correction within each simulated five-test family and includes stressed model-heterogeneity, scoring-error, and single-source-order surfaces. It uses only calibration variance inputs, never held-out effect directions.

```bash
uv run python scripts/analyse_experiment.py \
  --analysis-input data/outputs/experiments/risk_comm_v1/results/analysis_inputs.jsonl \
  --fact-analysis-input data/outputs/experiments/risk_comm_v1/results/fact_analysis_inputs.jsonl \
  --human-reference-analysis-input data/outputs/experiments/risk_comm_v1/results/human_reference_analysis_inputs.jsonl \
  --missingness-report data/outputs/experiments/risk_comm_v1/results/missingness_report.json \
  --experiment-manifest data/outputs/experiments/risk_comm_v1/checkpoints/experiment_manifest.json \
  --preregistration-manifest data/outputs/experiments/risk_comm_v1/checkpoints/preregistration_manifest.json \
  --annotation-sample-manifest data/outputs/experiments/risk_comm_v1/checkpoints/evaluation_annotation_sample_manifest.json \
  --scoring-validation-report data/outputs/experiments/risk_comm_v1/results/scoring_validation_report.json \
  --smallest-effect-manifest data/outputs/experiments/risk_comm_v1/checkpoints/smallest_effect_manifest.json \
  --analysis-plan docs/research-plan/RESEARCH_PLAN_V9.md \
  --protocol-deviations data/outputs/experiments/risk_comm_v1/checkpoints/protocol_deviations.json \
  --output-summary data/outputs/experiments/risk_comm_v1/results/confirmatory_summary.json \
  --sensitivity-summary data/outputs/experiments/risk_comm_v1/results/sensitivity_summary.json \
  --equivalence-summary data/outputs/experiments/risk_comm_v1/results/equivalence_summary.json \
  --r-input-csv data/outputs/experiments/risk_comm_v1/results/r_robustness_input.csv \
  --r-output-summary data/outputs/experiments/risk_comm_v1/results/r_robustness_summary.json \
  --assets-dir data/outputs/experiments/risk_comm_v1/assets \
  --draws 10000
```

The command requires the full terminal 1,920-unit ledger while analysing only completed outcomes recorded by the bound missingness report. It refuses a changed analysis commit, broken preregistration links, unresolvable paired estimands, or failed disclosure/omission/reassurance headline gates. It writes schema-validated confirmatory, sensitivity, equivalence, and R summaries plus stable `risk_comm_v1_table.tex` and `risk_comm_v1_figure.pdf` paths. Sensitivities cover each model, each source order, leave-one-use-case-out estimates, budget-compliant responses, refusal exclusion, binary disclosure thresholds, the locked human-reference subset, response-length mediation, and mitigation-row exclusion invariance.

R robustness code is locked by the complete transitive graph in `analysis/r/renv.lock` and executed by `analysis/r/run_mixed_models.R`:

```bash
Rscript -e 'renv::restore(project = "analysis/r")'
Rscript analysis/r/run_mixed_models.R <analysis.csv> <summary.json> <input_sha256>
```

The main analysis command invokes this locked R script after creating the exact input CSV. It fits conversation-level `lmer`/`glmer` models on one row per run unit and a true four-material-fact ordinal `clmm` rather than deriving an ordinal label from aggregate coverage. `src/analysis/r_models.py` resolves all paths before changing the R working directory, recomputes the CSV hash, schema-validates returned JSON, verifies its source hash, and raises on non-convergence. `analysis/r/smoke_test.R` fits all three model classes on simulated data in CI.
