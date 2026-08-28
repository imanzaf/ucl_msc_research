# Scoring and Validation

Scoring is owned by the experiment that produced the evaluated responses. Every experiment stores its evaluated-model outputs in `results/` and every
artifact produced by its scoring workflow in `scoring/`:

```text
data/outputs/experiments/<experiment_name>/
  results/
    <timestamp>_results.jsonl
  scoring/
    judge_prompts.json
    pilot_sample.json
    pilot_plan.jsonl
    pilot_raw_judge_results.jsonl
    pilot_manual_overrides.jsonl
    pilot_final_judgments.jsonl
    frozen_judge_contract.json
    judge_plan.jsonl
    cost_estimate.json
    approval.json
    raw_judge_results.jsonl
    manual_overrides.jsonl
    final_judgments.jsonl
    selections.jsonl
    response_scores.jsonl
    outcome_observations.jsonl
    paired_contrasts.json
    manifest.json
    summary.json
    cache/
    logs/
    checkpoints/
```

`raw_judge_results.jsonl` remains immutable. Confirmed corrections are recorded in `manual_overrides.jsonl`; applying that ledger writes
`final_judgments.jsonl`. `response_scores.jsonl` is the canonical analysis input. The manifest hashes the source responses, judge plan, raw calls,
final judgments, and final scores and verifies eight final judgments and one score record per evaluated response.

The same 191-response sample underlies the completed contract-development workflows. Each experiment contains the complete development bundle for the
judge contract it uses—sample, plan, raw outputs, correction ledger, and final judgments—so its frozen contract can be verified without depending on
a central scoring experiment. These replicated files are provenance artifacts; future experiment-specific pilots use the same filenames in the new
experiment's own directory.

The first six experiments were scored with `openai/gpt-5.4-mini`; `commercial_interest_instruction_v1` was scored with
`google/gemini-3.1-flash-lite`. Each experiment's manifest records the judge model and frozen contract. Both models run the same three independent
contracts with medium reasoning effort:

- content: one response, one candidate fact, and its anchor;
- presentation: one response and the two visible option names;
- accuracy: one response, its visible prompt context, its visible option names, and the six visible facts.

The content contract runs once for each fact, producing eight calls per response: six content, one presentation, and one accuracy. The judges never
receive hidden direction, pair, valence, ownership, treatment, evaluated-model, or provider labels. Exact evidence positions, fact counts, response
length, factual emphasis, and pair order are derived in code. Genuinely unlocatable evidence is corrected through the manual ledger rather than by
silently changing raw judge outputs.

## Experiment-scoped commands

Every scoring command requires `--experiment`. Its default inputs and outputs resolve beneath that experiment's `scoring/` directory. For example:

```bash
uv run risk-comm scoring show-prompts \
  --experiment commercial_interest_instruction_v1

uv run risk-comm scoring build-plan \
  --experiment commercial_interest_instruction_v1 \
  --stage full
```

The source contracts are in `src/scoring/judges.py`. Their response models are `ContentJudgeOutput`, `PresentationJudgeOutput`, and
`AccuracyJudgeOutput` in `src/models/scoring.py`.

## Exact-budget selections

Run selection recovery only for an experiment containing exact-budget responses:

```bash
uv run risk-comm scoring recover-selections \
  --experiment information_budget_v1

uv run risk-comm scoring recover-selections \
  --experiment commercial_interest_instruction_v1
```

Strict JSON remains format-adherent. One complete Markdown fence containing otherwise valid JSON supplies usable selection identifiers but remains
format-nonadherent. Ambiguous wrappers, wrong-k selections, duplicate identifiers, and unknown identifiers remain unusable. The decoded
`answer_text` is the prose-scoring target without changing the response's original adherence result.

## Pilot and contract freeze

The final judge prompts were reviewed on the frozen five-percent development sample. If a new experiment requires a new pilot, keep that pilot in the
same experiment's scoring directory:

