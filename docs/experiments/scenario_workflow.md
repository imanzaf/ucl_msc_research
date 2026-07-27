# Scenario workflow

This workflow covers V0.11.0 scenario generation, run-ID continuation, researcher review, revision, and publication. The active seed inputs are:

- `data/inputs/scenarios/v0.11.0/scenario_generation_seeds.json`
- `data/inputs/scenarios/v0.11.0/scenario_generation_seed_schema.json`

The seed SHA-256 is `20731f76e69af4a810e8240ce7ec6042a9493b715d29ac6f0027e7760e96b709`; the seed-schema SHA-256 is
`f314f04bbf9351446ffab9ebf82697955fc555e501e4c495a51c922be6498c57`. Candidate and accepted artifacts use schema `4.1.0`.

## Generation contract

One structured model call receives the broad deployment task and one seed-owned decision: two named options, the natural customer question, the
private customer/owner alignment, and the owner-benefit mechanism. It returns a neutral operating description plus one favourable and one adverse
fact for each option. The hidden alignment constrains generation but must not appear in generated prose.

Only the four directional facts form the material-fact scoring denominator. Descriptions are unscored option context. Specificity markers are not
generated; during review, the researcher may select zero to three exact phrases per material fact.

The independent semantic reviewer checks option feasibility, operating-description neutrality, fact definiteness and materiality, internal
consistency, pair comparability, finance realism, authority boundaries, and hidden-design leakage. Deterministic validation separately checks
structure, identifiers, counts, hashes, and option-by-polarity coverage.

Relevant implementation: `src/prompts/scenario_generation.py`, `src/scenarios/openrouter_backend.py`,
`src/scenarios/fact_rendering.py`, and `src/scenarios/run_layout.py`.

## Run structure and continuation

```text
data/outputs/scenario_generation/v0.11.0/
├── checkpoints/
└── <run-id>/
    ├── run_config.json
    ├── researcher_review/
    │   └── scenario_reviews.jsonl
    └── <round-id>/
        ├── invocation_config.json
        ├── provider_logs/
        ├── inputs/
        └── scenarios/
            └── <scenario-id>/
                ├── candidate.json
                ├── automated_reviews.jsonl
                ├── revision_cycles.jsonl
                ├── terminal_decision.json
                └── failures/
```

`--run-id` is a stable lowercase snake-case name with an explicit version suffix, such as `c1_calibration_v1`. Each generation or revision attempt
creates a timestamped round. Reusing the run ID authenticates and continues that history; using a new run ID starts an independent run from the
same seed.

Current-set resolution scans all rounds and selects the newest candidate for each scenario. An interrupted command resumes its incomplete matching
round and reuses valid saved candidates. Publication never falls back to an older accepted candidate when a newer candidate is pending or marked
`revise`.

## Generate or resume C1

Generate all ten C1 candidates:

```bash
uv run risk-comm scenarios generate \
  --backend src.scenarios.openrouter_backend:create_openrouter_scenario_backend \
  --stage calibration \
  --run-id c1_calibration_v1
```

Repeat the same command after an interruption to resume. Add `--scenario-id CF001_C1` to target one scenario.

## Review scenarios

Launch the local-only Streamlit reviewer for the run:

```bash
uv run risk-comm review launch \
  --run-id c1_calibration_v1 \
  --server-address 127.0.0.1
```

The scenario page shows the customer dialogue, assistant remit, option descriptions, and four directional facts as readable cards. Hidden
customer/provider alignment and compact pair diagnostics remain available in expanders. Five concise criteria guide one overall `accept` or
`revise` decision:

1. realistic context and appropriate authority boundary;
2. two feasible options;
3. definite, relevant, documentation-style facts;
4. a valid customer/provider conflict; and
5. sufficiently comparable fact pairs.

The criteria are guidance, not separately persisted checkboxes or automatic thresholds. Optional specificity phrases are stored independently
from the decision. The app has no provider client and cannot generate, score, or run experiments. Progress is written immediately to
`<run-id>/researcher_review/scenario_reviews.jsonl` and remains resumable if the browser closes.

## Regenerate revised scenarios

After review, repeat the generation command:

```bash
uv run risk-comm scenarios generate \
  --backend src.scenarios.openrouter_backend:create_openrouter_scenario_backend \
  --stage calibration \
  --run-id c1_calibration_v1
```

Only current `revise` cases are regenerated. Nonblank researcher notes are passed verbatim as revision feedback, and each replacement records its
parent candidate and review hashes. The reviewer subsequently shows only regenerated candidate hashes without a current decision.

## Generate R1 and R2 separately

Evaluation replications can be generated in separate commands under one logical run:

```bash
uv run risk-comm scenarios generate \
  --backend src.scenarios.openrouter_backend:create_openrouter_scenario_backend \
  --stage evaluation \
  --scenario-id CF001_R1 \
  --run-id evaluation_scenarios_v1 \
  --tight-limit-manifest data/outputs/scenario_generation/v0.11.0/checkpoints/tight_limit_manifest.json \
  --calibration-run-id c1_calibration_v1

uv run risk-comm scenarios generate \
  --backend src.scenarios.openrouter_backend:create_openrouter_scenario_backend \
  --stage evaluation \
  --scenario-id CF001_R2 \
  --run-id evaluation_scenarios_v1 \
  --tight-limit-manifest data/outputs/scenario_generation/v0.11.0/checkpoints/tight_limit_manifest.json \
  --calibration-run-id c1_calibration_v1
```

The combined family review waits until both R candidates exist. Omit `--scenario-id` and use `--use-case-id CF001` to create the complete family in
one round. The layout does not depend on a fixed replication count, so later R3/R4 seeds can use the same mechanism.

## Publish the accepted set

Once every newest candidate in scope is accepted:

```bash
uv run risk-comm scenarios publish \
  --run-id c1_calibration_v1 \
  --scope calibration \
  --published-by <researcher-id>
```

Publication resolves the newest candidate for every scenario, authenticates the matching `accept` decision, stages immutable accepted bundles,
builds the self-hashed scope manifest, and promotes both to `data/inputs/scenarios/v0.11.0/`. The lower-level `scenarios build-manifest` command is
reserved for validation and recovery.

Every provider request retains model identity, request and response hashes, token usage, provider-reported cost, and upstream inference cost under
its timestamped round.
