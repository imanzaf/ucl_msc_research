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

Scenario specifications live in `src/data_models/scenarios.py`. Each `Scenario` records the finance
area, shared atomic risk units, interaction mode, prompt variants across the nudge gradient, and
researcher-side source inspiration. Hidden scoring metadata such as expected disclosure lives on
risk units and should not be shown to either model unless deliberately copied into visible prompt
context. Prompt variants store structured task and guidance fields; visible scenario facts are
rendered later from validated risk units through the scenario prompt template.

Intermediate scenario-family drafts can be generated with:

```bash
uv run python scripts/generate_scenario_drafts.py --scenario-set v1
```

The generator uses Pydantic structured output for shared scenario content and each system-prompt
variant, then writes draft JSON plus Markdown review artifacts under
`data/inputs/scenarios/<scenario-set>/runs/<YYYYMMDDTHHMMSS>/`. See
`docs/experiments/scenario_generation.md` for details.

## Response scoring

TBC

Run the current tests with:

```bash
uv run pytest
```
