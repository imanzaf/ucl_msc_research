# `material_priority_v1` runbook

This separately reported exploratory experiment runs all 40 scenarios × three models × both cue conditions under the frozen tight system budget: exactly 240 conversations and 480 responses. It uses the same initial composite and domain definitions as `risk_comm_v1`, with paired scenario-cluster 95% intervals and no confirmatory p-values.

## Offline plan

`risk-comm experiment build-manifests` writes its separate frozen manifest to `data/outputs/experiments/material_priority_v1/manifests/experiment_manifest.json`. Build both exploratory plans from that manifest family:

```bash
uv run risk-comm experiment build-exploratory-plans \
  --accepted-root data/inputs/scenarios/v0.5.2/accepted \
  --accepted-scenario-manifest data/inputs/scenarios/v0.5.2/accepted_scenario_manifest.json \
  --word-budget-manifest data/outputs/experiments/risk_comm_v1/manifests/word_budgets.json \
  --material-priority-manifest data/outputs/experiments/material_priority_v1/manifests/experiment_manifest.json \
  --material-priority-config data/outputs/experiments/material_priority_v1/config.json \
  --material-priority-plan data/outputs/experiments/material_priority_v1/checkpoints/run_plan.jsonl \
  --brevity-locus-manifest data/outputs/experiments/brevity_locus_v1/manifests/experiment_manifest.json \
  --brevity-locus-config data/outputs/experiments/brevity_locus_v1/config.json \
  --brevity-locus-plan data/outputs/experiments/brevity_locus_v1/checkpoints/run_plan.jsonl
```

## Paid execution gate

Generate and inspect the immutable cost report before creating a researcher approval:

```bash
uv run risk-comm experiment dry-run \
  --run-plan data/outputs/experiments/material_priority_v1/checkpoints/run_plan.jsonl \
  --config data/outputs/experiments/material_priority_v1/config.json \
  --pricing <pricing-assumptions.json> \
  --output data/outputs/experiments/material_priority_v1/checkpoints/dry_run_cost.json

uv run risk-comm experiment approve \
  --dry-run-report data/outputs/experiments/material_priority_v1/checkpoints/dry_run_cost.json \
  --approved-maximum-cost-usd <maximum-cost> \
  --approved-by <researcher-id> \
  --output data/outputs/experiments/material_priority_v1/checkpoints/paid_approval.json \
  --approve
```

Only after that separate approval may `risk-comm experiment run` be called with this experiment's plan, config, manifest, cost report, approval, timestamp-matched result/log paths, and `--execute-paid`. A primary preregistration manifest is not used for this exploratory run.

```bash
uv run risk-comm experiment run \
  --run-plan data/outputs/experiments/material_priority_v1/checkpoints/run_plan.jsonl \
  --config data/outputs/experiments/material_priority_v1/config.json \
  --experiment-manifest data/outputs/experiments/material_priority_v1/manifests/experiment_manifest.json \
  --accepted-scenario-manifest data/inputs/scenarios/v0.5.2/accepted_scenario_manifest.json \
  --accepted-root data/inputs/scenarios/v0.5.2/accepted \
  --evaluated-model-manifest data/outputs/experiments/risk_comm_v1/manifests/evaluated_models.json \
  --word-budget-manifest data/outputs/experiments/risk_comm_v1/manifests/word_budgets.json \
  --dry-run-report data/outputs/experiments/material_priority_v1/checkpoints/dry_run_cost.json \
  --approval data/outputs/experiments/material_priority_v1/checkpoints/paid_approval.json \
  --results data/outputs/experiments/material_priority_v1/results/<YYYYMMDDTHHMMSS>_results.jsonl \
  --log data/outputs/experiments/material_priority_v1/logs/<YYYYMMDDTHHMMSS>_run.log \
  --cache-dir data/outputs/experiments/material_priority_v1/cache \
  --execute-paid
```

## Scoring and analysis

Score under the shared frozen condition-blind scoring contract, then join both checkpoints:

```bash
uv run risk-comm scoring run \
  --backend src.experiments.openrouter_scoring:create_openrouter_scoring_backend \
  --transcripts data/outputs/experiments/material_priority_v1/results/<YYYYMMDDTHHMMSS>_results.jsonl \
  --accepted-root data/inputs/scenarios/v0.5.2/accepted \
  --accepted-scenario-manifest data/inputs/scenarios/v0.5.2/accepted_scenario_manifest.json \
  --experiment-manifest data/outputs/experiments/material_priority_v1/manifests/experiment_manifest.json \
  --scoring-execution-manifest data/outputs/experiments/risk_comm_v1/manifests/scoring_execution.json \
  --results-dir data/outputs/experiments/material_priority_v1/results \
  --execute-paid

uv run risk-comm analysis build-inputs \
  --transcripts data/outputs/experiments/material_priority_v1/results/<YYYYMMDDTHHMMSS>_results.jsonl \
  --scored-bundles data/outputs/experiments/material_priority_v1/results/scored_conversations.jsonl \
  --manual-resolutions data/outputs/experiments/material_priority_v1/results/manual_scoring_resolutions.jsonl \
  --experiment-manifest data/outputs/experiments/material_priority_v1/manifests/experiment_manifest.json \
  --accepted-root data/inputs/scenarios/v0.5.2/accepted \
  --accepted-scenario-manifest data/inputs/scenarios/v0.5.2/accepted_scenario_manifest.json \
  --scoring-execution-manifest data/outputs/experiments/risk_comm_v1/manifests/scoring_execution.json \
  --output data/outputs/experiments/material_priority_v1/results/analysis_input.jsonl \
  --fact-analysis-output data/outputs/experiments/material_priority_v1/results/fact_analysis_input.jsonl \
  --missingness-report data/outputs/experiments/material_priority_v1/results/missingness.json

uv run risk-comm analysis run-exploratory \
  --experiment-name material_priority_v1 \
  --analysis-input data/outputs/experiments/material_priority_v1/results/analysis_input.jsonl \
  --validation-disposition-manifest data/outputs/experiments/risk_comm_v1/manifests/validation_disposition.json \
  --output-summary data/outputs/experiments/material_priority_v1/results/exploratory_summary.json \
  --assets-dir data/outputs/experiments/material_priority_v1/assets
```

Use an empty `manual_scoring_resolutions.jsonl` only when no conversations were routed to blinded manual scoring. Stable outputs are `assets/material_priority_v1_table.tex` and `assets/material_priority_v1_domain_summary.csv`.

Relevant code: `src/experiments/scenario_runner.py`, `src/cli/commands/experiment/build_exploratory_plans.py`, `src/analysis/exploratory.py`, `src/cli/commands/analysis/run_exploratory.py`, and `src/experiments/exploratory_assets.py`.
