# Experiment execution

This runbook covers model execution for the C1 diagnostic, rubric-development calibration, the confirmatory experiment, and both exploratory
experiments. Scenario preparation is documented in [scenario_workflow.md](scenario_workflow.md); scoring and analysis begin only after the relevant
model run is complete.

## Experiment matrix

| Experiment | Purpose | Conversations |
|---|---|---:|
| `c1_llama_2x2_v9` | Content-gated rescoring of the 40 completed V3 Llama C1 conversations | 40 |
| `risk_comm_calibration_v1` | Ten C1 scenarios × three models × the four primary cells | 120 |
| `risk_comm_v1` | Twenty R1–R2 scenarios × three models × the four primary cells | 240 |
| `material_priority_v1` | Twenty R1–R2 scenarios × three models × concise guidance × two seed-authored queries | 120 |
| `brevity_locus_v1` | Twenty R1–R2 scenarios × three models × neutral query with user-requested brevity | 60 |

The baseline system prompt has no response-length instruction. The concise condition adds exactly
`Keep your answers concise and no longer than 80 words.` under Guidance. This is a prompt instruction only: execution does not count, reject,
truncate, or retry responses based on their word count.

The complete evaluated-model contract is defined in `src/prompts/templates/experiment.jinja2`. Its `---system---`, `---user---`, and
`---follow-up---` sections keep the initial pair and later user turn together, with all dynamic formatting visible in the template. The V12 prompt
package hashes the complete template source through `src/prompts/template_utils.py`.

Evaluated responses use three runner-recorded retries after the initial attempt, with a fixed 30-second wait before each retry. The OpenAI client’s
internal retries are disabled for evaluated-model calls so every attempt is governed by the frozen experiment retry policy.

## Direct response generation

Use the response runner to select only the ten C1 scenarios (`c`), only the twenty R1/R2 scenarios (`r`), or all thirty published scenarios
(`all`). Omitting `--model-ids` runs all three evaluated models in `src/settings/models.json`:

```bash
uv run risk-comm experiment run-responses \
  --experiment-name all_scenarios_all_models_2x2_v1 \
  --scenario-scope all \
  --execute-paid
```

Pass one or more model ids to run only that subset:

```bash
uv run risk-comm experiment run-responses \
  --experiment-name r_llama_qwen_2x2_v1 \
  --scenario-scope r \
  --model-ids meta-llama/llama-3.3-70b-instruct qwen/qwen-2.5-72b-instruct \
  --execute-paid
```

The command authenticates the complete published manifest, freezes the selected model list and prompt package in `config.json`, writes the seeded
run plan before making calls, and appends every terminal conversation immediately. Repeating the same command resumes the same result file. It
generates evaluated-model responses only; scoring remains a separate command and is never invoked by this runner. Optional
`--provider-only MODEL_ID=PROVIDER_ID[,PROVIDER_ID]` values freeze OpenRouter routing per selected model.

If a stopped run needs a provider-route correction, amend only the unfinished units for one model and record the reason while resuming:

```bash
uv run risk-comm experiment run-responses \
  --experiment-name all_scenarios_all_models_2x2_v1 \
  --scenario-scope all \
  --route-unfinished-only qwen/qwen-2.5-72b-instruct=deepinfra \
  --routing-amendment-reason "OpenRouter fallback selected an incompatible endpoint." \
  --execute-paid
```

This preserves `checkpoints/run_plan_before_routing_amendment.jsonl`, writes a self-hashed
`checkpoints/response_routing_amendment.json`, updates routing only for run-unit IDs without a terminal transcript, and resumes without repeating
completed or failed calls. After the amendment exists, any later resume uses the ordinary command without the amendment options.

To retry active failed records while leaving completed records untouched, resume with `--rerun-failed`:

```bash
uv run risk-comm experiment run-responses \
  --experiment-name all_scenarios_all_models_2x2_v1 \
  --scenario-scope all \
  --rerun-failed \
  --execute-paid
```

The runner snapshots the pre-rerun results and plan, archives the failed transcripts under `results/failed_reruns/`, and makes only their run-unit
IDs pending. If the model already has an authenticated provider-routing amendment, the failed records inherit that route. Every failed rerun writes
a self-hashed manifest under `checkpoints/failed_reruns/`; the active results retain only the replacement terminal record.

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
