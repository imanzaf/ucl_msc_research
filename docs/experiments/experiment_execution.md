# Experiment execution

This runbook covers model execution for the C1 diagnostic, rubric-development calibration, the confirmatory experiment, and both exploratory
experiments. Scenario preparation is documented in [scenario_workflow.md](scenario_workflow.md); scoring and analysis begin only after the relevant
model run is complete.

## Experiment matrix

| Experiment | Purpose | Conversations |
|---|---|---:|
| `c1_llama_2x2_v8` | Eighteen-call rescoring of the 40 completed V3 Llama C1 conversations | 40 |
| `risk_comm_calibration_v1` | Ten C1 scenarios × three models × the four primary cells | 120 |
| `risk_comm_v1` | Twenty R1–R2 scenarios × three models × the four primary cells | 240 |
| `material_priority_v1` | Twenty R1–R2 scenarios × three models × concise guidance × two seed-authored queries | 120 |
| `brevity_locus_v1` | Twenty R1–R2 scenarios × three models × neutral query with user-requested brevity | 60 |

The baseline system prompt has no response-length instruction. The concise condition adds exactly `Keep your answers concise.` under Guidance.
Neither condition has a numeric word limit.

The complete evaluated-model contract is defined in `src/prompts/templates/experiment.jinja2`. Its `---system---`, `---user---`, and
`---follow-up---` sections keep the initial pair and later user turn together, with all dynamic formatting visible in the template. The V10 prompt
package hashes the complete template source through `src/prompts/template_utils.py`.

## C1 single-model diagnostic

Prepare and run the redesigned scoring diagnostic from the completed Llama C1 evaluated-model outputs:

```bash
uv run risk-comm scoring run-c1 \
  --source-experiment-name c1_llama_2x2_v3 \
  --frozen-by <researcher-id> \
  --execute-paid
```

The command authenticates the active C1 scenarios and prompt hash, requires all 40 source transcripts to be completed Llama outputs, and writes a
hash-bound source manifest under `data/outputs/experiments/c1_llama_2x2_v8/checkpoints/`. It makes no new evaluated-model calls. It writes the six
scoring-call caches and scored bundles under V4 and regenerates the stable V4 table. Repeating the command resumes only unfinished scoring calls.
Validate the redesigned output before freezing the shared scoring contract:

```bash
uv run risk-comm scoring validate-c1 \
  --scored-bundles data/outputs/experiments/c1_llama_2x2_v8/results/scored_conversations.jsonl \
  --scoring-calls data/outputs/experiments/c1_llama_2x2_v8/results/scoring_calls.jsonl \
  --manual-queue data/outputs/experiments/c1_llama_2x2_v8/results/manual_scoring_queue.jsonl \
  --output data/outputs/experiments/c1_llama_2x2_v8/checkpoints/scoring_diagnostic.json

uv run risk-comm scoring build-manifest \
  --evaluated-model-manifest data/outputs/experiments/risk_comm_v1/manifests/evaluated_models.json \
  --judge-snapshot data/outputs/experiments/risk_comm_v1/manifests/judge_snapshot.json \
  --c1-diagnostic-report data/outputs/experiments/c1_llama_2x2_v8/checkpoints/scoring_diagnostic.json \
  --frozen-by <researcher-id> \
  --output data/outputs/experiments/risk_comm_v1/manifests/scoring_execution.json
```

Validation requires all 40 bundles, all 720 successful response-contract-fact calls, eighteen independent provenances per conversation, isolated initial and
follow-up inputs, and no manual queue. The C1 diagnostic checks the new scoring contract; it does not replace three-model calibration.

## Freeze shared manifests

After scenario acceptance, prompt review, model selection, and budget calibration, build the manifests for calibration and all three registered
experiments:

```bash
uv run risk-comm experiment build-manifests \
  --accepted-scenario-manifest data/inputs/scenarios/v2.0.0/accepted_scenario_manifest.json \
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

## Three-model calibration

Build the complete 120-conversation plan:

```bash
uv run risk-comm calibration build-plan \
  --calibration-manifest data/outputs/experiments/risk_comm_calibration_v1/checkpoints/calibration_manifest.json \
  --accepted-root data/inputs/scenarios/v2.0.0/accepted \
  --accepted-scenario-manifest data/inputs/scenarios/v2.0.0/accepted_scenario_manifest.json \
  --evaluated-model-manifest data/outputs/experiments/risk_comm_v1/manifests/evaluated_models.json \
  --prompt-review-manifest data/outputs/experiments/risk_comm_v1/manifests/prompt_review.json \
  --word-budget-manifest data/outputs/experiments/risk_comm_v1/manifests/word_budgets.json
