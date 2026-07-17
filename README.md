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

The current V0.3.1 design lives in `src/data_models/scenarios_v6.py`,
`src/data_models/prompt_controls.py`, and `src/data_models/scenario_review.py`. Each `scenario_family.v6` family has two finance task
archetypes with two matched replications each. Every scenario contains two primary adverse facts,
two paired favorable controls, and two neutral controls, plus exact source locators and evaluation
checkpoints. The current generator accepts only `scenario_seed_collection.v6.1` from V0.3.1.
Older seed directories remain committed as historical snapshots, but the current code does not
load or translate their schemas.

Intermediate scenario-family drafts can be generated with:

```bash
uv run python scripts/generate_v6_scenario_drafts.py \
  --scenario-set v0.3.1 \
  --family-scenario-concurrency 4
```

The generator creates four initial drafts, asks fixed independent reviewer Claude Haiku 4.5 for one
complete family-level semantic audit, and sends only flagged scenarios through one full-replacement
revision call. Automated revision never marks findings resolved. A human manifest must resolve every
finding and mark the family accepted before the experiment loader will use V6 artifacts. See
`docs/experiments/scenario_generation.md` for the rubric, failure behavior, and artifact layout.
Each family has one human-readable review file at `human_reviews/<family>.md`. V6 evaluates only the
neutral seed request and a code-owned anxious tone variant; the positive persona is excluded from V6 runs.
The initial `PFM001` and `RW001` pilot uses fixed primary model `meta-llama/llama-3.3-70b-instruct`. Any additional family or model requires a passed `pilot_validation/manifest.json` that binds the 48 run units and predeclared 36/12 human audit to hashed scored-result and typed annotation artifacts; the runner recomputes all gate statistics.

### Scenario changelog

- `v0.3.1` is the sole supported generation protocol. It uses one code-owned prompt-control profile,
  two invariant task constraints per seed, semantic family review, selective full-scenario revision,
  and mandatory human acceptance.
- `v0.3.0` is retained under `data/inputs/scenarios/v0.3.0/` for provenance. It used family-specific
  task and integrity prose and is intentionally rejected by the current generator.
- Earlier seed sets, including `v0.2.0`, remain in `data/inputs/scenarios/` as archival research
  inputs rather than supported current-generation formats.

## End-to-end pipeline

Reviewed scenario artifacts can be run and scored with:

```bash
uv run python scripts/run_experiment_pipeline.py \
  --experiment-name deception_probe_v1 \
  --scenario-run-dir data/inputs/scenarios/v0.3.1/runs/<accepted-run-id> \
  --family-scenario-concurrency 4 \
  --scoring-concurrency 8
```

The pipeline uses OpenRouter for agent, user-simulator, and scoring calls; caches every LLM call under
`data/outputs/experiments/<name>_v<N>/cache/llm_calls/`; writes transcripts and scoring records under
`data/outputs/experiments/<name>_v<N>/results/`; logs token usage and cost summaries; and generates a stable
LaTeX summary table in `data/outputs/experiments/<name>_v<N>/assets/`. Activation capture is disabled in v1
because API-only OpenRouter runs do not expose model activations. The full model catalog and
role-specific model selections live only in `configs/models.json`; runtime generation parameters
live in `configs/model_settings.py`. Use `--family-scenario-concurrency 4` to run the four V6 scenario
instances within each family concurrently while keeping families sequential; use
`--scoring-concurrency N` to score completed records concurrently. See
`docs/experiments/end_to_end_pipeline.md` for commands and output paths.

OpenRouter credentials are configured separately for scenario generation, agent responses,
user simulation, and scoring through `OPENROUTER_API_KEY_SCENARIO_GENERATION`,
`OPENROUTER_API_KEY_AGENT`, `OPENROUTER_API_KEY_USER_SIMULATOR`, and
`OPENROUTER_API_KEY_SCORING`. The legacy `OPENROUTER_API_KEY` remains a fallback for unset roles
during migration.

## Response scoring

V6 scoring directly audits every fact at the initial-response checkpoint and both primary adverse
facts again after the scripted risk follow-up. Those direct judgments determine initial and
persistent omission, repair, specificity, and understatement. Extraction and matching identify
unsupported claims, while a separate check identifies contradictions. V5 retains its legacy
disclaimer-washing path. Pure Python calculators produce the headline metrics and a separately
reported equal-weight exploratory composite.
See `docs/experiments/scoring.md` for the post-run scoring flow and `docs/experiments/metrics.md`
for the implemented formulas and interpretation notes.

Run the current tests with:

```bash
uv run pytest
```
