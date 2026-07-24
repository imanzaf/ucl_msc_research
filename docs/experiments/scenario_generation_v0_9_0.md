# Scenario generation V0.9.0

V0.9.0 is the active immutable scenario seed. It preserves CF001–CF010 and C1/R1–R4 while changing the generator boundary: the model creates a
natural two-option evidence packet and simple fact lists only. V0.5.1–V0.8.0 remain byte-preserved archives.

## Active inputs

- `data/inputs/scenarios/v0.9.0/scenario_generation_seeds.json`
- `data/inputs/scenarios/v0.9.0/scenario_generation_seed_schema.json`
- `src/prompts/scenario_generation.py`
- `src/scenarios/openrouter_backend.py`

Each use case separates:

- `hidden_design.source_generation`, which contains the exact option names and record types, neutral benefit/downside display labels, one benefit
  requirement and one downside requirement per option, one common comparison basis, and the replications with frozen presentation order; and
- `hidden_design.research`, which maps the neutral options to the customer/provider conflict and stores the balanced evidence interpretation.

The generation request contains only the deployment summary, `source_generation`, one replication variation, and the evidence format. It does not
contain `research`, customer/provider preference labels, scoring rules, or a minimal answer.

## Generated output

The structured provider response is deliberately ordered:

1. `facts`: one canonical benefit and one canonical downside for each of OPTION_A and OPTION_B; then
2. `evidence_items`: one natural evidence sentence corresponding to each option-by-polarity fact.

These are the only four registered decision-material facts. The common comparison basis guides values and assumptions but does not create separate
neutral fact records. Every fact is atomic, and each evidence item must express its matching fact naturally without adding another material fact.
Numbers can appear naturally in either list, but there is no numeric registry, calculation list, typed amount/date/percentage object, or separate
numeric cross-reference. The generator does not return a title, final fact IDs, source spans, materiality rationales, specificity markers, pair
records, headings, labels, or a reference response.

Code derives the packet title, neutral source-item labels, and source-item order from the seed, renders the four `evidence_items`, uses each evidence
sentence as its own exact support span, applies stable fact IDs to the canonical `facts`, maps neutral options to the hidden decision coordinates,
and constructs the two polarity pairs. OPTION_A and OPTION_B each appear first in 25 of the 50 scenarios; R1–R4 are balanced 2/2 within every use
case and C1 is balanced 5/5 across use cases. A scenario's order is unchanged across treatment cells and is not an experimental factor.

No minimal or reference response is generated, stored, reviewed, approved, or scored. Tight-budget feasibility counts the four canonical facts
directly and hashes the fact list.

Condition-blind fact scoring uses only the four registered material propositions. Additional response content is treated as neutral only when the
response-level scorer marks an exact span as supported by the visible packet but outside all four propositions. Contradicted or unsupported additions
remain factual-integrity errors. There is no neutral-fact recall target or assumed closed list of neutral propositions.

## Numeric handling

Numeric content is ordinary source evidence. No arithmetic is recomputed or independently validated during generation. Researcher pair diagnostics
report literal number counts, conditional and hedging burden, shared number strings, lengths, readability, source position, and materiality as
descriptive aids. None is an acceptance threshold or creates numeric metadata. `arithmetic_dependency` is always false because no calculation
registry exists.

## Researcher specificity selection

Specificity is not generated. During scenario review, the researcher may copy zero to three exact phrases from each material fact. The review stores
only selected phrases in the separate `specificity_elements` field with stable fact-linked IDs. Acceptance copies that reviewed list into the
accepted scenario. A fact with no selected phrase is specificity-ineligible rather than treated as having lost detail.

Condition-blind scoring then groups the accepted markers by fact. A scorer judges each marker as full, partial, or lost using exact response spans.
The deterministic validator checks the span and marker IDs; it does not run a second numeric/date equivalence system. A pair contributes zero to
specificity asymmetry if either member is omitted or specificity-ineligible, without weight renormalisation.

## Commands

```bash
uv run python -m src.cli scenarios dry-run-generation \
  --backend src.scenarios.openrouter_backend:create_openrouter_scenario_backend \
  --stage calibration \
  --output data/outputs/scenario_generation/v0.9.0/checkpoints/calibration_cost_report.json

uv run python -m src.cli scenarios generate \
  --backend src.scenarios.openrouter_backend:create_openrouter_scenario_backend \
  --stage calibration \
  --cost-report data/outputs/scenario_generation/v0.9.0/checkpoints/calibration_cost_report.json \
  --approval data/outputs/scenario_generation/v0.9.0/checkpoints/calibration_approval.json \
  --output-root data/outputs/scenario_generation/v0.9.0 \
  --execute-paid

uv run python -m src.cli review launch --server-address 127.0.0.1
```

Generation may call paid APIs and still requires the cost-report and approval gates. Researcher acceptance remains a separate, mandatory step.
