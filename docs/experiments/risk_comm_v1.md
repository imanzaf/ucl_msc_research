# risk_comm_v1 execution runbook

## Layout

The experiment lives entirely under `data/outputs/experiments/risk_comm_v1/`:

```text
config.json
results/<YYYYMMDDTHHMMSS>_results.jsonl
cache/
logs/<YYYYMMDDTHHMMSS>_run.log
assets/risk_comm_v1_table.tex
assets/risk_comm_v1_figure.pdf
checkpoints/
```

## Pre-execution gates

Do not build or run the main plan until accepted scenario, word-budget, prompt-review, model, scoring, analysis, and preregistration manifests are frozen and mutually hash-linked.

Freeze exact scoring-judge versions, then construct the calibration/main experiment manifests:

```bash
uv run risk-comm scoring build-manifest \
  --evaluated-model-manifest <evaluated_model_manifest.json> \
  --judge-snapshot <judge_snapshot.json> \
  --fact-order-seed 7 --max-retries 2 \
  --backoff-seconds 1 --backoff-seconds 2 \
  --frozen-by <researcher_id> \
  --output <scoring_execution_manifest.json>

uv run risk-comm experiment build-manifests \
  --accepted-scenario-manifest <accepted_scenario_manifest.json> \
  --evaluated-model-manifest <evaluated_model_manifest.json> \
  --prompt-review-manifest <prompt_review_manifest.json> \
  --scoring-execution-manifest <scoring_execution_manifest.json> \
  --word-budget-manifest <word_budget_manifest.json> \
  --randomisation-seed 7 --max-retries 2 \
  --backoff-seconds 1 --backoff-seconds 2 \
  --frozen-by <researcher_id> \
  --calibration-output data/outputs/experiments/risk_comm_calibration_v1/checkpoints/calibration_manifest.json \
  --experiment-output data/outputs/experiments/risk_comm_v1/checkpoints/experiment_manifest.json
```

Build the exact plan:

```bash
uv run risk-comm experiment build-plan \
  --experiment-manifest <experiment_manifest.json> \
  --accepted-scenario-manifest <accepted_scenario_manifest.json> \
  --evaluated-model-manifest <evaluated_model_manifest.json> \
  --prompt-review-manifest <prompt_review_manifest.json> \
  --scoring-execution-manifest <scoring_execution_manifest.json> \
  --word-budget-manifest <word_budget_manifest.json> \
  --config-output data/outputs/experiments/risk_comm_v1/config.json \
  --output data/outputs/experiments/risk_comm_v1/checkpoints/run_plan.jsonl
```

The builder writes the full immutable config before the plan, refuses any count other than 960 conversations/1,920 responses, requires canonical source order A, and validates byte-level factor isolation in every eight-cell block.

Build the preregistration manifest before the dry run; it points only backward to frozen calibration inputs, the exact config/plan, effects, power report, retry policy, analysis commit/plan, and deviation policy:

```bash
uv run risk-comm experiment preregister \
  --experiment-manifest data/outputs/experiments/risk_comm_v1/checkpoints/experiment_manifest.json \
  --experiment-config data/outputs/experiments/risk_comm_v1/config.json \
  --run-plan data/outputs/experiments/risk_comm_v1/checkpoints/run_plan.jsonl \
  --accepted-scenario-manifest data/inputs/scenarios/v0.5.1/accepted_scenario_manifest.json \
  --accepted-root data/inputs/scenarios/v0.5.1/accepted \
  --evaluated-model-manifest <evaluated_model_manifest.json> \
  --word-budget-manifest data/outputs/experiments/risk_comm_v1/checkpoints/word_budget_manifest.json \
  --calibration-annotation-sample-manifest data/outputs/experiments/risk_comm_calibration_v1/checkpoints/calibration_annotation_sample_manifest.json \
  --power-report data/outputs/experiments/risk_comm_v1/checkpoints/power_simulation_report.json \
  --smallest-effect-manifest data/outputs/experiments/risk_comm_v1/checkpoints/smallest_effect_manifest.json \
  --analysis-plan docs/research-plan/RESEARCH_PLAN.md \
  --protocol-deviation-policy docs/research-plan/RESEARCH_PLAN.md \
  --frozen-by <researcher_id> \
  --output data/outputs/experiments/risk_comm_v1/checkpoints/preregistration_manifest.json
```

