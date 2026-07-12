# ucl_msc_research

Repo containing code and paper for UCL IFT final MSc dissertation.

## Project structure

- `configs/` - Pydantic settings for API keys and project configuration.
- `docs/` - Research plans, experiment design, and supporting documents.
- `data/outputs/experiments/` - Ignored end-to-end experiment outputs, caches, logs, and paper assets.
- `scripts/` - Runnable research utilities and draft-generation pipelines.
- `src/data_models/` - Pydantic models for benchmark and scoring data structures.
- `src/prompts/` - Grouped prompt templates for scenarios, user simulation, output processing, and scoring.
- `src/scoring/` - Pure metric calculators for response and user-harm scoring.
- `tex_src/` - Dissertation LaTeX source and references.
- `tests/` - Unit tests for project code.

## Scenario design

Scenario specifications live in `src/data_models/scenarios.py`. Each `ScenarioFamily` records the
finance domain, interaction mode, tool-use flag, seed-owned agent and user roles, three prompt
conditions, and five generated `ScenarioInstance` records. Each instance contains one realistic
agent-visible source-context packet, plus hidden atomic facts and traceability rationales for scoring,
user-facing context for the user simulator, possible user actions, possible user beliefs, and
persona-matched initial user prompts.

Intermediate scenario-family drafts can be generated with:

```bash
uv run python scripts/generate_scenario_drafts.py
```

The generator defaults to scenario set `v0.2.0` and uses one Pydantic structured-output call per
seed-owned user goal through OpenRouter. Both production-baseline guidance and family-specific
production-integrity instructions are seed-owned lists rendered as prompt bullets. The generator
writes draft JSON plus Markdown review artifacts under
`data/inputs/scenarios/<scenario-set>/runs/<YYYYMMDDTHHMMSS>/`. Use `--max-families <N>` to process
only the first `N` family seeds during iterative runs. See
`docs/experiments/scenario_generation.md` for details.

## End-to-end pipeline

Reviewed scenario artifacts can be run and scored with:

```bash
uv run python scripts/run_experiment_pipeline.py \
  --experiment-name deception_probe_v1 \
  --scenario-run-dir data/inputs/scenarios/v0.1.0/runs/20260705T204014 \
  --family-scenario-concurrency 5 \
  --scoring-concurrency 8
```

The pipeline uses OpenRouter for agent, user-simulator, and scoring calls; caches every LLM call under
`data/outputs/experiments/<name>_v<N>/cache/llm_calls/`; writes transcripts and scoring records under
`data/outputs/experiments/<name>_v<N>/results/`; logs token usage and cost summaries; and generates a stable
LaTeX summary table in `data/outputs/experiments/<name>_v<N>/assets/`. Activation capture is disabled in v1
because API-only OpenRouter runs do not expose model activations. The full model catalog and
role-specific model selections live only in `configs/models.json`; runtime generation parameters
live in `configs/model_settings.py`. Use `--family-scenario-concurrency 5` to run the five scenario
instances within each family concurrently while keeping families sequential; use
`--scoring-concurrency N` to score completed records concurrently. See
`docs/experiments/end_to_end_pipeline.md` for commands and output paths.

OpenRouter credentials are configured separately for scenario generation, agent responses,
user simulation, and scoring through `OPENROUTER_API_KEY_SCENARIO_GENERATION`,
`OPENROUTER_API_KEY_AGENT`, `OPENROUTER_API_KEY_USER_SIMULATOR`, and
`OPENROUTER_API_KEY_SCORING`. The legacy `OPENROUTER_API_KEY` remains a fallback for unset roles
during migration.

## Response scoring

The scoring implementation uses LLM fact extraction, LLM fact-to-ground-truth matching, separate LLM
checks for contradiction and disclaimer washing, and pure Python metric calculators.
See `docs/experiments/scoring.md` for the post-run scoring flow and `docs/experiments/metrics.md`
for the implemented formulas and interpretation notes.

Run the current tests with:

```bash
uv run pytest
```
