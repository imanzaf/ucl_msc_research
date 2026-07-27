# Scenario workflow

This workflow covers V1.0.0 scenario generation, run-ID continuation, researcher review, revision, and publication. The active seed inputs are:

- `data/inputs/scenarios/v1.0.0/scenario_generation_seeds.json`
- `data/inputs/scenarios/v1.0.0/scenario_generation_seed_schema.json`

The seed SHA-256 is `846c0ab8a89387d15d7ae53e171ecd6f43cdace4f554889a3f52d1b16ec9b5ff`; the seed-schema SHA-256 is
`68eacf33bc69eb4c77f3bc8ce3c40ff2e17ab24dc9dcb2281895a2aaa9749503`. Candidate and accepted artifacts use schema `5.0.0`.

## Generation contract

One structured model call receives the broad deployment task and one seed-owned decision: two named options, the neutral customer query, the
owner-supporting option, and the owner-benefit mechanism. It returns a neutral operating description plus one favourable and one adverse fact for
each option. The hidden design requires only that the owner-supporting option create more of the stated owner benefit; the alternative is not
assumed to be better for the customer.

Each replication also owns a natural `neutral_user_query`, a semantically equivalent `concerned_user_query`, and one generic `follow_up_query`.
These reviewed seed strings are used directly in evaluated prompts; there is no reusable cue-prefix or cue-template layer.

Only the four directional facts form the material-fact scoring denominator. Descriptions are unscored option context. Specificity markers are not
generated; during review, the researcher may select zero to three exact phrases per material fact.

The independent semantic reviewer checks option feasibility, operating-description neutrality, fact definiteness and materiality, internal
consistency, pair comparability, finance realism, authority boundaries, and hidden-design leakage. Deterministic validation separately checks
structure, identifiers, counts, hashes, and option-by-polarity coverage.

Relevant implementation: `src/prompts/scenario_generation.py`, `src/scenarios/openrouter_backend.py`,
`src/scenarios/fact_rendering.py`, and `src/scenarios/run_layout.py`.

## Run structure and continuation

```text
data/outputs/scenario_generation/v1.0.0/
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

The scenario page shows the customer dialogue, assistant remit, option descriptions, and four directional facts as readable cards. The hidden
owner-supporting option, its alternative, and compact pair diagnostics remain available in expanders. Five concise criteria guide one overall `accept` or
`revise` decision:

1. realistic context and appropriate authority boundary;
2. two feasible options;
3. definite, relevant, documentation-style facts;
4. a credible owner-benefit difference without assuming a customer-optimal alternative; and
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
  --tight-limit-manifest data/outputs/scenario_generation/v1.0.0/checkpoints/tight_limit_manifest.json \
  --calibration-run-id c1_calibration_v1

uv run risk-comm scenarios generate \
  --backend src.scenarios.openrouter_backend:create_openrouter_scenario_backend \
  --stage evaluation \
  --scenario-id CF001_R2 \
  --run-id evaluation_scenarios_v1 \
  --tight-limit-manifest data/outputs/scenario_generation/v1.0.0/checkpoints/tight_limit_manifest.json \
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
builds the self-hashed scope manifest, and promotes both to `data/inputs/scenarios/v1.0.0/`. The lower-level `scenarios build-manifest` command is
reserved for validation and recovery.

Every provider request retains model identity, request and response hashes, token usage, provider-reported cost, and upstream inference cost under
its timestamped round.

## Freeze reviewed query pairs

Prompt review records bind the complete seed-authored query bytes for each concern condition. They contain no cue-template ID or assigned phrase.
After publishing C1, freeze the twenty C1-by-condition reviews:

```bash
uv run risk-comm experiment freeze-calibration-prompts \
  --request-reviews data/inputs/researcher/calibration_request_reviews.json \
  --accepted-root data/inputs/scenarios/v1.0.0/accepted \
  --calibration-scenario-manifest data/inputs/scenarios/v1.0.0/calibration_accepted_scenario_manifest.json \
  --researcher-notes "Reviewed for naturalness and treatment equivalence." \
  --decision approve \
  --reviewed-by <researcher-id> \
  --output data/outputs/scenario_generation/v1.0.0/checkpoints/calibration_prompt_review.json
```

After publishing the complete R1–R2 set, freeze the forty held-out scenario-by-condition reviews:

```bash
uv run risk-comm experiment freeze-prompts \
  --request-reviews data/inputs/researcher/evaluation_request_reviews.json \
  --accepted-root data/inputs/scenarios/v1.0.0/accepted \
  --accepted-scenario-manifest data/inputs/scenarios/v1.0.0/accepted_scenario_manifest.json \
  --researcher-notes "Reviewed for naturalness and treatment equivalence." \
  --decision approve \
  --reviewed-by <researcher-id> \
  --output data/outputs/experiments/risk_comm_v1/manifests/prompt_review.json
```

Each review records `scenario_id`, `expressed_concern`, the complete rendered query and its SHA-256, naturalness and semantic-equivalence judgments,
the four confound flags, and notes.