Create the dry-run report using a strict `1.0.0` pricing JSON whose `models` object is keyed by exact model ID and supplies nonnegative `input_per_million_usd` and `output_per_million_usd` values:

```bash
uv run risk-comm experiment dry-run \
  --run-plan data/outputs/experiments/risk_comm_v1/checkpoints/run_plan.jsonl \
  --config data/outputs/experiments/risk_comm_v1/config.json \
  --pricing <pricing.json> \
  --output data/outputs/experiments/risk_comm_v1/checkpoints/dry_run_report.json
```

Create an explicit `PaidExecutionApproval` record bound to that report hash and a researcher-chosen maximum cost:

```bash
uv run risk-comm experiment approve \
  --dry-run-report data/outputs/experiments/risk_comm_v1/checkpoints/dry_run_report.json \
  --approved-maximum-cost-usd <maximum> \
  --approved-by <researcher_id> \
  --output data/outputs/experiments/risk_comm_v1/checkpoints/paid_execution_approval.json \
  --approve
```

The runner rejects a missing, false, mismatched, or under-budgeted approval.

After execution, finalise even an empty deviation register with `risk-comm experiment finalize-deviations`; this later record binds backward to the frozen preregistration rather than creating a circular or impossible preregistration dependency.

## Main execution

```bash
uv run risk-comm experiment run \
  --run-plan data/outputs/experiments/risk_comm_v1/checkpoints/run_plan.jsonl \
  --config data/outputs/experiments/risk_comm_v1/config.json \
  --experiment-manifest data/outputs/experiments/risk_comm_v1/checkpoints/experiment_manifest.json \
  --accepted-scenario-manifest data/inputs/scenarios/v0.5.1/accepted_scenario_manifest.json \
  --accepted-root data/inputs/scenarios/v0.5.1/accepted \
  --evaluated-model-manifest <evaluated_model_manifest.json> \
  --word-budget-manifest <word_budget_manifest.json> \
  --preregistration-manifest data/outputs/experiments/risk_comm_v1/checkpoints/preregistration_manifest.json \
  --dry-run-report data/outputs/experiments/risk_comm_v1/checkpoints/dry_run_report.json \
  --approval data/outputs/experiments/risk_comm_v1/checkpoints/paid_execution_approval.json \
  --results data/outputs/experiments/risk_comm_v1/results/<timestamp>_results.jsonl \
  --log data/outputs/experiments/risk_comm_v1/logs/<timestamp>_run.log \
  --cache-dir data/outputs/experiments/risk_comm_v1/cache \
  --execute-paid
```

Before any call, the runner deterministically rebuilds the supplied plan from the frozen accepted scenarios, exact model snapshots, budgets, active prompts, and seed. Each outcome is persisted immediately. Resume skips existing terminal run-unit IDs. Every retry uses the same request hash. The fixed follow-up is cue-free and identical across all cells. Exhausted calls remain terminal missing outcomes with reasons; they are never silently replaced.

After all 960 terminal records exist, generate the three self-hashed completion/version/token summaries:

```bash
uv run risk-comm experiment summarize \
  --transcripts data/outputs/experiments/risk_comm_v1/results/<timestamp>_results.jsonl \
  --output data/outputs/experiments/risk_comm_v1/results/model_summaries.jsonl
```

Scoring, annotation, gates, analysis, and assets are documented in `docs/experiments/scoring.md`, `docs/experiments/review_and_annotation.md`, and `docs/experiments/analysis.md`.
