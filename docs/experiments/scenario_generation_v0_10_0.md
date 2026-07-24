# Scenario generation V0.10.0

V0.10.0 is the active immutable scenario protocol. It contains ten broad financial-assistant task families and three distinct decisions per family:
one calibration decision (`C1`) and two held-out decisions (`R1`, `R2`). V0.5.1–V0.9.0 remain byte-preserved historical seeds.

The active inputs are:

- `data/inputs/scenarios/v0.10.0/scenario_generation_seeds.json`
- `data/inputs/scenarios/v0.10.0/scenario_generation_seed_schema.json`

The seed has SHA-256 `cf912e7f4d8ae6c2e8dd4d0b02f753a68b017444880e4ac4f297423984baee5f`; its schema has SHA-256
`b37ebe9bc1fdb017259aa043cf07ebf0af3b167beb84adc36a822593594c7c1d`.

Runtime code supports only this seed and schema. Earlier seed JSON files remain historical research artifacts, but active Pydantic models, validators,
generation commands, schemas, and tests do not load or execute their formats.

## Design boundary

Each use case owns only the broad deployed role, entity type, task, and authority limit. Each replication then owns:

- `scenario_id`
- `decision_type`
- exactly two `{option_id, option_name}` records
- a natural initial customer question and follow-up question
- `customer_supporting_option`
- `owner_supporting_option`
- `owner_benefit_mechanism`
- the counterbalanced `presentation_order`

The ownership mapping and owner-benefit mechanism are research-only design fields. They are supplied to the scenario generator so it can create a
credible latent conflict, but code prevents those labels and values from entering the evaluated prompt.

Across all 30 scenarios, each option ID is customer-supporting 15 times and appears first 15 times. The ten C1 scenarios are independently balanced
5/5 on both dimensions. These code-owned checks prevent a fixed `OPTION_A` or first-position shortcut.

## Single-call generator contract

One scenario is generated with one structured model call. There is no intermediate fact call, evidence call, or minimal-response call.

The exact input data model is:

```text
ScenarioGenerationInput
├── deployment
│   ├── entity_type
│   └── general_task
└── decision
    ├── decision_type
    ├── options[2]
    │   ├── option_id
    │   └── option_name
    ├── customer_query
    ├── customer_supporting_option
    ├── owner_supporting_option
    └── owner_benefit_mechanism
```

The exact generated output is:

```text
ScenarioFactDraft
├── schema_version = "4.0.0"
└── facts[4]
    ├── option_id
    ├── polarity = benefit | downside
    └── text
```

The output validator requires exactly one fact in every option × polarity cell. Each fact is capped at 400 characters, and the structured call has
a 2,000-token output ceiling. The generator produces no title, headings, evidence packet, source items, spans, numeric registry, neutral facts,
materiality rationale, specificity elements, recommendation, or minimal response.

The active system prompt is defined in `src/prompts/scenario_generation.py`. In substance, it asks for four self-contained,
customer-relevant facts; requires paired benefits and downsides to be comparable; makes numeric detail optional; and prohibits disclosure of the
ownership mapping or commercial mechanism.

## Candidate construction and evaluated input

`src/scenarios/openrouter_backend.py` maps the neutral option IDs to hidden customer/owner decision coordinates after generation. Code assigns stable
fact and pair IDs, equal required status, materiality rating, and provenance. Candidate schema V4 serializes neither a source packet nor evidence
spans.

`src/scenarios/fact_rendering.py` renders the accepted propositions themselves as four unlabelled bullets. It applies the seed-owned option order and
a deterministic, scenario-dependent polarity order. `src/prompts/experiment.py` places that exact list under `## Available information`, alongside
the family-level deployment contract and natural customer question. The evaluated model is therefore given the same four propositions that are
later scored, matching the direct-fact design rather than duplicating each proposition in an evidence sentence.

Specificity markers are not generated. During researcher review, zero to three exact phrases may be selected from each accepted fact for later
specificity scoring. A fact may legitimately have no specificity marker.

## Review and execution

Generate the ten C1 candidates:

```bash
uv run python -m src.cli scenarios generate \
  --backend src.scenarios.openrouter_backend:create_openrouter_scenario_backend \
  --stage calibration
```

After the C1 lifecycle gates are frozen, generate one family’s R1–R2 batch:

```bash
uv run python -m src.cli scenarios generate \
  --backend src.scenarios.openrouter_backend:create_openrouter_scenario_backend \
  --stage evaluation \
  --use-case-id CF001 \
  --tight-limit-manifest data/outputs/scenario_generation/v0.10.0/checkpoints/tight_limit_manifest.json \
  --calibration-candidate data/outputs/scenario_generation/v0.10.0/CF001_C1/candidate.json
```

Generation needs no scenario-generation dry run, cost report, or approval artifact. Every OpenRouter request records the returned model version,
request and response hashes, token usage, and provider-reported billed and upstream costs in candidate provenance and structured provider logs under
`data/outputs/scenario_generation/v0.10.0/raw_provider/`.

The independent semantic reviewer assesses C1 individually and R1–R2 together with the frozen C1 as a diversity anchor. It reviews option
feasibility, customer/owner conflict validity, four-fact completeness, pair comparability, realism, and leakage. One bounded regeneration is allowed;
unresolved findings go to manual restructuring. Researcher acceptance remains mandatory.

## Experiment dimensions

- Calibration: 10 C1 × 3 models × 4 cells = 120 conversations, 240 assistant responses.
- Primary: 20 held-out scenarios × 3 models × 4 cells = 240 conversations, 480 responses.
- Material-priority exploratory study: 20 × 3 × 2 cells = 120 conversations, 240 responses.
- Brevity-locus exploratory study: 20 × 3 × 1 cell = 60 conversations, 120 responses.

The research basis for the ten families and their decisions is documented in `docs/experiments/scenario_research.md`.
