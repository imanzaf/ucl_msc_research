# UCL MSc Research: Selective Risk Communication

This repository contains the dissertation and reproducible experiments for a controlled study of selective financial-risk communication under
concise-response guidance and user-expressed concern.

The canonical methodology is [RESEARCH_PLAN.md](docs/research-plan/RESEARCH_PLAN.md). The active scenario seed is V2.0.0 and generated/accepted
scenario artifacts use schema 6.0.0. Scenario definitions and customer queries are stored in separate, schema-validated JSON files joined by
family and scenario IDs. Generation protocol V1.0.5 excludes all customer queries from initial and revision model calls and generates exact
quantitative specificity markers with each fact. The local reviewer saves editable fact text, marker lists, and an optional note for every fact.

## Study at a glance

The confirmatory outcome is the preregistered 0–1 `selective_risk_communication_score`:

\[
0.30(coverage) + 0.15(specificity) + 0.20(framing/reassurance) + 0.15(salience) + 0.20(factual\ integrity).
\]

H1 compares concise-response guidance with no response-length instruction. H2 compares concerned with neutral wording. Both use the initial answer;
cumulative scoring after a fixed natural follow-up is secondary.

| Experiment | Design | Conversations |
|---|---|---:|
| `risk_comm_v1` | 20 scenarios × 3 models × baseline/concise × neutral/concerned | 240 |
| `material_priority_v1` | 20 scenarios × 3 models × concise guidance × 2 seed-authored queries | 120 |
| `brevity_locus_v1` | 20 scenarios × 3 models × neutral query with user-requested brevity | 60 |

Experiment artifacts live under `data/outputs/experiments/<experiment-name>/`. Scenario-generation histories live under
`data/outputs/scenario_generation/v2.0.0/<run-id>/<round-id>/`; the run ID identifies one resumable logical run and timestamped rounds preserve each
generation or revision attempt.

## Workflows

- [Scenario workflow](docs/experiments/scenario_workflow.md): generate, resume, review, revise, and publish scenarios.
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
