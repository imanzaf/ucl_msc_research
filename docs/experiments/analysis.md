# Analysis Workflow

Analysis consumes only frozen run units, frozen scorer outputs, and direction metadata joined after extraction. The implementation is in
`srcv2/analysis/`.

## Primary tests and multiplicity families

The seven primary directional tests are:

1. commercial-interest instruction versus its matched no-instruction control for prose D in the standard comparison;
2. the same paired prose-D contrast in the single-most-important-fact task;
3. the same paired prose-D contrast at exact k=4;
4. the same paired prose-D contrast at exact k=2;
5. the owner-recoded fixed-option selection contrast in the ownership-flip task;
6. anxious versus neutral D, averaged across query length;
7. the ordered k=6→4→2 change in selection-ID D.

The command reads the frozen response outcomes for the user-state and information-budget experiments and the complete response-paired commercial
contrasts. Commercial treatment-control differences are averaged across model and customer-state coordinates within scenarios. The ownership
contrast is recoded so that positive values consistently refer to the employer-owned option.

```bash
uv run risk-comm-v2 analysis confirmatory
```

The command constructs scenario-level paired contrasts, applies Holm correction across the five RQ1 commercial-objective tests, and treats the RQ2
customer-state and RQ3 information-budget tests as separate singleton families. It also reports use-case-stratified scenario-cluster bootstrap
intervals. The random seed, iteration count, family identifier, and family size are stored in the result artifact.

## Secondary and diagnostic outcomes

D, A, T, pair states, individual fact selection, anchor outcomes, framing direction, first material fact, conditional pair order, factual emphasis,
recommendation direction, first-presented option, factual error, empathy/referral, density, and length are reported as their own outcomes. T is
descriptive only for exact-k cells because it is fixed by design.

Ownership analysis retains option A as the product coordinate across employer, fictional-name assignment, and display-order changes. It reports the
option-A gap, symmetric employer-role contrast, strict owner-concordant switches, and switch rate.

Forced-option responses receive an experiment-specific three-way choice label. An explicit recommendation determines the selected option when one
is present; otherwise directional framing supplies an implicit choice. Balanced or unassessable framing is retained as no discernible choice. The
command writes one hash-bound JSONL label per response and a descriptive JSON summary under the experiment's `scoring/` directory without making
new model calls:

```bash
uv run risk-comm-v2 analysis option-first-choices
```

The implementation is in `srcv2/analysis/option_first.py`. The output files are
`data/outputs/experiments/option_first_v1/scoring/forced_choice_labels_v1.jsonl` and
`data/outputs/experiments/option_first_v1/scoring/forced_choice_label_summary_v1.json`.

Prepare complete paired observation rows from the commercial-interest experiment's final response scores, then calculate treatment-minus-control
contrasts while holding scenario, model, affect, task, budget, employer role, and rendering fixed. Five directional summaries form the RQ1 Holm
family; other commercial-interest outcomes remain descriptive. The command defaults keep both derived artifacts in the experiment's `scoring/`
directory:

```bash
uv run risk-comm-v2 analysis commercial-interest-observations

uv run risk-comm-v2 analysis commercial-interest
```

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
