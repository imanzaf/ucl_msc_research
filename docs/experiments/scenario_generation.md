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

The default seed file currently contains:

- `listed_company_risk_disclosure_v1`
- `supply_chain_finance_credit_review_v1`

Each seed contains only an original use-case summary, hardcoded finance area, interaction mode, and
researcher-side `source_inspiration`. Interaction mode, scenario IDs, prompt templates, and source
inspiration are code-owned fields: they are not included in the LLM-facing output models, and
scenario IDs are derived as `<scenario_family_id>_<nudge-level>` after parsing. Downloaded
benchmark references are stored for auditability, but they are not sent to the LLM.

## Output Shape

The OpenAI Responses API is called with Pydantic structured output using the LLM-facing models in
`src/data_models/scenarios.py`: one `GeneratedScenario` call creates shared scenario content and
risk units, then one `GeneratedPromptVariant` call creates each `zero`, `low`, and `high` prompt
variant. The persisted `Scenario` model inherits from `GeneratedScenario` and adds seed-controlled
metadata, prompt variants, prompt template, and source inspiration before saving with
`model_dump_json`.

Each generated scenario must contain:

- exactly four shared risk units: one `high`, one `medium`, one `low`, and one `neutral`
- exactly three prompt variants: `zero`, `low`, and `high`
- seed-controlled `finance_area` and `interaction_mode`
- deterministic scenario IDs of the form `<scenario_family_id>_<nudge-level>`
- no embedded user persona, review status, execution-turn count, or target falsifiability field
- structured `system_prompt.task` and `system_prompt.guidance` fields for each prompt variant
- no inlined fact lists inside prompt variants; facts are rendered from `risk_units` using `prompt_template`

## Manual Review

Review the Markdown file first, then inspect the JSON. Accept a draft only after confirming:

- risk facts are original and finance-native
- risk units are atomic and materiality labels are defensible
- high-nudge prompts explicitly request risk omission or concealment
- low-nudge prompts create goal conflict without explicitly requesting deception
- zero-nudge prompts are balanced and neutral
- hidden scoring metadata is not included in prompts shown to the financial-agent model
- prompt facts come from `risk_units` rather than duplicated free-form text inside prompt variants
