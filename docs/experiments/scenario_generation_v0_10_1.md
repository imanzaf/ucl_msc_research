# Scenario generation V0.10.1

V0.10.1 defines the active option-information generation contract and consumes the V0.11.0 task-family seed. V0.11.0 removes shared evaluated-agent
factuality/style guidance and limits each family authority string to genuine action boundaries. Earlier paid C1 outputs remain preserved under
`data/outputs/scenario_generation/v0.10.0/`; new work is isolated by logical run beneath the active seed version at
`data/outputs/scenario_generation/v0.11.0/runs/<run-id>/`.

The active seed inputs are:

- `data/inputs/scenarios/v0.11.0/scenario_generation_seeds.json`
- `data/inputs/scenarios/v0.11.0/scenario_generation_seed_schema.json`

The seed has SHA-256 `20731f76e69af4a810e8240ce7ec6042a9493b715d29ac6f0027e7760e96b709`; its schema has SHA-256
`f314f04bbf9351446ffab9ebf82697955fc555e501e4c495a51c922be6498c57`.

## Generation boundary

One scenario is generated in one structured model call. The generator receives the broad deployment task, one decision with two named options, the
natural customer question, and the private customer/owner alignment fields. The alignment and owner-benefit mechanism constrain which product terms
are selected but must not appear in generated prose.

The exact input model remains:

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

The generated output model is:

```text
ScenarioOptionInformationDraft
└── options[2]
    ├── option_id
    ├── description
    ├── favourable_fact
    └── adverse_fact
```

The provider response contains no schema version or option name. `option_id` is retained only as structured mapping metadata so code can associate
records with seed-owned options without relying on list position. Code assigns candidate artifact schema `4.1.0` after generation. Internal option
identifiers are rejected if copied into any prose field. The generator treats each option as a fixed synthetic configuration. Descriptions explain
operation neutrally; the other fields state definite documentation-style terms, service features, or operating conditions without advice,
recommendations, comparative conclusions, or explanations of why the terms are favourable or adverse.

Rates, fees, limits, durations, thresholds, and eligibility conditions remain ordinary prose. They receive a plausible exact synthetic value when
that value is the natural product term, but there is no numeric registry or calculation layer.

## Candidate construction

`src/scenarios/openrouter_backend.py` stores the two descriptions separately as unscored option context. It maps the four generated directional
facts to hidden customer/owner coordinates, adds the seed-owned option name to each canonical proposition, and assigns stable fact and pair IDs.
Candidate and accepted scenarios use schema `4.1.0`.

The four directional facts remain the complete material-fact scoring denominator: one favourable and one adverse fact for each option. Specificity
markers are not generated; the researcher may later select zero to three exact phrases per accepted material fact.

`src/scenarios/fact_rendering.py` still supplies the current four-fact list to the evaluated prompt. Integration and formatting of the neutral
descriptions are intentionally deferred to the evaluated-prompt design step.

## Semantic review

The independent reviewer assesses meaning rather than rejecting a predefined word list. It checks:

- feasibility of both options and validity of the hidden customer/provider conflict;
- neutral, accurate operating descriptions with no additional directional material fact;
- definite, atomic, independently checkable favourable and adverse product terms;
- documentation-style wording rather than interpretation, advice, or a comparative conclusion;
- internal consistency, realism, equal required status, pair matching, and leakage absence.

Internal `OPTION_A` and `OPTION_B` leakage is prevented structurally by the generated-output and persisted-artifact models.

## Commands and outputs

The output hierarchy separates one logical seed run from the individual commands used to complete or resume it:

```text
data/outputs/scenario_generation/v0.11.0/
├── checkpoints/                         # shared frozen lifecycle gates
└── runs/
    └── <run-id>/                        # YYYYMMDDTHHMMSSffffffZ
        ├── run_config.json              # immutable seed and generation-protocol identity
        ├── invocations/
        │   └── <invocation-id>/
        │       ├── invocation_config.json
        │       └── provider_logs/
        │           ├── generation/
        │           └── review/
        ├── scenarios/
        │   └── CF001_C1/
        │       ├── candidate.json
        │       ├── automated_reviews.jsonl
        │       ├── revision_cycles.jsonl
        │       ├── terminal_decision.json
        │       ├── failures/
        │       └── superseded_reviews/
        └── researcher_review/
            └── scenario_reviews.jsonl
```

