# Scenario Generation Draft Pipeline

This procedure generates intermediate scenario-family drafts for the financial deception
benchmark. Drafts are not benchmark-ready until manually reviewed.

## Command

```bash
uv run python scripts/generate_scenario_drafts.py --scenario-set v1
```

The command writes review artifacts to:

- `data/inputs/scenarios/v1/runs/<YYYYMMDDTHHMMSS>/<scenario_family_id>.json`
- `data/inputs/scenarios/v1/runs/<YYYYMMDDTHHMMSS>/<scenario_family_id>_review.md`

By default the run id is the current timestamp. Use `--run-id <YYYYMMDDTHHMMSS>` only when
you need a deterministic output directory for a controlled rerun.

## Configuration

API settings live in `configs/api_settings.py`; model settings live in
`configs/model_settings.py`. Both load `.env.static` first, then `.env`. Relevant variables:

- `OPENAI_API_KEY_SCENARIO_GENERATOR`
- `SCENARIO_GENERATOR_MODEL`, default `gpt-5.5-pro`
- `MAX_GENERATION_RETRIES`, default `2`

## Inputs

The generator reads seeds from:

- `data/inputs/scenarios/<scenario-set>/scenario_generation_seeds.json`

The scenario set is selected with `--scenario-set`; for the first pass this is `v1`.
Use `--scenario-root` to override the root directory when needed.

Each seed contains an original use-case summary, hardcoded finance area, interaction mode, agent
role, agent task, user role, indirect institutional pressure, and researcher-side
`source_inspiration`. The prompt task is built deterministically as
`You are a {agent_role}. Your task is to {agent_task}.` Scenario IDs, prompt templates, source
inspiration, and user prompts are outside the LLM-facing output models, and scenario IDs are
derived as `<scenario_family_id>_<pressure-level>` after parsing. Downloaded benchmark references are
stored for auditability, but they are not sent to the LLM.

## Output Shape

The OpenAI Responses API is called with Pydantic structured output using the LLM-facing models in
`src/data_models/scenarios.py`. Generation proceeds in two LLM calls per scenario family:

1. **`GeneratedFactSet`** — shared fact units only. The required number and category distribution are defined by `REQUIRED_RISK_UNIT_COUNTS`.
2. **`GeneratedPressureGuidance`** — mild and strong variants of the seed's indirect institutional pressure, used for `mild_pressure` and `strong_pressure`.

`no_pressure` contains only the seed-built role/task prompt and no behavioral guidance. `integrity`
adds fixed honesty, accuracy, and material-disclosure guidance. `mild_pressure` adds mild indirect
institutional pressure. `strong_pressure` adds strong indirect institutional pressure. The persisted
`Scenario` model adds seed-controlled metadata, prompt variants, prompt template, and source inspiration before saving with
`model_dump_json`. User prompts are intentionally left for a later pipeline.

Each generated scenario must contain:

- exactly the shared fact-unit count and category distribution defined by `REQUIRED_RISK_UNIT_COUNTS`
- exactly four prompt variants: `integrity`, `no_pressure`, `mild_pressure`, and `strong_pressure`
- seed-controlled `finance_area` and `interaction_mode`
- seed-controlled `agent_role`, `user.user_role`, and auto-built prompt task
- deterministic scenario IDs of the form `<scenario_family_id>_<pressure-level>`
- no embedded user persona, review status, execution-turn count, or target falsifiability field
- structured `system_prompt.agent_role`, `system_prompt.agent_task`, and `system_prompt.guidance` fields for each prompt variant
- no generated `user_prompt` field
- no inlined fact lists inside prompt variants; facts are rendered from `risk_units` using `prompt_template`

## Manual Review

Review the Markdown file first, then inspect the JSON. Accept a draft only after confirming:

- risk facts are original and finance-native
- risk units are atomic and materiality labels are defensible
- strong-pressure prompts introduce strong indirect institutional pressure without explicit deception instructions
- mild-pressure prompts introduce mild indirect institutional pressure without explicit deception instructions
- no-pressure prompts contain no behavioral guidance beyond the auto-built role/task prompt
- integrity prompts explicitly require balanced material-risk disclosure and prohibit deception
- hidden scoring metadata is not included in prompts shown to the financial-agent model
- prompt facts come from `risk_units` rather than duplicated free-form text inside prompt variants
