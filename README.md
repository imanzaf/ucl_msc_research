# UCL MSc Research: Selective Financial Communication

This repository contains the experiment implementation and analysis code for a controlled evaluation of selective and directional communication by financial-assistant language models, completed for the IFTE0008 Dissertation module as part of the MSc Banking and Digital Finance programme.

## Abstract

> **Placeholder:** the final paper abstract will be added here before release.

## Repository structure

```text
src/                    Experiment, scoring, and analysis implementation
tests/                  Tests for the retained implementation
schemas/                JSON Schemas exported from the public Pydantic models
scripts/risk-comm       Unified command-line launcher
scripts/                Focused audit and repository-hook utilities
docs/experiments/       Targeted workflow guides
data/inputs/            Versioned scenario and benchmark inputs
data/outputs/           Frozen experiment, scoring, and analysis artifacts
tex_src/v0.4.0/         Latest dissertation source and generated PDF
```

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

The seven experiment directories and their manuscript labels are documented in the
[experiment execution guide](docs/experiments/experiment_execution.md). Each experiment owns its configuration, evaluated responses, scoring artifacts, caches, logs, and paper assets beneath `data/outputs/experiments/<experiment_name>/`.
