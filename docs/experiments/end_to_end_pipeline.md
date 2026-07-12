# End-to-End Experiment Pipeline

This runbook describes the v1 OpenRouter-backed pipeline for running reviewed scenario artifacts,
scoring completed transcripts, caching all LLM calls, and producing a stable paper asset.

## Configuration

API and model settings live in `configs/api_settings.py` and `configs/model_settings.py`. Both load
`.env.static` first, then `.env`.

Required experiment variables:

- `OPENROUTER_API_KEY_SCENARIO_GENERATION`
- `OPENROUTER_API_KEY_AGENT`
- `OPENROUTER_API_KEY_USER_SIMULATOR`
- `OPENROUTER_API_KEY_SCORING`
- `OPENROUTER_BASE_URL` (defaults to `https://openrouter.ai/api/v1`)
- `OPENROUTER_TEMPERATURE`
- `OPENROUTER_SEED`
- `OPENROUTER_REQUEST_TIMEOUT_SECONDS`
- `MAX_USER_SIMULATOR_FOLLOWUP_TURNS`

Each stage uses only its role-specific key. During migration, `OPENROUTER_API_KEY` remains an
optional fallback for any role-specific key that is unset.

All model ids are fixed in `configs/models.json`; model names are not read from environment
variables. `--agent-model` may select a subset of configured agent entries but cannot introduce an
unconfigured model. Runtime CLIs validate configured model ids against OpenRouter's `/models`
endpoint before making generation calls; use `--skip-model-validation` only for offline smoke tests.

The model catalog is role-specific:

- `agent_models` contains the four models under test: GPT 5.5, Claude Sonnet 5, Llama 3.3 70B Instruct, and Qwen 2.5 72B Instruct.
- `user_model` is Gemini 3.1 Flash Lite for user-simulator turns and outcomes.
- `scoring_model` is GPT 5.4 Mini for extraction, matching, and judge calls.
- `scenario_generator_model` is GPT 5.4 Mini for scenario draft generation.

## Scenario Draft Generation

Scenario draft generation now uses OpenRouter structured outputs through the shared client:

```bash
uv run python scripts/generate_scenario_drafts.py --scenario-set v0.2.0
```

Outputs are written to:

- `data/inputs/scenarios/<scenario-set>/runs/<YYYYMMDDTHHMMSS>/<scenario_family_id>.json`
- `data/inputs/scenarios/<scenario-set>/runs/<YYYYMMDDTHHMMSS>/<scenario_family_id>_review.md`
- `data/inputs/scenarios/<scenario-set>/runs/<YYYYMMDDTHHMMSS>/cache/llm_calls/*.json`

Drafts remain review artifacts until manually checked.

## Run Scenarios

Run reviewed scenario JSON through the selected agent models and user simulator:

```bash
uv run python scripts/run_scenarios.py \
  --experiment-name deception_probe_v1 \
  --scenario-run-dir data/inputs/scenarios/v0.1.0/runs/20260705T204014 \
  --agent-model anthropic/claude-sonnet-5 \
  --agent-model meta-llama/llama-3.3-70b-instruct
```

Useful filters:

```bash
uv run python scripts/run_scenarios.py \
  --experiment-name deception_probe_v1 \
  --scenario-run-dir data/inputs/scenarios/v0.1.0/runs/20260705T204014 \
  --scenario-family-id RW001 \
  --scenario-id RW001_U01 \
  --prompt-condition neutral \
  --persona-id neutral_baseline \
  --limit 1
```

Scenario-run outputs:

- `experiments/<name>_v<N>/config.json`
- `experiments/<name>_v<N>/results/<YYYYMMDDTHHMMSS>_results.jsonl`
- `experiments/<name>_v<N>/results/<YYYYMMDDTHHMMSS>_scenario_usage.json`
- `experiments/<name>_v<N>/logs/<YYYYMMDDTHHMMSS>_run.log`
- `experiments/<name>_v<N>/cache/llm_calls/*.json`

Single-turn scenarios run initial user prompt -> agent response -> user outcome. Multi-turn scenarios
run initial user prompt -> agent response -> user-simulator follow-up loop, capped at three follow-up
user turns -> user outcome.

## Score Runs

Score completed transcripts separately:

```bash
uv run python scripts/score_runs.py \
  --experiment-name deception_probe_v1 \
  --scenario-run-dir data/inputs/scenarios/v0.1.0/runs/20260705T204014
```

Scoring outputs:

- `experiments/<name>_v<N>/results/<YYYYMMDDTHHMMSS>_scoring_results.jsonl`
- `experiments/<name>_v<N>/results/<YYYYMMDDTHHMMSS>_scoring_usage.json`
- `experiments/<name>_v<N>/logs/<YYYYMMDDTHHMMSS>_scoring_run.log`
- `experiments/<name>_v<N>/assets/<name>_v<N>_table.tex`

The scoring stage makes four LLM-assisted calls per scenario run: response fact extraction,
fact-unit matching, fact contradiction checking, and disclaimer-washing checking. Programmatic
response metrics and user-harm metrics are then computed by `src/scoring/metrics.py`.

## Joint Pipeline

Run scenario execution, scoring, and asset generation in one command:

```bash
uv run python scripts/run_experiment_pipeline.py \
  --experiment-name deception_probe_v1 \
  --scenario-run-dir data/inputs/scenarios/v0.1.0/runs/20260705T204014
```

The joint script accepts the same filters and cache flags as `run_scenarios.py`.

## Caching And Cost Logging

Each OpenRouter call is cached by a SHA-256 key over the normalized request payload, model id,
generation parameters, structured-output schema hash, stage, and prompt version.

Cache controls:

- default: read/write experiment-local cache under `experiments/<name>_v<N>/cache/llm_calls/`
- `--no-cache`: disable local cache reads and writes
- `--refresh-cache`: ignore existing cached records and write fresh results
- `--resume`: skip run units already present in earlier result files

Every cached call record stores the raw response, parsed output, request metadata, generation id,
usage, and cost. Usage summaries aggregate prompt tokens, completion tokens, total tokens, reasoning
tokens, provider cached tokens, provider cache-write tokens, local cache hits, total stored cost, and
actual run cost excluding local cache hits.

## Activation Capture

Activation capture is disabled in v1 because OpenRouter/API calls do not expose model activations.
Experiment configs and run records persist:

```json
"activation_capture": "disabled_api_only"
```

White-box activation capture should be added later as a separate local-model adapter.
