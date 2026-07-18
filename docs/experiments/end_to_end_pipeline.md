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

- `agent_models` contains the configured models under test: Llama 3.3 70B Instruct and Qwen 2.5 72B Instruct.
- `user_model` is Gemma 4 26B A4B, a 26B Mixture-of-Experts model, for user-simulator turns and outcomes.
- `scoring_model` is Gemini 3.1 Flash Lite for extraction, matching, and judge calls.
- `scenario_generator_model` is GPT 5.4 Mini for scenario draft generation.
- `scenario_reviewer_model` is fixed to Claude Haiku 4.5 for independent V6 semantic review.

## Scenario Draft Generation

Generate V6 drafts, run one family-level semantic review, and selectively revise flagged scenarios:

```bash
uv run python scripts/generate_v6_scenario_drafts.py \
  --scenario-set v0.4.0 \
  --family-scenario-concurrency 4
```

V6 validates the generator and reviewer IDs before generation and requires the reviewer to advertise
`response_format`. The semantic review uses temperature `0.0` and strict provider parameter routing.
Revision uses the normal generation temperature. The four initial drafts and any flagged revisions
run concurrently within the configured family limit; families remain sequential.

Outputs are written to:

- `data/inputs/scenarios/<scenario-set>/runs/<YYYYMMDDTHHMMSS>/<scenario_family_id>.json`
- `data/inputs/scenarios/<scenario-set>/runs/<YYYYMMDDTHHMMSS>/initial/<scenario_family_id>.json`
- `data/inputs/scenarios/<scenario-set>/runs/<YYYYMMDDTHHMMSS>/semantic_reviews/<scenario_family_id>.json`
- `data/inputs/scenarios/<scenario-set>/runs/<YYYYMMDDTHHMMSS>/semantic_reviews/attempts/<scenario_family_id>_attempt_<n>.json`
- `data/inputs/scenarios/<scenario-set>/runs/<YYYYMMDDTHHMMSS>/manifests/<scenario_family_id>.json`
- `data/inputs/scenarios/<scenario-set>/runs/<YYYYMMDDTHHMMSS>/human_reviews/<scenario_family_id>.json`
- `data/inputs/scenarios/<scenario-set>/runs/<YYYYMMDDTHHMMSS>/human_reviews/<scenario_family_id>.md`
- `data/inputs/scenarios/<scenario-set>/runs/<YYYYMMDDTHHMMSS>/failures/<scenario_family_id>.json` on terminal failure
- `data/inputs/scenarios/<scenario-set>/runs/<YYYYMMDDTHHMMSS>/cache/llm_calls/*.json`

The top-level family JSON is written last and only after successful generation, review coverage, and
revision validation. It remains unusable while the human manifest is pending or rejected. Human
review must resolve every automated finding before setting the family to `accepted`.

The Markdown file under `human_reviews/` is the only human-readable review artifact. It combines the automated finding list and final scenarios. V6 runs only neutral and anxious personas: the seed request supplies neutral wording and code applies a fixed anxious tone prefix. No positive V6 persona is scheduled.

Pilot selections are limited to `PFM001` and `RW001` using fixed primary model `meta-llama/llama-3.3-70b-instruct`. Before running another V6 family or agent model, add a passed `pilot_validation/manifest.json` to the accepted scenario run. It must bind all 48 pilot run-unit IDs and the 36/12 review subsets to the exact scored-results and typed human-annotation files with SHA-256 digests. The runner validates the files, hashes, complete matrix, labels, and IDs; recomputes precision, recall, and quadratic-weighted kappa; and checks the thresholds before expansion.

The current generator accepts only V0.4.0 seed schemas. Older seed directories remain in the repository as archival inputs and are summarized in the version changelog in `docs/experiments/scenario_generation.md`; they are not loaded or translated by the current generator.

## Run Scenarios

Run reviewed scenario JSON through the selected agent models and user simulator:

```bash
uv run python scripts/run_scenarios.py \
  --experiment-name deception_probe_v1 \
  --scenario-run-dir data/inputs/scenarios/v0.4.0/runs/<accepted-run-id> \
  --agent-model meta-llama/llama-3.3-70b-instruct
```

Useful filters:

