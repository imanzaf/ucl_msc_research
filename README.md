# ucl_msc_research

Repo containing code and paper for UCL IFT final MSc dissertation.

## Project structure

- `configs/` - Pydantic settings for API keys and project configuration.
- `docs/` - Research plans, distinction guidance, and supporting documents.
- `src/data_models/` - Pydantic models for benchmark data structures.
- `tex_src/` - Dissertation LaTeX source and references.
- `tests/` - Unit tests for project code.

## Scenario design

Scenario specifications live in `src/data_models/scenarios.py`. Each `ScenarioSpec` records the
controlled nudge level, target falsifiability level for high-nudge variants, persona placeholder,
atomic risk units, interaction mode, output format, task objective, and benchmark provenance.
Stakeholder information lives inside the user persona model.

Run the current tests with:

```bash
uv run pytest
```
