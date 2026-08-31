# UCL MSc Research: Selective Financial Communication

This repository contains the experiment implementation and analysis code for a controlled evaluation of selective and directional communication by financial-assistant language models, completed for the IFTE0008 Dissertation module as part of the MSc Banking and Digital Finance programme.

## Abstract

A large language model acting as a financial assistant can be factually correct yet still shape a customer's decision through what it selects, omits or foregrounds. Seven models were evaluated across 30 controlled financial scenarios to examine how institutional objectives, customer-state cues and information constraints shape communication. Each scenario contained six customer-relevant facts arranged in three pairs matched on customer valence but opposed in institutional direction. This design separated coverage, pairwise imbalance and institutional direction rather than collapsing them into one bias score.

Restricted response space created substantial selectivity without automatically favouring the institution. Under a 40-word limit, 72.4% of responses omitted at least one material fact and 62.4% broke at least one matched pair, although mean institutional direction remained near zero (*D* = -0.013, where -1 is countervailing and +1 is institution-supporting). Customer-state cues mainly affected response length and reassurance, while affiliation mainly affected ordering. With an explicit commercial objective and an exact two-fact budget, mean direction increased by 0.105 while coverage changed by less than one percentage point. Concision therefore created an information-allocation problem, but selectivity was not inherently institutionally directional.

This study contributes a controlled benchmark and matched-pair method for separating general information loss from institution-favouring selection, and provides evidence that information constraints and institutional objectives shape the selection and presentation of facts in different ways. Financial-assistant evaluation should therefore test the composition and pairwise balance of the evidence that survives, using the smallest response budget and actual institutional objective intended for deployment.

## Repository structure

```text
src/                    Experiment, scoring, and analysis implementation
tests/                  Tests for the retained implementation
schemas/                JSON Schemas exported from the public Pydantic models
scripts/risk-comm       Unified command-line launcher
scripts/                Focused audit and repository-hook utilities
docs/experiments/       Targeted workflow guides
data/inputs/            Versioned scenario and benchmark inputs
```

## Final benchmark corpus

The complete frozen corpus used by the experiments is
[`data/inputs/scenarios/v4.0.1/accepted_scenarios.jsonl`](data/inputs/scenarios/v4.0.1/accepted_scenarios.jsonl).
It contains one record for each of the 30 accepted scenarios, including the decision context, options, all six visible facts, matched-pair assignments, customer valence, institutional direction, required anchors, presentation order, ownership eligibility, and review provenance.

## Main commands

```bash
uv sync --group dev
uv run risk-comm --help
uv run risk-comm <group> --help
uv run pytest
uv run pre-commit run --all-files
```

The CLI groups are `scenarios`, `experiment`, `scoring`, `analysis`, `maintenance`, and `review`. Commands that make paid provider calls require an explicit cost estimate and a hash-bound approval artifact.

## Workflow guides

- [Scenario construction and validation](docs/experiments/scenario_workflow.md)
- [Experiment planning and execution](docs/experiments/experiment_execution.md)
- [Scoring and adjudication](docs/experiments/scoring_and_validation.md)
- [Confirmatory and descriptive analysis](docs/experiments/analysis.md)

The seven experiment components and their manuscript labels are documented in the
[experiment execution guide](docs/experiments/experiment_execution.md). The frozen experiment, scoring, and analysis outputs are not included in the public repository because the generated files were too large to upload. The repository instead provides the final benchmark inputs, implementation, schemas, and workflow documentation.
