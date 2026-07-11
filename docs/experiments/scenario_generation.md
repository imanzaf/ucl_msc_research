# Scenario Generation Draft Pipeline

This procedure generates intermediate scenario-family drafts for the financial deception / risk-communication
benchmark through OpenRouter structured outputs. Drafts are not benchmark-ready until manually reviewed.

## Command

```bash
uv run python scripts/generate_scenario_drafts.py
```

The generator defaults to scenario set `v0.1.0`. The command writes review artifacts to:

- `data/inputs/scenarios/v0.1.0/runs/<YYYYMMDDTHHMMSS>/<scenario_family_id>.json`
- `data/inputs/scenarios/v0.1.0/runs/<YYYYMMDDTHHMMSS>/<scenario_family_id>_review.md`

Use `--scenario-set <name>` to run another scenario set, and use
`--run-id <YYYYMMDDTHHMMSS>` only when you need a deterministic output directory.

## Configuration

API settings live in `configs/api_settings.py`; model settings live in
`configs/model_settings.py`. Both load `.env.static` first, then `.env`. Relevant variables:

- `OPENROUTER_API_KEY`
- `OPENROUTER_BASE_URL`
- `OPENROUTER_APP_TITLE`
- `OPENROUTER_HTTP_REFERER`
- `SCENARIO_GENERATOR_MODEL` (default `openai/gpt-5.4`)
- `OPENROUTER_TEMPERATURE`
- `OPENROUTER_SEED`
- `OPENROUTER_REQUEST_TIMEOUT_SECONDS`
- `MAX_GENERATION_RETRIES`

## Inputs

The generator reads seeds from:

- `data/inputs/scenarios/<scenario-set>/scenario_generation_seeds.json`

The current default seed file is:

- `data/inputs/scenarios/v0.1.0/scenario_generation_seeds.json`

Each scenario-generation seed contains only seed-owned fields: `scenario_family_id`, `segment`,
`interaction_mode`, `tool_using`, `agent_role`, `agent_task`, `task_guidance`, `user_role`, and five
seed-owned `scenarios` with `scenario_id` and `user_goal`. Generated fields such as fact units,
source/reference passages, user context, initial prompts, actions, and beliefs are intentionally not
stored in the seed.

## Output Shape

The shared OpenRouter client is called with JSON-schema structured output using
`GeneratedScenarioInstance` from `src/data_models/scenarios.py`. Generation makes one LLM call per
seed-owned scenario goal. The persisted `ScenarioFamily` then attaches seed-owned family metadata
and code-owned prompt variants. Each OpenRouter call is cached under the timestamped generation run
directory at `cache/llm_calls/`.

Each generated `ScenarioInstance` must contain:

- exactly 8 fact units: 2 `high_adverse`, 2 `low_adverse`, 2 `favorable`, and 2
  `neutral_distractor`
- natural `source` labels and `reference_text` passages shown to the agent
- hidden fact metadata: `polarity`, `risk_category`, `disclosure_requirement`,
  `expected_disclosure`, `specificity_markers`, and source-wording flags
- `user_facing_context` for the user simulator
- `possible_user_actions` with binary `is_harmful` labels
- `possible_user_beliefs` labelled as `supported`, `partially_supported`, or `unsupported`
- `initial_user_prompt` keyed by `neutral_baseline`, `anxious_risk_averse`, and
  `positive_risk_seeking`

Each persisted family contains exactly three prompt variants:

- `neutral` — role, task, and reference information only
- `production_baseline` — seed-owned production guidance
- `production_integrity` — seed-owned production guidance plus fixed integrity guidance

The agent sees source-labelled `reference_text` passages. It does not see hidden scoring
metadata such as `expected_disclosure`, `polarity`, `risk_category`, or belief/action labels.

## Manual Review

Review the Markdown file first, then inspect the JSON. Accept a draft only after confirming:

- reference passages are realistic, fictional, finance-native, and traceable to atomic fact units
- high-adverse and low-adverse facts are materially plausible for the user goal
- expected disclosure text is hidden scoring guidance and is not leaked into prompts
- source-wording flags describe only the generated reference text
- possible actions include both harmful and non-harmful options
- possible beliefs include supported, partially supported, and unsupported options
- persona-matched initial user prompts pursue the same user goal without naming the persona
- prompt variants do not inline generated facts or reference passages
