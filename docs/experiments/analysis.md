# Analysis Workflow

Analysis consumes only frozen run units, frozen scorer outputs, and direction metadata joined after extraction. The implementation is in
`srcv2/analysis/`.

## Confirmatory family

The two confirmatory tests are:

1. anxious versus neutral D, averaged across query length;
2. the ordered k=6→4→2 change in selection-ID D.

Input JSONL for the first test contains `scenario_id`, `use_case_id`, `model_slug`, `affect`, `query_length`, and
`signed_directional_gap`. Input for the second contains `scenario_id`, `use_case_id`, `model_slug`, `exact_fact_budget`, and
`signed_directional_gap`.

```bash
uv run risk-comm-v2 analysis confirmatory \
  --user-state-scores data/outputs/experiments/user_state_scores.jsonl \
  --budget-scores data/outputs/experiments/information_budget_scores.jsonl \
  --output data/outputs/experiments/confirmatory_results.json
```

The command constructs scenario-level paired contrasts, applies a two-test Holm correction, and reports use-case-stratified scenario-cluster
bootstrap intervals. The bootstrap seed and iteration count are stored in the result artifact.

## Secondary and diagnostic outcomes

D, A, T, pair states, individual fact selection, anchor outcomes, framing direction, first material fact, conditional pair order, factual emphasis,
recommendation direction, first-presented option, factual error, empathy/referral, density, and length are reported as their own outcomes. T is
descriptive only for exact-k cells because it is fixed by design.

Ownership analysis retains option A as the product coordinate across employer, fictional-name assignment, and display-order changes. It reports the
option-A gap, symmetric employer-role contrast, strict owner-concordant switches, and switch rate.

## Descriptive grouped reporting

Prepare JSONL rows containing a `group` label and numeric `value`, then run:

```bash
uv run risk-comm-v2 analysis describe \
  --observations data/outputs/experiments/descriptive_observations.jsonl \
  --output data/outputs/experiments/descriptive_summaries.json
```

Groups are emitted alphabetically rather than sorted by outcomes. Use-case and open-weight/closed patterns are descriptive only: the report contains
no ranking and supports no causal claim about access category.

## Paper assets

```bash
uv run risk-comm-v2 experiment generate-assets
```

Each experiment writes a stable `<experiment-name>_table.tex` beneath its own `assets/` directory. Manuscript result placeholders remain until these
assets are generated from complete final outputs.
