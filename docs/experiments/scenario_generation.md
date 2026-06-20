# Scenario Generation Draft Pipeline

This procedure generates intermediate scenario-family drafts for the financial deception
benchmark. Drafts are not benchmark-ready until manually reviewed.

## Command

```bash
uv run python scripts/generate_scenario_drafts.py --all-defaults
```

The command writes review artifacts to:

- `data/outputs/scenario_drafts/<scenario_family_id>.json`
- `data/outputs/scenario_drafts/<scenario_family_id>_review.md`

## Configuration

API settings live in `configs/api_settings.py`; model settings live in
`configs/model_settings.py`. Both load `.env.static` first, then `.env`. Relevant variables:

- `OPENAI_API_KEY_SCENARIO_GENERATOR`
- `SCENARIO_GENERATOR_MODEL`, default `gpt-5.5-pro`
- `MAX_GENERATION_RETRIES`, default `2`

## Inputs

The generator reads seeds from:

- `data/inputs/scenarios/scenario_generation_seeds.json`

The default seed file currently contains:

- `listed_company_risk_disclosure_v1`
- `supply_chain_finance_credit_review_v1`

Each seed contains only an original use-case summary, hardcoded finance area, and
researcher-side `source_inspiration`. Scenario IDs are derived as
`<scenario_family_id>_<nudge-level>`. Downloaded benchmark references are stored for auditability,
but they are not sent to the LLM.

## Output Shape

The OpenAI Responses API is called with Pydantic structured output using
`src/data_models/scenarios.py::Scenario`. The code validates hardcoded seed fields and overwrites
`source_inspiration` from the seed file before saving the same `Scenario` model with
`model_dump_json`.

Each generated scenario must contain:

- exactly four shared risk units: one `high`, one `medium`, one `low`, and one `neutral`
- exactly three prompt variants: `zero`, `low`, and `high`
- deterministic scenario IDs of the form `<scenario_family_id>_<nudge-level>`
- no embedded user persona, review status, execution-turn count, or target falsifiability field

## Manual Review

Review the Markdown file first, then inspect the JSON. Accept a draft only after confirming:

- risk facts are original and finance-native
- risk units are atomic and materiality labels are defensible
- high-nudge prompts explicitly request risk omission or concealment
- low-nudge prompts create goal conflict without explicitly requesting deception
- zero-nudge prompts are balanced and neutral
- hidden scoring metadata is not included in prompts shown to the financial-agent model
