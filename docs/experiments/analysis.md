# Analysis runbook

The sole primary outcome is the initial `selective_communication_score`. H1 is concise minus baseline; H2 is concerned minus neutral. The family contains exactly these two confirmatory tests.

Initial presentation style and factual inaccuracy are prespecified secondary outcomes. Follow-up-only and cumulative results for all three scores are secondary checkpoints. Secondary results receive paired effect estimates and 95% scenario-bootstrap intervals, but no confirmatory p-values or significance labels.

## Build analysis inputs

```bash
uv run risk-comm analysis build-inputs \
  --transcripts data/outputs/experiments/risk_comm_v1/results/<YYYYMMDDTHHMMSS>_results.jsonl \
  --scored-bundles data/outputs/experiments/risk_comm_v1/results/scored_conversations.jsonl \
  --manual-edits data/outputs/experiments/risk_comm_v1/results/manual_scoring_edits.jsonl \
  --manual-resolutions data/outputs/experiments/risk_comm_v1/results/manual_scoring_resolutions.jsonl \
  --experiment-manifest data/outputs/experiments/risk_comm_v1/manifests/experiment_manifest.json \
  --accepted-root data/inputs/scenarios/v2.0.0/accepted \
  --accepted-scenario-manifest data/inputs/scenarios/v2.0.0/accepted_scenario_manifest.json \
  --scoring-execution-manifest data/outputs/experiments/risk_comm_v1/manifests/scoring_execution.json \
  --output data/outputs/experiments/risk_comm_v1/results/analysis_input.jsonl \
  --fact-analysis-output data/outputs/experiments/risk_comm_v1/results/fact_analysis_input.jsonl \
  --missingness-report data/outputs/experiments/risk_comm_v1/results/missingness.json
```

The builder requires the complete 240-unit terminal ledger. Every completed conversation produces initial, follow-up, and cumulative analysis rows. Fact-level rows are binary and cover four facts at all three checkpoints. A manual edit must bind an existing immutable automated bundle; its recalculated metrics and edit hash replace that bundle only in the derived analysis rows.

## Power and secondary precision

After calibration, the researcher-authored assumptions file must contain the smallest H1/H2 selective-communication effects, calibrated repeated-design variance components, and four positive scenario-contrast standard deviations:

- `initial:presentation_style_score:H1`;
- `initial:presentation_style_score:H2`;
- `initial:factual_inaccuracy_score:H1`; and
- `initial:factual_inaccuracy_score:H2`.

Freeze the assumptions against the exact calibration output, then run the two-test Holm power simulation:

```bash
uv run risk-comm analysis freeze-assumptions \
  --assumptions-json data/inputs/researcher/analysis_assumptions.json \
  --calibration-source data/outputs/experiments/risk_comm_calibration_v1/results/calibration_diagnostics.json \
  --frozen-by <researcher-id> \
  --smallest-output data/outputs/experiments/risk_comm_v1/manifests/smallest_effects.json \
  --power-output data/outputs/experiments/risk_comm_v1/manifests/power_assumptions.json

uv run risk-comm analysis simulate-power \
  --smallest-effect-manifest data/outputs/experiments/risk_comm_v1/manifests/smallest_effects.json \
  --power-assumption-manifest data/outputs/experiments/risk_comm_v1/manifests/power_assumptions.json \
  --output data/outputs/experiments/risk_comm_v1/results/power_simulation.json
```

The report contains power only for the two primary selective-communication tests. For the secondary outcomes it reports expected 95% interval half-widths, calculated as \(1.96s/\sqrt{20}\) from the calibration-estimated scenario-contrast standard deviations; these are precision summaries, not power targets.

## Frozen inference

The primary panel uses:

- two-sided scenario-level paired sign-flip tests;
- exactly 100,000 seeded permutations;
- Holm adjustment across H1 and H2 only; and
- exactly 10,000 use-case-stratified scenario-bootstrap draws for 95% intervals.

The secondary panel uses the same paired effect definitions and 10,000-draw intervals without p-values.

```bash
uv run risk-comm analysis run \
  --analysis-input data/outputs/experiments/risk_comm_v1/results/analysis_input.jsonl \
  --fact-analysis-input data/outputs/experiments/risk_comm_v1/results/fact_analysis_input.jsonl \
  --human-reference-analysis-input data/outputs/experiments/risk_comm_v1/results/human_reference.jsonl \
  --missingness-report data/outputs/experiments/risk_comm_v1/results/missingness.json \
  --experiment-manifest data/outputs/experiments/risk_comm_v1/manifests/experiment_manifest.json \
  --preregistration-manifest data/outputs/experiments/risk_comm_v1/manifests/preregistration.json \
  --annotation-sample-manifest data/outputs/experiments/risk_comm_v1/manifests/evaluation_annotation_sample.json \
  --scoring-validation-report data/outputs/experiments/risk_comm_v1/results/scoring_validation.json \
  --validation-disposition-manifest data/outputs/experiments/risk_comm_v1/manifests/validation_disposition.json \
  --analysis-plan docs/research-plan/RESEARCH_PLAN.md \
  --protocol-deviations data/outputs/experiments/risk_comm_v1/manifests/protocol_deviations.json \
  --confirmatory-summary data/outputs/experiments/risk_comm_v1/results/confirmatory_summary.json \
  --secondary-summary data/outputs/experiments/risk_comm_v1/results/secondary_summary.json \
  --r-input-csv data/outputs/experiments/risk_comm_v1/results/r_input.csv \
  --r-output-summary data/outputs/experiments/risk_comm_v1/results/r_summary.json \
  --assets-dir data/outputs/experiments/risk_comm_v1/assets
```

If a blinded disposition requires full manual scoring, add `--manual-analysis-input <path>`.

The stable assets are:

- `risk_comm_v1_confirmatory_table.tex`: H1/H2 selective-communication estimates, intervals, and adjusted p-values;
- `risk_comm_v1_secondary_table.tex`: presentation/factual-accuracy and checkpoint estimates with intervals only; and
- `risk_comm_v1_figure.pdf`: the two primary effects.

The power simulation in `src/analysis/power.py` models the equal-weight coverage and specificity components and the existing two-test Holm family. Calibration results determine the reported expected precision for presentation style and factual inaccuracy; the study is not powered around the secondary outcomes.

There are no equal-domain, leave-one-domain-out, spontaneous-change, or mixed-composite analyses in the active implementation.
