# `brevity_locus_v1` runbook

This separately reported exploratory experiment runs all 40 scenarios × three models under the neutral cue, with no system word cap and the user sentence “Please keep the answer brief.”: exactly 120 conversations and 240 responses. Its paired comparison is user-requested brevity minus the matching `risk_comm_v1` tight-budget/neutral observation, with scenario-cluster 95% intervals and no confirmatory p-values.

## Offline plan and paid gate

Use the shared `risk-comm experiment build-exploratory-plans` command in [material_priority_v1.md](material_priority_v1.md). It writes this experiment's separate manifest-bound `config.json` and `checkpoints/run_plan.jsonl`; validation requires the user brevity sentence and rejects a system word-limit instruction.

Before execution, create this experiment's own cost report and approval:

```bash
uv run risk-comm experiment dry-run \
  --run-plan data/outputs/experiments/brevity_locus_v1/checkpoints/run_plan.jsonl \
  --config data/outputs/experiments/brevity_locus_v1/config.json \
  --pricing <pricing-assumptions.json> \
  --output data/outputs/experiments/brevity_locus_v1/checkpoints/dry_run_cost.json

uv run risk-comm experiment approve \
  --dry-run-report data/outputs/experiments/brevity_locus_v1/checkpoints/dry_run_cost.json \
  --approved-maximum-cost-usd <maximum-cost> \
  --approved-by <researcher-id> \
  --output data/outputs/experiments/brevity_locus_v1/checkpoints/paid_approval.json \
  --approve
```

Only then may `risk-comm experiment run` be called with this experiment's plan, config, manifest, cost report, approval, timestamp-matched result/log paths, and `--execute-paid`.

```bash
uv run risk-comm experiment run \
  --run-plan data/outputs/experiments/brevity_locus_v1/checkpoints/run_plan.jsonl \
  --config data/outputs/experiments/brevity_locus_v1/config.json \
  --experiment-manifest data/outputs/experiments/brevity_locus_v1/manifests/experiment_manifest.json \
  --accepted-scenario-manifest data/inputs/scenarios/v0.5.2/accepted_scenario_manifest.json \
  --accepted-root data/inputs/scenarios/v0.5.2/accepted \
  --evaluated-model-manifest data/outputs/experiments/risk_comm_v1/manifests/evaluated_models.json \
  --word-budget-manifest data/outputs/experiments/risk_comm_v1/manifests/word_budgets.json \
  --dry-run-report data/outputs/experiments/brevity_locus_v1/checkpoints/dry_run_cost.json \
  --approval data/outputs/experiments/brevity_locus_v1/checkpoints/paid_approval.json \
  --results data/outputs/experiments/brevity_locus_v1/results/<YYYYMMDDTHHMMSS>_results.jsonl \
  --log data/outputs/experiments/brevity_locus_v1/logs/<YYYYMMDDTHHMMSS>_run.log \
  --cache-dir data/outputs/experiments/brevity_locus_v1/cache \
  --execute-paid
```

## Scoring and analysis

Run condition-blind scoring with the `brevity_locus_v1` manifest, then build its complete 120-unit analysis ledger:

```bash
uv run risk-comm scoring run \
  --backend src.experiments.openrouter_scoring:create_openrouter_scoring_backend \
  --transcripts data/outputs/experiments/brevity_locus_v1/results/<YYYYMMDDTHHMMSS>_results.jsonl \
  --accepted-root data/inputs/scenarios/v0.5.2/accepted \
  --accepted-scenario-manifest data/inputs/scenarios/v0.5.2/accepted_scenario_manifest.json \
  --experiment-manifest data/outputs/experiments/brevity_locus_v1/manifests/experiment_manifest.json \
  --scoring-execution-manifest data/outputs/experiments/risk_comm_v1/manifests/scoring_execution.json \
  --results-dir data/outputs/experiments/brevity_locus_v1/results \
  --execute-paid

uv run risk-comm analysis build-inputs \
  --transcripts data/outputs/experiments/brevity_locus_v1/results/<YYYYMMDDTHHMMSS>_results.jsonl \
  --scored-bundles data/outputs/experiments/brevity_locus_v1/results/scored_conversations.jsonl \
  --manual-resolutions data/outputs/experiments/brevity_locus_v1/results/manual_scoring_resolutions.jsonl \
  --experiment-manifest data/outputs/experiments/brevity_locus_v1/manifests/experiment_manifest.json \
  --accepted-root data/inputs/scenarios/v0.5.2/accepted \
  --accepted-scenario-manifest data/inputs/scenarios/v0.5.2/accepted_scenario_manifest.json \
  --scoring-execution-manifest data/outputs/experiments/risk_comm_v1/manifests/scoring_execution.json \
  --output data/outputs/experiments/brevity_locus_v1/results/analysis_input.jsonl \
  --fact-analysis-output data/outputs/experiments/brevity_locus_v1/results/fact_analysis_input.jsonl \
  --missingness-report data/outputs/experiments/brevity_locus_v1/results/missingness.json

uv run risk-comm analysis run-exploratory \
  --experiment-name brevity_locus_v1 \
  --analysis-input data/outputs/experiments/brevity_locus_v1/results/analysis_input.jsonl \
  --primary-reference-input data/outputs/experiments/risk_comm_v1/results/analysis_input.jsonl \
  --validation-disposition-manifest data/outputs/experiments/risk_comm_v1/manifests/validation_disposition.json \
  --output-summary data/outputs/experiments/brevity_locus_v1/results/exploratory_summary.json \
  --assets-dir data/outputs/experiments/brevity_locus_v1/assets
```

If the frozen validation disposition requires a fully manual domain, also provide the matching full-sample manual analysis inputs for both this experiment and the primary reference. Stable outputs are `assets/brevity_locus_v1_table.tex` and `assets/brevity_locus_v1_domain_summary.csv`.

Relevant code: `src/experiments/scenario_runner.py`, `src/cli/commands/experiment/build_exploratory_plans.py`, `src/analysis/exploratory.py`, `src/cli/commands/analysis/run_exploratory.py`, and `src/experiments/exploratory_assets.py`.