```

Run or resume it:

```bash
uv run risk-comm calibration run \
  --calibration-manifest data/outputs/experiments/risk_comm_calibration_v1/checkpoints/calibration_manifest.json \
  --accepted-root data/inputs/scenarios/v2.0.0/accepted \
  --accepted-scenario-manifest data/inputs/scenarios/v2.0.0/accepted_scenario_manifest.json \
  --evaluated-model-manifest data/outputs/experiments/risk_comm_v1/manifests/evaluated_models.json \
  --prompt-review-manifest data/outputs/experiments/risk_comm_v1/manifests/prompt_review.json \
  --word-budget-manifest data/outputs/experiments/risk_comm_v1/manifests/word_budgets.json \
  --results data/outputs/experiments/risk_comm_calibration_v1/results/<YYYYMMDDTHHMMSS>_results.jsonl \
  --log data/outputs/experiments/risk_comm_calibration_v1/logs/<YYYYMMDDTHHMMSS>_run.log \
  --execute-paid
```

Calibration may refine rubric wording and judge selection. Held-out R1–R2 artifacts and results must remain unavailable until the scoring-execution
and main experiment manifests are frozen.

## Confirmatory experiment

Build the complete 240-conversation plan:

```bash
uv run risk-comm experiment build-plan \
  --accepted-root data/inputs/scenarios/v2.0.0/accepted \
  --experiment-manifest data/outputs/experiments/risk_comm_v1/manifests/experiment_manifest.json \
  --accepted-scenario-manifest data/inputs/scenarios/v2.0.0/accepted_scenario_manifest.json \
  --evaluated-model-manifest data/outputs/experiments/risk_comm_v1/manifests/evaluated_models.json \
  --prompt-review-manifest data/outputs/experiments/risk_comm_v1/manifests/prompt_review.json \
  --scoring-execution-manifest data/outputs/experiments/risk_comm_v1/manifests/scoring_execution.json \
  --word-budget-manifest data/outputs/experiments/risk_comm_v1/manifests/word_budgets.json \
  --config-output data/outputs/experiments/risk_comm_v1/config.json \
  --output data/outputs/experiments/risk_comm_v1/checkpoints/run_plan.jsonl
```

Create and inspect the immutable cost report, then record the separate maximum-cost approval:

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

Execute only after the report and approval have been checked:

```bash
uv run risk-comm experiment run \
  --run-plan data/outputs/experiments/risk_comm_v1/checkpoints/run_plan.jsonl \
  --config data/outputs/experiments/risk_comm_v1/config.json \
  --experiment-manifest data/outputs/experiments/risk_comm_v1/manifests/experiment_manifest.json \
  --accepted-scenario-manifest data/inputs/scenarios/v2.0.0/accepted_scenario_manifest.json \
  --accepted-root data/inputs/scenarios/v2.0.0/accepted \
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

## Exploratory experiments

Build both plans together from their separately frozen manifests:

```bash
uv run risk-comm experiment build-exploratory-plans \
  --accepted-root data/inputs/scenarios/v2.0.0/accepted \
  --accepted-scenario-manifest data/inputs/scenarios/v2.0.0/accepted_scenario_manifest.json \
  --word-budget-manifest data/outputs/experiments/risk_comm_v1/manifests/word_budgets.json \
  --material-priority-manifest data/outputs/experiments/material_priority_v1/manifests/experiment_manifest.json \
  --material-priority-config data/outputs/experiments/material_priority_v1/config.json \
  --material-priority-plan data/outputs/experiments/material_priority_v1/checkpoints/run_plan.jsonl \
  --brevity-locus-manifest data/outputs/experiments/brevity_locus_v1/manifests/experiment_manifest.json \
  --brevity-locus-config data/outputs/experiments/brevity_locus_v1/config.json \
  --brevity-locus-plan data/outputs/experiments/brevity_locus_v1/checkpoints/run_plan.jsonl
```

For each `<experiment-name>` (`material_priority_v1` or `brevity_locus_v1`), create its own cost report and approval:

```bash
uv run risk-comm experiment dry-run \
  --run-plan data/outputs/experiments/<experiment-name>/checkpoints/run_plan.jsonl \
  --config data/outputs/experiments/<experiment-name>/config.json \
  --pricing <pricing-assumptions.json> \
  --output data/outputs/experiments/<experiment-name>/checkpoints/dry_run_cost.json

uv run risk-comm experiment approve \
  --dry-run-report data/outputs/experiments/<experiment-name>/checkpoints/dry_run_cost.json \
  --approved-maximum-cost-usd <maximum-cost> \
  --approved-by <researcher-id> \
  --output data/outputs/experiments/<experiment-name>/checkpoints/paid_approval.json \
  --approve
```

Then execute that experiment with its own plan, config, manifest, result, log, cache, cost report, approval, and `--execute-paid`. Exploratory
experiments use paired scenario-cluster intervals without confirmatory p-values.

## Outputs and implementation

Every experiment writes its `config.json` before execution and keeps timestamped raw results and logs alongside resumable caches, checkpoints, and
stable paper assets under `data/outputs/experiments/<experiment-name>/`.

Relevant code: `src/cli/commands/calibration/`, `src/cli/commands/experiment/`, `src/experiments/scenario_runner.py`,
`src/prompts/experiment.py`, `src/prompts/templates/experiment.jinja2`, `src/prompts/template_utils.py`, `src/experiments/c1_assets.py`, and
`src/experiments/exploratory_assets.py`.
