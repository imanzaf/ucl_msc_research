# Scoring and Validation

Scoring starts only after all 3,822 evaluated responses are frozen. One model, `openai/gpt-5.4-mini`, runs three independent judge contracts using
medium reasoning effort:

- content: one response, one candidate fact, and its anchor;
- presentation: one response and the two visible option names;
- accuracy: one response, the visible assistant context and customer query, the two visible option names, and the six visible reference facts.

The content contract runs once for each of six facts, so each evaluated response requires eight calls: six content, one presentation, and one accuracy.
No call receives fact direction, pair, valence, ownership, treatment, evaluated-model, or provider labels. Exact evidence positions, counts, response length,
factual emphasis, and pair order are derived in code. Returned evidence is kept verbatim in the raw record. Code maps only superficial formatting,
quotation, punctuation, and case differences back to the original response; genuinely paraphrased or unlocatable evidence is queued for manual correction.
Fact presence concerns the underlying proposition; anchor presence separately records whether its specific number, rate, duration, threshold, or definite
condition survives. A product or topic mention alone is not fact presence. Recommendation requires an explicit choice; conditional advice covering
both options, favourable emphasis, and one-option discussion remain separate from recommendation.

Before judge execution, `recover-selections` derives the exact-budget selection outcome. Strict JSON remains format-adherent. One complete Markdown
fence containing otherwise valid JSON supplies usable selection IDs but remains format-nonadherent. Prose, ambiguous wrappers, wrong-k selections,
duplicate IDs, and unknown IDs remain unusable, and no evaluated response is regenerated. The decoded `answer_text` from strict or wholly fenced
JSON is used for prose judging without changing the original adherence result:

```bash
uv run risk-comm-v2 scoring recover-selections \
  --output data/outputs/experiments/response_judging_v7/results/exact_budget_selections.jsonl \
  --summary data/outputs/experiments/response_judging_v7/logs/exact_budget_selection_summary.json
```

## Review the contracts

Write the exact prompts, strict output schemas, hashes, and output-token ceilings without making a paid call:

```bash
uv run risk-comm-v2 scoring show-prompts \
  --output data/outputs/experiments/response_judging_v7/judge_prompts.json
```

The source contracts are in `srcv2/scoring/judges.py`. The three response models are `ContentJudgeOutput`, `PresentationJudgeOutput`, and
`AccuracyJudgeOutput` in `srcv2/models/scoring.py`.

## Build and run the 5% pilot

Draw the stratified 191-response sample and build its 1,528 calls:

```bash
uv run risk-comm-v2 scoring sample-pilot

uv run risk-comm-v2 scoring build-plan \
  --stage pilot \
  --output data/outputs/experiments/response_judging_v7/checkpoints/pilot_plan.jsonl
```

Obtain current GPT-5.4 Mini prices, estimate the exact plan, and record bounded approval before execution:

```bash
uv run risk-comm-v2 scoring estimate-cost \
  --plan data/outputs/experiments/response_judging_v7/checkpoints/pilot_plan.jsonl \
  --input-price-per-million <CURRENT_INPUT_PRICE_USD> \
  --output-price-per-million <CURRENT_OUTPUT_PRICE_USD> \
  --output data/outputs/experiments/response_judging_v7/checkpoints/pilot_cost_estimate.json

uv run risk-comm-v2 scoring approve-execution \
  --estimate data/outputs/experiments/response_judging_v7/checkpoints/pilot_cost_estimate.json \
  --approved-max-cost <APPROVED_USD_CEILING> \
  --approved-by <RESEARCHER_ID> \
  --note "Approved 191-response judge-development pilot" \
  --confirm-paid-execution \
  --output data/outputs/experiments/response_judging_v7/checkpoints/pilot_approval.json

uv run risk-comm-v2 scoring execute-pilot \
  --plan data/outputs/experiments/response_judging_v7/checkpoints/pilot_plan.jsonl \
  --estimate data/outputs/experiments/response_judging_v7/checkpoints/pilot_cost_estimate.json \
  --approval data/outputs/experiments/response_judging_v7/checkpoints/pilot_approval.json \
  --cache-dir data/outputs/experiments/response_judging_v7/cache/pilot \
  --output data/outputs/experiments/response_judging_v7/results/pilot_results.jsonl \
  --summary data/outputs/experiments/response_judging_v7/logs/pilot_summary.json
```

