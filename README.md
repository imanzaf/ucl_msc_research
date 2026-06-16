# ucl_msc_research

Repo containing code and paper for UCL IFT final MSc dissertation.

## Project structure

- `configs/` - Pydantic settings for API keys and project configuration.
- `docs/` - Research plans, distinction guidance, and supporting documents.
- `src/data_models/` - Pydantic models for benchmark and scoring data structures.
- `tex_src/` - Dissertation LaTeX source and references.
- `tests/` - Unit tests for project code.

## Scenario design

Scenario specifications live in `src/data_models/scenarios.py`. Each `ScenarioSpec` records the
controlled nudge level, target falsifiability level for high-nudge variants, reusable user persona,
prompt execution context, atomic risk units, interaction mode, and benchmark provenance. Hidden
scoring metadata such as expected disclosure lives on risk units and should not be shown to either
model unless deliberately copied into visible prompt context.

## Response scoring

Response scoring models live in `src/data_models/scoring.py`. Each `ResponseScore` records the
scenario and run identifiers, observed falsifiability level, agent tone, response-level aggregate
metrics, and per-unit scoring records. Each `UnitScore` tracks disclosure, specificity, framing,
ordering, emphasis, and a rationale for one material-risk unit.

Run the current tests with:

```bash
uv run pytest
```