```bash
uv run risk-comm scoring sample-pilot \
  --experiment <EXPERIMENT_NAME>

uv run risk-comm scoring build-plan \
  --experiment <EXPERIMENT_NAME> \
  --stage pilot

uv run risk-comm scoring estimate-cost \
  --experiment <EXPERIMENT_NAME> \
  --stage pilot \
  --input-price-per-million <CURRENT_INPUT_PRICE_USD> \
  --output-price-per-million <CURRENT_OUTPUT_PRICE_USD>

uv run risk-comm scoring approve-execution \
  --experiment <EXPERIMENT_NAME> \
  --stage pilot \
  --approved-max-cost <APPROVED_USD_CEILING> \
  --approved-by <RESEARCHER_ID> \
  --note "Approved scoring pilot" \
  --confirm-paid-execution

uv run risk-comm scoring execute-pilot \
  --experiment <EXPERIMENT_NAME>
```

After reviewing every pilot call, apply any pilot correction ledger and freeze the contract:

```bash
uv run risk-comm scoring apply-overrides \
  --experiment <EXPERIMENT_NAME> \
  --plan data/outputs/experiments/<EXPERIMENT_NAME>/scoring/pilot_plan.jsonl \
  --raw-results data/outputs/experiments/<EXPERIMENT_NAME>/scoring/pilot_raw_judge_results.jsonl \
  --overrides data/outputs/experiments/<EXPERIMENT_NAME>/scoring/pilot_manual_overrides.jsonl \
  --output data/outputs/experiments/<EXPERIMENT_NAME>/scoring/pilot_final_judgments.jsonl

uv run risk-comm scoring freeze-contract \
  --experiment <EXPERIMENT_NAME> \
  --confirm-pilot-reviewed
```

## Full scoring run

Build, cost, approve, and execute each experiment independently:

```bash
uv run risk-comm scoring build-plan \
  --experiment <EXPERIMENT_NAME> \
  --stage full

uv run risk-comm scoring estimate-cost \
  --experiment <EXPERIMENT_NAME> \
  --input-price-per-million <CURRENT_INPUT_PRICE_USD> \
  --output-price-per-million <CURRENT_OUTPUT_PRICE_USD>

uv run risk-comm scoring approve-execution \
  --experiment <EXPERIMENT_NAME> \
  --approved-max-cost <APPROVED_USD_CEILING> \
  --approved-by <RESEARCHER_ID> \
  --note "Approved full scoring run" \
  --confirm-paid-execution

uv run risk-comm scoring execute-full \
  --experiment <EXPERIMENT_NAME>
```

Execution resumes from `data/outputs/experiments/<EXPERIMENT_NAME>/scoring/cache/full/`. Token use, billed cost, structural validity, and completion
counts are written to that experiment's `scoring/summary.json`.

## Corrections and final scores

Raw results are never edited. If a scoring run produced separate reusable and replacement result files, first merge them against the immutable plan:

```bash
uv run risk-comm scoring merge-results \
  --experiment <EXPERIMENT_NAME> \
  --source <REUSABLE_RESULTS.jsonl> \
  --source <REPLACEMENT_RESULTS.jsonl>
```

Record confirmed replacements as `JudgeOverride` rows in the experiment's `manual_overrides.jsonl`, then run:

```bash
uv run risk-comm scoring apply-overrides \
  --experiment <EXPERIMENT_NAME>

uv run risk-comm scoring calculate-outcomes \
  --experiment <EXPERIMENT_NAME>
```

`apply-overrides` validates evidence against the canonical parsed response prose. `calculate-outcomes` writes `response_scores.jsonl` and
`manifest.json`, validating a complete eight-label join for every response. The output keeps signed directional gap D, pairwise absolute imbalance A,
total coverage T, pair states, specificity, presentation, factual-error exposure, and secondary outcomes separate.

For the commercial-interest experiment, its matched observations and contrasts remain in the same scoring directory:

```bash
uv run risk-comm analysis commercial-interest-observations
uv run risk-comm analysis commercial-interest
```