Inspect every pilot output. If an approved change affects only one contract's input, build that contract's plan with `--contract`, rerun every affected
call, and use `merge-results` to combine those replacement records with hash-identical records from the other contracts. Never merge a record whose
task hash does not occur in the target plan. Residual label errors and structurally invalid outputs are corrected after execution through the manual
override ledger rather than by expanding the prompts.

## Freeze and run the full corpus

After explicit review and manual adjudication of every pilot call, freeze a contract that binds both the immutable raw results and the complete
adjudicated label set:

```bash
uv run risk-comm-v2 scoring freeze-contract \
  --pilot-sample data/outputs/experiments/response_judging_v7/checkpoints/pilot_sample.json \
  --pilot-plan data/outputs/experiments/response_judging_v7/checkpoints/pilot_plan.jsonl \
  --pilot-results data/outputs/experiments/response_judging_v7/results/pilot_results.jsonl \
  --pilot-adjudicated data/outputs/experiments/response_judging_v7/results/adjudicated_judgments.jsonl \
  --confirm-pilot-reviewed \
  --output data/outputs/experiments/response_judging_v7/checkpoints/frozen_judge_contract.json

uv run risk-comm-v2 scoring build-plan \
  --stage full \
  --output data/outputs/experiments/response_judging_v7/checkpoints/full_plan.jsonl
```

The full plan contains 30,576 calls. Estimate and approve that exact plan using the same `estimate-cost` and `approve-execution` commands, then run:

```bash
uv run risk-comm-v2 scoring execute-full \
  --plan data/outputs/experiments/response_judging_v7/checkpoints/full_plan.jsonl \
  --frozen-contract data/outputs/experiments/response_judging_v7/checkpoints/frozen_judge_contract.json \
  --estimate data/outputs/experiments/response_judging_v7/checkpoints/full_cost_estimate.json \
  --approval data/outputs/experiments/response_judging_v7/checkpoints/full_approval.json \
  --cache-dir data/outputs/experiments/response_judging_v7/cache/full \
  --output data/outputs/experiments/response_judging_v7/results/full_raw_results.jsonl \
  --summary data/outputs/experiments/response_judging_v7/logs/full_summary.json
```

## Manual corrections and outcomes

Raw records are immutable. Put confirmed corrections in a JSONL ledger using `JudgeOverride`; each row binds the original output hash and supplies one
typed replacement output with researcher, time, and reason. Empty-ledger files are valid when no correction is needed.

```bash
uv run risk-comm-v2 scoring apply-overrides \
  --plan data/outputs/experiments/response_judging_v7/checkpoints/full_plan.jsonl \
  --raw-results data/outputs/experiments/response_judging_v7/results/full_raw_results.jsonl \
  --overrides data/outputs/experiments/response_judging_v7/results/manual_overrides.jsonl \
  --output data/outputs/experiments/response_judging_v7/results/adjudicated_judgments.jsonl
```

`srcv2/scoring/outcomes.py` then reports signed directional gap D, pairwise absolute imbalance A, total material coverage T, pair states, specificity,
presentation, factual-error exposure, and secondary outcomes separately. Exact-k selection-ID D is calculated from the selected IDs rather than from
prose, and T is not analysed as an exact-k outcome because k fixes it. The confirmatory exact-budget contrast uses the fixed subset of model
families with usable neutral k=2, k=4, and k=6 selections in every scenario; all format-adherence and partial-model results are reported descriptively.