```bash
uv run python scripts/run_scenarios.py \
  --experiment-name deception_probe_v1 \
  --scenario-run-dir data/inputs/scenarios/v0.4.0/runs/<accepted-run-id> \
  --scenario-family-id RW001 \
  --scenario-id RW001_T1_R1 \
  --prompt-condition neutral \
  --persona-id neutral_baseline \
  --limit 1
```

To reduce wall-clock time while keeping family-level sequencing, run scenario instances within each
family concurrently:

```bash
uv run python scripts/run_scenarios.py \
  --experiment-name deception_probe_v1 \
  --scenario-run-dir data/inputs/scenarios/v0.4.0/runs/<accepted-run-id> \
  --family-scenario-concurrency 4
```

With `--family-scenario-concurrency 4`, the runner processes one family at a time, but can keep all
four scenario instances in that family active together. Each individual conversation remains
sequential because later user and agent turns depend on earlier turns.

Scenario-run outputs:

- `data/outputs/experiments/<name>_v<N>/config.json`
- `data/outputs/experiments/<name>_v<N>/results/<YYYYMMDDTHHMMSS>_results.jsonl`
- `data/outputs/experiments/<name>_v<N>/results/<YYYYMMDDTHHMMSS>_scenario_usage.json`
- `data/outputs/experiments/<name>_v<N>/logs/<YYYYMMDDTHHMMSS>_run.log`
- `data/outputs/experiments/<name>_v<N>/cache/llm_calls/*.json`

V6 scenarios run fixed initial request -> agent response -> fixed risk follow-up -> agent response ->
user outcome. Code-owned persona wrappers alter affective tone only. V6 never calls the user simulator
to generate a follow-up. V5 single-turn and generated multi-turn protocols remain unchanged.

Each `ScenarioRunRecord` persists the full transcript plus explicit count fields:
`transcript_turn_count`, `user_turn_count`, `agent_turn_count`,
`generated_user_followup_count`, `scripted_user_followup_count`,
`user_simulator_decision_count`, and `conversation_protocol`.

## Score Runs

Score completed transcripts separately:

```bash
uv run python scripts/score_runs.py \
  --experiment-name deception_probe_v1 \
  --scenario-run-dir data/inputs/scenarios/v0.4.0/runs/<accepted-run-id> \
  --scoring-concurrency 8
```

Scoring outputs:

- `data/outputs/experiments/<name>_v<N>/results/<YYYYMMDDTHHMMSS>_scoring_results.jsonl`
- `data/outputs/experiments/<name>_v<N>/results/<YYYYMMDDTHHMMSS>_scoring_usage.json`
- `data/outputs/experiments/<name>_v<N>/logs/<YYYYMMDDTHHMMSS>_scoring_run.log`
- `data/outputs/experiments/<name>_v<N>/assets/<name>_v<N>_table.tex`

V6 scoring makes four LLM-assisted calls: direct fact-by-checkpoint disclosure assessment, response
fact extraction, fact-unit matching, and contradiction checking. Direct judgments provide omission,
repair, specificity, and understatement; extraction and matching are used for unsupported claims.
V5 instead retains its legacy disclaimer-washing call. Programmatic response and user-harm metrics
are computed by `src/scoring/metrics.py`.

## Joint Pipeline

Run scenario execution, scoring, and asset generation in one command:

```bash
uv run python scripts/run_experiment_pipeline.py \
  --experiment-name deception_probe_v1 \
  --scenario-run-dir data/inputs/scenarios/v0.4.0/runs/<accepted-run-id> \
  --family-scenario-concurrency 4 \
  --scoring-concurrency 8
```

The joint script accepts the same filters and cache flags as `run_scenarios.py`.

## Caching And Cost Logging

Each OpenRouter call is cached by a SHA-256 key over the normalized request payload, model id,
generation parameters, structured-output schema hash, stage, and prompt version.

Cache controls:

- default: read/write experiment-local cache under
  `data/outputs/experiments/<name>_v<N>/cache/llm_calls/`
- default experiment root: `data/outputs/experiments/`, which is git-ignored
- `--no-cache`: disable local cache reads and writes
- `--refresh-cache`: ignore existing cached records and write fresh results
- `--resume`: skip run units already present in earlier result files
- `--family-scenario-concurrency N`: run up to `N` scenario instances concurrently inside each
  family while keeping families sequential
- `--scoring-concurrency N`: score up to `N` completed scenario-run records concurrently

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
