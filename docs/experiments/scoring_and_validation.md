# Scoring and Validation

One model, `google/gemini-3.1-flash-lite`, runs three independent judge contracts using medium reasoning effort. The contracts are developed and frozen on
the stratified 191-response sample and are applied without retuning to all 10,710 evaluated responses:

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

Before judge execution, `recover-selections` derives the 3,570 exact-budget selection outcomes. Strict JSON remains format-adherent. One complete Markdown
fence containing otherwise valid JSON supplies usable selection IDs but remains format-nonadherent. Prose, ambiguous wrappers, wrong-k selections,
duplicate IDs, and unknown IDs remain unusable, and no evaluated response is regenerated. The decoded `answer_text` from strict or wholly fenced
JSON is used for prose judging without changing the original adherence result:

```bash
uv run risk-comm-v2 scoring recover-selections \
  --output data/outputs/experiments/response_judging_v8/results/exact_budget_selections.jsonl \
  --summary data/outputs/experiments/response_judging_v8/logs/exact_budget_selection_summary.json
```

## Review the contracts

Write the exact prompts, strict output schemas, hashes, and output-token ceilings without making a paid call:

```bash
uv run risk-comm-v2 scoring show-prompts \
  --output data/outputs/experiments/response_judging_v8/judge_prompts.json
```

The source contracts are in `srcv2/scoring/judges.py`. The three response models are `ContentJudgeOutput`, `PresentationJudgeOutput`, and
`AccuracyJudgeOutput` in `srcv2/models/scoring.py`.

## Build and run the 5% pilot

Draw the stratified 191-response sample and build its 1,528 calls:

```bash
uv run risk-comm-v2 scoring sample-pilot

uv run risk-comm-v2 scoring build-plan \
  --stage pilot \
  --output data/outputs/experiments/response_judging_v8/checkpoints/pilot_plan.jsonl
```

Obtain current Gemini 3.1 Flash Lite prices, estimate the exact plan, and record bounded approval before execution:

```bash
uv run risk-comm-v2 scoring estimate-cost \
  --plan data/outputs/experiments/response_judging_v8/checkpoints/pilot_plan.jsonl \
  --input-price-per-million <CURRENT_INPUT_PRICE_USD> \
  --output-price-per-million <CURRENT_OUTPUT_PRICE_USD> \
  --output data/outputs/experiments/response_judging_v8/checkpoints/pilot_cost_estimate.json

uv run risk-comm-v2 scoring approve-execution \
  --estimate data/outputs/experiments/response_judging_v8/checkpoints/pilot_cost_estimate.json \
  --approved-max-cost <APPROVED_USD_CEILING> \
  --approved-by <RESEARCHER_ID> \
  --note "Approved 191-response judge-development pilot" \
  --confirm-paid-execution \
  --output data/outputs/experiments/response_judging_v8/checkpoints/pilot_approval.json

uv run risk-comm-v2 scoring execute-pilot \
  --plan data/outputs/experiments/response_judging_v8/checkpoints/pilot_plan.jsonl \
  --estimate data/outputs/experiments/response_judging_v8/checkpoints/pilot_cost_estimate.json \
  --approval data/outputs/experiments/response_judging_v8/checkpoints/pilot_approval.json \
  --cache-dir data/outputs/experiments/response_judging_v8/cache/pilot \
  --output data/outputs/experiments/response_judging_v8/results/pilot_results.jsonl \
  --summary data/outputs/experiments/response_judging_v8/logs/pilot_summary.json
```

Inspect every pilot output. If an approved change affects only one contract's input, build that contract's plan with `--contract`, rerun every affected
call, and use `merge-results` to combine those replacement records with hash-identical records from the other contracts. Never merge a record whose
task hash does not occur in the target plan. Residual label errors and structurally invalid outputs are corrected after execution through the manual
override ledger rather than by expanding the prompts.

## Freeze and run evaluated responses

After explicit review and manual adjudication of every pilot call, freeze a contract that binds both the immutable raw results and the complete
adjudicated label set:

```bash
uv run risk-comm-v2 scoring freeze-contract \
  --pilot-sample data/outputs/experiments/response_judging_v8/checkpoints/pilot_sample.json \
  --pilot-plan data/outputs/experiments/response_judging_v8/checkpoints/pilot_plan.jsonl \
  --pilot-results data/outputs/experiments/response_judging_v8/results/pilot_results.jsonl \
  --pilot-adjudicated data/outputs/experiments/response_judging_v8/results/adjudicated_judgments.jsonl \
  --confirm-pilot-reviewed \
  --output data/outputs/experiments/response_judging_v8/checkpoints/frozen_judge_contract.json

uv run risk-comm-v2 scoring build-plan \
  --stage full \
  --output data/outputs/experiments/response_judging_v8/checkpoints/full_plan.jsonl
```

