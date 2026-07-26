# `risk_comm_v1` runbook

`risk_comm_v1` is the 240-conversation confirmatory experiment: 20 V0.11.0 R1–R2 scenarios × three frozen models × ample/tight budget ×
neutral/concerned cue. Each scenario supplies one fixed four-fact list and seed-owned option order; order is counterbalanced across scenarios but is not
an experimental factor. The initial composite supports H1 and H2; cumulative scoring is secondary.

## Offline plan

Freeze the separately identified calibration, primary, and two exploratory manifests from the same authenticated protocol inputs:

```bash
uv run risk-comm experiment build-manifests \
  --accepted-scenario-manifest data/inputs/scenarios/v0.11.0/accepted_scenario_manifest.json \
  --evaluated-model-manifest data/outputs/experiments/risk_comm_v1/manifests/evaluated_models.json \
  --prompt-review-manifest data/outputs/experiments/risk_comm_v1/manifests/prompt_review.json \
  --scoring-execution-manifest data/outputs/experiments/risk_comm_v1/manifests/scoring_execution.json \
  --word-budget-manifest data/outputs/experiments/risk_comm_v1/manifests/word_budgets.json \
  --frozen-by <researcher-id> \
  --calibration-output data/outputs/experiments/risk_comm_calibration_v1/checkpoints/calibration_manifest.json \
  --experiment-output data/outputs/experiments/risk_comm_v1/manifests/experiment_manifest.json \
  --material-priority-output data/outputs/experiments/material_priority_v1/manifests/experiment_manifest.json \
  --brevity-locus-output data/outputs/experiments/brevity_locus_v1/manifests/experiment_manifest.json
```

```bash
uv run risk-comm experiment build-plan \
  --accepted-root data/inputs/scenarios/v0.11.0/accepted \
  --experiment-manifest data/outputs/experiments/risk_comm_v1/manifests/experiment_manifest.json \
  --accepted-scenario-manifest data/inputs/scenarios/v0.11.0/accepted_scenario_manifest.json \
  --evaluated-model-manifest data/outputs/experiments/risk_comm_v1/manifests/evaluated_models.json \
  --prompt-review-manifest data/outputs/experiments/risk_comm_v1/manifests/prompt_review.json \
  --scoring-execution-manifest data/outputs/experiments/risk_comm_v1/manifests/scoring_execution.json \
  --word-budget-manifest data/outputs/experiments/risk_comm_v1/manifests/word_budgets.json \
  --config-output data/outputs/experiments/risk_comm_v1/config.json \
  --output data/outputs/experiments/risk_comm_v1/checkpoints/run_plan.jsonl
```

The plan builder refuses counts other than 240 and validates every four-cell prompt block, natural follow-up, cue assignment, visible-fact hash,
seeded position, and run identifier.

## Paid execution gate

Create and inspect the immutable cost report, then record a separate maximum-cost approval:

```bash
uv run risk-comm experiment dry-run \
  --run-plan data/outputs/experiments/risk_comm_v1/checkpoints/run_plan.jsonl \
  --config data/outputs/experiments/risk_comm_v1/config.json \
  --pricing <pricing-assumptions.json> \
  --output data/outputs/experiments/risk_comm_v1/checkpoints/dry_run_cost.json

uv run risk-comm experiment approve \
  --dry-run-report data/outputs/experiments/risk_comm_v1/checkpoints/dry_run_cost.json \
  --approved-maximum-cost-usd <maximum-cost> \
  --approved-by <researcher-id> \
  --output data/outputs/experiments/risk_comm_v1/checkpoints/paid_approval.json \
  --approve
```

`risk-comm experiment run` remains unavailable without both linked artifacts, the frozen preregistration, and `--execute-paid`. Implementation and offline testing must not pass that gate.

The exact paid command is:

```bash
uv run risk-comm experiment run \
  --run-plan data/outputs/experiments/risk_comm_v1/checkpoints/run_plan.jsonl \
  --config data/outputs/experiments/risk_comm_v1/config.json \
  --experiment-manifest data/outputs/experiments/risk_comm_v1/manifests/experiment_manifest.json \
  --accepted-scenario-manifest data/inputs/scenarios/v0.11.0/accepted_scenario_manifest.json \
  --accepted-root data/inputs/scenarios/v0.11.0/accepted \
  --evaluated-model-manifest data/outputs/experiments/risk_comm_v1/manifests/evaluated_models.json \
  --word-budget-manifest data/outputs/experiments/risk_comm_v1/manifests/word_budgets.json \
  --preregistration-manifest data/outputs/experiments/risk_comm_v1/manifests/preregistration.json \
  --dry-run-report data/outputs/experiments/risk_comm_v1/checkpoints/dry_run_cost.json \
  --approval data/outputs/experiments/risk_comm_v1/checkpoints/paid_approval.json \
  --results data/outputs/experiments/risk_comm_v1/results/<YYYYMMDDTHHMMSS>_results.jsonl \
  --log data/outputs/experiments/risk_comm_v1/logs/<YYYYMMDDTHHMMSS>_run.log \
  --cache-dir data/outputs/experiments/risk_comm_v1/cache \
  --execute-paid
```

## Analysis inputs

After condition-blind scoring and any blinded manual resolutions, join the full terminal ledger into initial and cumulative rows:

```bash
uv run risk-comm analysis build-inputs \
  --transcripts data/outputs/experiments/risk_comm_v1/results/<YYYYMMDDTHHMMSS>_results.jsonl \
  --scored-bundles data/outputs/experiments/risk_comm_v1/results/scored_conversations.jsonl \
  --manual-resolutions data/outputs/experiments/risk_comm_v1/results/manual_scoring_resolutions.jsonl \
  --experiment-manifest data/outputs/experiments/risk_comm_v1/manifests/experiment_manifest.json \
  --accepted-root data/inputs/scenarios/v0.11.0/accepted \
  --accepted-scenario-manifest data/inputs/scenarios/v0.11.0/accepted_scenario_manifest.json \
  --scoring-execution-manifest data/outputs/experiments/risk_comm_v1/manifests/scoring_execution.json \
  --output data/outputs/experiments/risk_comm_v1/results/analysis_input.jsonl \
  --fact-analysis-output data/outputs/experiments/risk_comm_v1/results/fact_analysis_input.jsonl \
  --missingness-report data/outputs/experiments/risk_comm_v1/results/missingness.json
```

The builder refuses anything other than a complete 240-unit terminal ledger and retains exhausted calls as typed missing records.

## Outputs

- config: `data/outputs/experiments/risk_comm_v1/config.json`
- raw results: `data/outputs/experiments/risk_comm_v1/results/<YYYYMMDDTHHMMSS>_results.jsonl`
- logs: `data/outputs/experiments/risk_comm_v1/logs/<YYYYMMDDTHHMMSS>_run.log`
- checkpoints: `data/outputs/experiments/risk_comm_v1/checkpoints/`
- assets: `data/outputs/experiments/risk_comm_v1/assets/risk_comm_v1_table.tex` and `risk_comm_v1_figure.pdf`

Relevant code: `src/experiments/scenario_runner.py`, `src/prompts/experiment.py`, `src/data_models/prompt_controls.py`, `src/scoring/metrics.py`, and `src/analysis/sign_flip.py`.
