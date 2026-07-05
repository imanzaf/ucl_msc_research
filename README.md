# ucl_msc_research

Repo containing code and paper for UCL IFT final MSc dissertation.

## Project structure

- `configs/` - Pydantic settings for API keys and project configuration.
- `docs/` - Research plans, distinction guidance, and supporting documents.
- `docs/experiments/` - Runbooks for benchmark and experiment procedures.
- `scripts/` - Runnable research utilities and draft-generation pipelines.
- `src/data_models/` - Pydantic models for benchmark and scoring data structures.
- `tex_src/` - Dissertation LaTeX source and references.
- `tests/` - Unit tests for project code.

## Scenario design

Scenario specifications live in `src/data_models/scenarios.py`. Each V4 `ScenarioFamily` records the
finance area, interaction mode, tool-use flag, seed-owned agent and user roles, three prompt
conditions, and five generated `ScenarioInstance` records. Each instance contains source-labelled
reference passages shown to the financial agent, hidden atomic fact metadata for scoring,
user-facing context for the user simulator, possible user actions, possible user beliefs, and
persona-matched initial user prompts.

Intermediate scenario-family drafts can be generated with:

```bash
uv run python scripts/generate_scenario_drafts.py
```

The generator defaults to scenario set `v4` and uses one Pydantic structured-output call per
seed-owned user goal. Production-baseline guidance stays seed-owned; production-integrity guidance
is a fixed add-on. The generator writes draft JSON plus Markdown review artifacts under
`data/inputs/scenarios/<scenario-set>/runs/<YYYYMMDDTHHMMSS>/`. See
`docs/experiments/scenario_generation.md` for details.

## Response scoring

TBC

Run the current tests with:

```bash
uv run pytest
```