Omitting `--run-id` always creates a fresh timestamped run and prints its ID and path. Supplying that exact ID authenticates and continues the same
run. Every continuation creates a separate timestamped invocation record and separate provider-log directories, while scenario artifacts retain
stable paths. A continuation skips a hash-valid terminal scenario, reuses a valid saved candidate after an interrupted review, and records failures
without creating a terminal marker.

Generate the ten C1 candidates in a fresh run:

```bash
uv run python -m src.cli scenarios generate \
  --backend src.scenarios.openrouter_backend:create_openrouter_scenario_backend \
  --stage calibration
```

If that command stops partway through, repeat it with the printed run ID:

```bash
uv run python -m src.cli scenarios generate \
  --backend src.scenarios.openrouter_backend:create_openrouter_scenario_backend \
  --stage calibration \
  --run-id <run-id>
```

An exact C1 can also be generated or resumed with `--scenario-id CF001_C1`.

The active V0.11.0 seed contains R1 and R2 for each family. They can be generated in separate invocations within the same logical run after the C1
lifecycle gates are frozen. The first invocation persists its candidate and reports which family candidate is still pending. Once the last family
candidate exists, the command performs the required shared semantic review of the complete R batch against the fixed C1 anchor:

```bash
uv run python -m src.cli scenarios generate \
  --backend src.scenarios.openrouter_backend:create_openrouter_scenario_backend \
  --stage evaluation \
  --scenario-id CF001_R1 \
  --run-id <run-id> \
  --tight-limit-manifest data/outputs/scenario_generation/v0.11.0/checkpoints/tight_limit_manifest.json \
  --calibration-candidate data/outputs/scenario_generation/v0.11.0/runs/<run-id>/scenarios/CF001_C1/candidate.json

uv run python -m src.cli scenarios generate \
  --backend src.scenarios.openrouter_backend:create_openrouter_scenario_backend \
  --stage evaluation \
  --scenario-id CF001_R2 \
  --run-id <run-id> \
  --tight-limit-manifest data/outputs/scenario_generation/v0.11.0/checkpoints/tight_limit_manifest.json \
  --calibration-candidate data/outputs/scenario_generation/v0.11.0/runs/<run-id>/scenarios/CF001_C1/candidate.json
```

Omit `--scenario-id` and use `--use-case-id CF001` to generate the complete current R1–R2 family in one invocation. The scenario-oriented layout
does not assume that replications share an invocation, so a later seed with R3/R4 would use the same continuation mechanism and directory shape.

Every request logs returned model version, request and response hashes, token usage, provider-reported billed cost, and upstream inference cost under
its invocation. Launch `uv run risk-comm review launch --run-id <run-id>` to review that run; omitting the option selects the newest configured run.
Researcher review and acceptance remain mandatory.

Publish an accepted candidate only from its own generated bundle and run-scoped researcher review:

```bash
uv run risk-comm scenarios publish \
  --candidate data/outputs/scenario_generation/v0.11.0/runs/<run-id>/scenarios/CF001_C1/candidate.json \
  --automated-reviews data/outputs/scenario_generation/v0.11.0/runs/<run-id>/scenarios/CF001_C1/automated_reviews.jsonl \
  --revision-cycles data/outputs/scenario_generation/v0.11.0/runs/<run-id>/scenarios/CF001_C1/revision_cycles.jsonl \
  --researcher-reviews data/outputs/scenario_generation/v0.11.0/runs/<run-id>/researcher_review/scenario_reviews.jsonl \
  --accepted-root data/inputs/scenarios/v0.11.0/accepted \
  --accepted-by <researcher-id>
```
