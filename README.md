# UCL MSc Research: Selective Risk Communication

This repository contains the dissertation and reproducible experiments for a controlled study of selective financial-risk communication under
concise-response guidance and user-expressed concern.

The canonical methodology is [RESEARCH_PLAN.md](docs/research-plan/RESEARCH_PLAN.md). The active scenario seed is V3.0.0 and generated/published
scenario artifacts use schema 9.0.0. Scenario definitions and customer queries are stored in separate, schema-validated JSON files joined by
family and scenario IDs. Generation protocol V1.1.1 makes one initial generation call per scenario, excludes all customer queries from that call,
generates exact quantitative specificity markers with each fact, and freezes the R1 same-provider and R2 external-option relationships in the
provider payload. For R1/R2, its example contains only the matching published C1's two option-information records.
All five active scenario, experiment, and scoring prompts are paired Jinja2 templates under
`src/prompts/templates/`, loaded through shared utilities in `src/prompts/template_utils.py`; R1/R2 are processed independently. The local scenario
editor saves arbitrary wording changes as parent-linked candidate versions and can publish any selected current version directly.

Scenario authoring has no automated-review, regeneration, acceptance-decision, model-freeze, prompt-review, pilot, or complete-batch gate. Those
downstream evaluated-model controls remain separate. R1 generation always compares two options from the provider; R2 compares one provider option
with one identified external option.

## Study at a glance

The sole primary outcome is the preregistered 0–1 `selective_communication_score`:

\[
0.5(coverage\ asymmetry) + 0.5(specificity\ asymmetry).
\]

H1 compares concise-response guidance with no response-length instruction. H2 compares concerned with neutral wording. Both use the initial answer
and form the only Holm-adjusted confirmatory family. `presentation_style_score` and binary `factual_inaccuracy_score` are prespecified secondary
outcomes. Follow-up-only and code-derived cumulative results for all three scores are secondary checkpoints. Power is calculated only for H1/H2;
calibration supplies expected interval precision for the initial secondary contrasts.

Scoring makes between ten and eighteen successful LLM calls per conversation. Each isolated response receives four content calls, presentation
calls only for facts marked present, and one accuracy call across the full fact list. Cumulative results require no additional LLM call.

| Experiment | Design | Conversations |
|---|---|---:|
| `risk_comm_v1` | 20 scenarios × 3 models × baseline/concise × neutral/concerned | 240 |
| `material_priority_v1` | 20 scenarios × 3 models × concise guidance × 2 seed-authored queries | 120 |
| `brevity_locus_v1` | 20 scenarios × 3 models × neutral query with user-requested brevity | 60 |

Experiment artifacts live under `data/outputs/experiments/<experiment-name>/`. Scenario-generation histories live under
`data/outputs/scenario_generation/v3.0.0/<run-id>/<round-id>/`; the run ID identifies one logical authoring set and timestamped rounds preserve each
initial or manually revised candidate version.

## Workflows

- [Scenario workflow](docs/experiments/scenario_workflow.md): generate initial candidates, edit/save versions, and publish selected scenarios.
- [Experiment execution](docs/experiments/experiment_execution.md): run C1, calibration, confirmatory, and exploratory model calls.
- [Scoring and validation](docs/experiments/scoring_and_validation.md): automated scoring, blinded annotation, validation, and contingencies.
- [Analysis](docs/experiments/analysis.md): construct analysis inputs and run confirmatory or exploratory inference.
- [Scenario-family research](docs/experiments/scenario_research.md): source basis for the financial task-family taxonomy.

The [Distinction Guide](docs/reference/DISTINCTION_GUIDE.md) is supporting dissertation guidance rather than an experiment runbook. Historical
protocols and superseded workflow documents remain under `docs/archive/`.

## Common offline checks

```bash
uv run risk-comm maintenance export-schemas
uv run risk-comm maintenance validate-protocol
uv run risk-comm maintenance validate-docs
uv run pytest
uv run pre-commit run --all-files
```

Setup, validation, plan construction, tests, and documentation commands never authorise paid provider calls. Scenario generation runs only when
explicitly requested and records actual provider usage and cost. Evaluated-model and scoring calls retain their separate paid-execution gates.