The completed six-experiment plan contains 30,576 calls. Build the 55,104-call commercial-interest plan separately so its paid execution can be
estimated, approved, resumed, and reviewed without rerunning those calls:

```bash
uv run risk-comm-v2 scoring build-plan \
  --stage full \
  --experiment commercial_interest_instruction_v1 \
  --output data/outputs/experiments/commercial_interest_instruction_v1/checkpoints/judge_plan.jsonl
```

Estimate and approve the exact requested plan using the same `estimate-cost` and `approve-execution` commands, then run it with the frozen contract:

```bash
uv run risk-comm-v2 scoring execute-full \
  --plan data/outputs/experiments/commercial_interest_instruction_v1/checkpoints/judge_plan.jsonl \
  --frozen-contract data/outputs/experiments/response_judging_v8/checkpoints/frozen_judge_contract.json \
  --estimate data/outputs/experiments/commercial_interest_instruction_v1/checkpoints/judge_cost_estimate.json \
  --approval data/outputs/experiments/commercial_interest_instruction_v1/checkpoints/judge_approval.json \
  --cache-dir data/outputs/experiments/commercial_interest_instruction_v1/cache/judges_gemini \
  --output data/outputs/experiments/commercial_interest_instruction_v1/results/judge_raw_results.jsonl \
  --summary data/outputs/experiments/commercial_interest_instruction_v1/logs/judge_summary.json
```

A complete all-experiment plan contains 85,680 calls. Existing and commercial-interest raw records can be assembled against that plan with
`merge-results`; matching hashes permit reuse, and duplicate or missing call coordinates fail closed.

## Manual corrections and outcomes

Raw records are immutable. Put confirmed corrections in a JSONL ledger using `JudgeOverride`; each row binds the original output hash and supplies one
typed replacement output with researcher, time, and reason. Empty-ledger files are valid when no correction is needed.

```bash
uv run risk-comm-v2 scoring apply-overrides \
  --plan data/outputs/experiments/response_judging_v8/checkpoints/full_plan.jsonl \
  --raw-results data/outputs/experiments/response_judging_v8/results/full_raw_results.jsonl \
  --overrides data/outputs/experiments/response_judging_v8/results/manual_overrides.jsonl \
  --output data/outputs/experiments/response_judging_v8/results/adjudicated_judgments.jsonl
```

`srcv2/scoring/outcomes.py` then reports signed directional gap D, pairwise absolute imbalance A, total material coverage T, pair states, specificity,
presentation, factual-error exposure, and secondary outcomes separately. Exact-k selection-ID D is calculated from the selected IDs rather than from
prose, and T is not analysed as an exact-k outcome because k fixes it. The confirmatory exact-budget contrast uses the fixed subset of model
families with usable neutral k=2, k=4, and k=6 selections in every scenario; all format-adherence and partial-model results are reported descriptively.

For the commercial-interest experiment, apply the reviewed correction ledger and calculate response outcomes with the complete evaluated-response
file and the recovered-selection artifact:

```bash
uv run risk-comm-v2 scoring apply-overrides \
  --plan data/outputs/experiments/commercial_interest_instruction_v1/checkpoints/judge_plan.jsonl \
  --raw-results data/outputs/experiments/commercial_interest_instruction_v1/results/judge_raw_results.jsonl \
  --overrides data/outputs/experiments/commercial_interest_instruction_v1/results/full_manual_overrides.jsonl \
  --output data/outputs/experiments/commercial_interest_instruction_v1/results/adjudicated_judgments.jsonl

uv run risk-comm-v2 scoring calculate-outcomes \
  --runs data/outputs/experiments/commercial_interest_instruction_v1/results/20260817T225417Z_results.jsonl \
  --adjudicated data/outputs/experiments/commercial_interest_instruction_v1/results/adjudicated_judgments.jsonl \
  --selections data/outputs/experiments/response_judging_v8/results/exact_budget_selections.jsonl \
  --output data/outputs/experiments/commercial_interest_instruction_v1/results/response_outcomes.jsonl
```

`calculate-outcomes` validates an exact eight-label join for every response. It stores prose content and identifier selection separately, derives
factual density as communicated supplied facts per 100 response words, and keeps ownership outcomes on the fixed option-A product coordinate.
