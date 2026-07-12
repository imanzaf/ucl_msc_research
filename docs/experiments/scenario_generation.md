# Scenario Generation Draft Pipeline

This procedure generates intermediate scenario-family drafts for the financial deception / risk-communication
benchmark through OpenRouter structured outputs. Drafts are not benchmark-ready until manually reviewed.

## Command

```bash
uv run python scripts/generate_scenario_drafts.py
```

The generator defaults to scenario set `v0.2.0`. The command writes review artifacts to:

- `data/inputs/scenarios/v0.2.0/runs/<YYYYMMDDTHHMMSS>/<scenario_family_id>.json`
- `data/inputs/scenarios/v0.2.0/runs/<YYYYMMDDTHHMMSS>/<scenario_family_id>_review.md`

Use `--scenario-set <name>` to run another scenario set, and use
`--run-id <YYYYMMDDTHHMMSS>` only when you need a deterministic output directory.
Use `--max-families <N>` to process only the first `N` scenario-family seeds in seed-file order.
Use `--family-scenario-concurrency 5` to generate the five scenario instances in each family
concurrently while still processing families sequentially.
For example, generate only the first two families with:

```bash
uv run python scripts/generate_scenario_drafts.py \
  --scenario-set v0.2.0 \
  --max-families 2 \
  --family-scenario-concurrency 5
```

## Configuration

API settings live in `configs/api_settings.py`; model settings live in
`configs/model_settings.py`. Both load `.env.static` first, then `.env`. Relevant variables:

- `OPENROUTER_API_KEY_SCENARIO_GENERATION`
- `OPENROUTER_BASE_URL`
- `OPENROUTER_APP_TITLE`
- `OPENROUTER_HTTP_REFERER`
- `OPENROUTER_TEMPERATURE`
- `OPENROUTER_SEED`
- `OPENROUTER_REQUEST_TIMEOUT_SECONDS`
- `MAX_GENERATION_RETRIES`

`OPENROUTER_API_KEY` is accepted as a backward-compatible fallback when the scenario-generation
key has not yet been configured.

The scenario-generation model is fixed by `scenario_generator_model` in `configs/models.json` and
is not selected through an environment variable.

## Inputs

The generator reads seeds from:

- `data/inputs/scenarios/<scenario-set>/scenario_generation_seeds.json`

The current default seed file is:

- `data/inputs/scenarios/v0.2.0/scenario_generation_seeds.json`

Each scenario-generation seed contains only seed-owned fields: `scenario_family_id`, `segment`,
`interaction_mode`, `tool_using`, `agent_role`, `agent_task`, `task_guidance`,
`integrity_instructions`, `user_role`, and five seed-owned `scenarios` with `scenario_id` and
`user_goal`. Guidance and integrity instructions are stored as lists. Generated fields such as
agent context, fact units, user context, initial prompts, actions, and beliefs are intentionally not
stored in the seed.

## Output Shape

The shared OpenRouter client is called with JSON-schema structured output using
`GeneratedScenarioInstance` from `src/data_models/scenarios.py`. Generation makes one LLM call per
seed-owned scenario goal. The persisted `ScenarioFamily` then attaches seed-owned family metadata
and code-owned prompt variants. Each OpenRouter call is cached under the timestamped generation run
directory at `cache/llm_calls/`.

Each generated `ScenarioInstance` must contain:

- one complete `reference_text` source-context packet in the realistic native form an agent could
  receive, such as prose, a table, transaction feed, statement, CRM record, research extract, policy
  excerpt, screening output, or JSON
- exactly 8 fact units: 2 `high_adverse`, 2 `low_adverse`, 2 `favorable`, and 2
  `neutral_distractor`
- a `reference_rationale` on each hidden fact identifying where and how the agent context supports
  it
- hidden fact metadata: `polarity`, `risk_category`, `disclosure_requirement`,
  `expected_disclosure`, `specificity_markers`, and source-wording flags
- `user_facing_context` for the user simulator
- `possible_user_actions` with binary `is_harmful` labels
- `possible_user_beliefs` labelled as `supported`, `partially_supported`, or `unsupported`
- `initial_user_prompt` keyed by `neutral_baseline`, `anxious_risk_averse`, and
  `positive_risk_seeking`

Each persisted family contains exactly three prompt variants:

- `neutral` — role, task, and source context only
- `production_baseline` — seed-owned production guidance rendered as a list
- `production_integrity` — seed-owned production guidance followed by the family's seed-owned integrity instructions

The agent sees the single scenario-level `reference_text` as extra source context. The user
question, agent role, task, and prompt condition are supplied separately. The agent does not see
hidden scoring metadata such as facts, `reference_rationale`, `expected_disclosure`, `polarity`,
`risk_category`, or belief/action labels.

## Manual Review

Review the Markdown file first, then inspect the JSON. Accept a draft only after confirming:

- the agent context is realistic, fictional, finance-native, and presented in a source format the
  agent could naturally receive
- the agent context does not include the user question, agent task, prompt variants, coaching, or
  conversational instructions
- the agent context is self-contained: any attachment, prior note, policy excerpt, statement,
  screening output, factsheet, registry extract, consensus snapshot, or transaction export needed to
  answer the user goal or support a hidden fact is included directly in `reference_text`
- references to missing, unavailable, out-of-scope, or not-included sources are used only as
  explicit evidence caveats, not as sources the agent must retrieve elsewhere
- every atomic fact is traceable to the agent context through its `reference_rationale`
- high-adverse and low-adverse facts are materially plausible for the user goal
- expected disclosure text is hidden scoring guidance and is not leaked into prompts
- `specificity_markers` are risk-material quantitative anchors only: amounts, percentages, rates,
  ratios, counts, limits, thresholds, balances, fee amounts, loss values, concentration levels,
  notice periods, durations, or decision-critical deadlines/maturities
- `specificity_markers` do not include traceability-only labels such as product names, merchant
  names, account names, masked account identifiers, case ids, row labels, source sections,
  ordinary posting/statement/meeting/travel dates, status words, or qualitative phrases
- source-wording flags describe only the generated agent context
- possible actions include both harmful and non-harmful options
- possible beliefs include supported, partially supported, and unsupported options
- persona-matched initial user prompts pursue the same user goal without naming the persona
- prompt variants do not inline generated facts or the scenario agent context
