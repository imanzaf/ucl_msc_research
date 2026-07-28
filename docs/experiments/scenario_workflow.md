# Scenario workflow

This workflow covers V2.0.0 scenario generation, run-ID continuation, researcher review, revision, and publication. The active generation protocol
is V1.0.5; the active scenario inputs are:

- scenario definitions: `data/inputs/scenarios/v2.0.0/scenario_generation_seeds.json`
- definition schema: `data/inputs/scenarios/v2.0.0/scenario_generation_seed_schema.json`
- customer queries: `data/inputs/scenarios/v2.0.0/scenario_customer_queries.json`
- query schema: `data/inputs/scenarios/v2.0.0/scenario_customer_queries_schema.json`

The four SHA-256 digests are:

- definitions: `f56c20b4baf673f1ddcac5cd2af79086a1c6ff31b25471fab9c360ae96e0b9fb`
- definition schema: `8a8e04ff76b44d410c1278a183cd4e179f4b01e151490131f52fcc8bc119af0f`
- customer queries: `2d5271a115a5a1edc10cd11f49c111d1b7d977e8f807d2405b847b301072f1e8`
- query schema: `a8707b1a2388f9149b80b34870cdd2b98424025d4a45c6173b702248f5249133`

Candidate and accepted artifacts use schema `6.0.0`.

## Generation contract

One structured model call receives the broad deployment task and one seed-owned decision: the decision type, two named options, the
owner-supporting option, and the owner-benefit mechanism. It returns a neutral operating description plus one favourable and one adverse fact for
each option. Every fact also returns zero to three exact quantitative specificity markers, limited to phrases such as currency amounts,
percentages, rates, limits, counts, and durations. No customer query is sent to the initial or revision generator. Revision calls receive only the
frozen decision input, prior generated option descriptions, facts, specificity markers, fact-pair structure, and review findings; a runtime guard
rejects any generation payload containing an exact seed-authored query.

Every automated or researcher-directed revision finding contains exactly `severity`, `fact_text`, and `suggested_action`. Automated review copies
the problematic option description or material fact into `fact_text`. The researcher form saves one editable record per fact containing the fact
text, marker list, and optional notes. For researcher-directed regeneration, deterministic code links each noted or edited record to the exact
parent fact and includes the saved text or marker correction in `suggested_action`. A revise decision requires at least one fact note. Code derives
audit references from complete finding hashes after the provider boundary.

The separate query document groups records first by `use_case_id` and then by `scenario_id`. Each scenario owns a natural `neutral_user_query`, a
semantically equivalent `concerned_user_query`, and one generic `follow_up_query`. Loading requires an exact one-to-one match between the 30
definition IDs and 30 query IDs. Deterministic code joins the records after validation, copies the queries into the candidate after generation,
and uses them directly in evaluated prompts; there is no reusable cue-prefix or cue-template layer. The complete candidate, including its queries,
remains visible to the independent semantic reviewer and the separate researcher prompt-review gates.

Only the four directional facts form the material-fact scoring denominator. Descriptions are unscored option context. Generated specificity
markers are editable during researcher review, and accepted publication uses the researcher-saved fact text and marker lists.

The independent semantic reviewer checks option feasibility, operating-description neutrality, fact definiteness and materiality, internal
consistency, pair comparability, finance realism, authority boundaries, and hidden-design leakage. Deterministic validation separately checks
structure, identifiers, counts, hashes, and option-by-polarity coverage.

Relevant implementation: `src/prompts/scenario_generation.py`, `src/scenarios/openrouter_backend.py`, `src/review_app.py`,
`src/scenarios/researcher_edits.py`, and `src/scenarios/acceptance.py`.

## Run structure and continuation

```text
data/outputs/scenario_generation/v2.0.0/
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

Run authentication binds the generation-protocol version and all four scenario-input hashes. Earlier histories remain preserved on disk but are
not accepted by the active V2.0.0 input and V1.0.5 generation contracts; a new run ID is required.

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
4. a credible owner-benefit difference; and
5. sufficiently comparable fact pairs.

The criteria are guidance, not separately persisted checkboxes or automatic thresholds. Each fact card contains editable fact text, an editable
one-marker-per-line list, and an optional notes field. A revise decision requires at least one nonblank fact note. The saved researcher review uses
schema `3.3.0`; accepted publication applies its edited fact text and marker lists, while revision turns its notes and edits into parent-linked
findings. The app has no provider client and cannot generate, score, or run experiments. Progress is written immediately to
`<run-id>/researcher_review/scenario_reviews.jsonl` and remains resumable if the browser closes.

## Regenerate revised scenarios

After review, repeat the generation command:

```bash
uv run risk-comm scenarios generate \
  --backend src.scenarios.openrouter_backend:create_openrouter_scenario_backend \
  --stage calibration \
  --run-id c1_calibration_v1
```

Only current `revise` cases are regenerated. Every noted or edited fact becomes a finding whose `fact_text` is the exact parent fact and whose
`suggested_action` contains the saved note plus any researcher-edited fact text or marker list. Each replacement records its parent candidate and
review hashes. The reviewer subsequently shows only regenerated candidate hashes without a current decision.

## Generate R1 and R2 separately

Evaluation replications can be generated in separate commands under one logical run:

```bash
uv run risk-comm scenarios generate \
  --backend src.scenarios.openrouter_backend:create_openrouter_scenario_backend \
  --stage evaluation \
  --scenario-id CF001_R1 \
  --run-id evaluation_scenarios_v1 \
  --tight-limit-manifest data/outputs/scenario_generation/v2.0.0/checkpoints/tight_limit_manifest.json \
  --calibration-run-id c1_calibration_v1

uv run risk-comm scenarios generate \
  --backend src.scenarios.openrouter_backend:create_openrouter_scenario_backend \
  --stage evaluation \
  --scenario-id CF001_R2 \
  --run-id evaluation_scenarios_v1 \
  --tight-limit-manifest data/outputs/scenario_generation/v2.0.0/checkpoints/tight_limit_manifest.json \
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
builds the self-hashed scope manifest, and promotes both to `data/inputs/scenarios/v2.0.0/`. The lower-level `scenarios build-manifest` command is
reserved for validation and recovery.

Every provider request retains model identity, request and response hashes, token usage, provider-reported cost, and upstream inference cost under
its timestamped round.

## Freeze reviewed query pairs

Prompt review records bind the complete seed-authored query bytes for each concern condition. They contain no cue-template ID or assigned phrase.
After publishing C1, freeze the twenty C1-by-condition reviews:

```bash
uv run risk-comm experiment freeze-calibration-prompts \
  --request-reviews data/inputs/researcher/calibration_request_reviews.json \
  --accepted-root data/inputs/scenarios/v2.0.0/accepted \
  --calibration-scenario-manifest data/inputs/scenarios/v2.0.0/calibration_accepted_scenario_manifest.json \
  --researcher-notes "Reviewed for naturalness and treatment equivalence." \
  --decision approve \
  --reviewed-by <researcher-id> \
  --output data/outputs/scenario_generation/v2.0.0/checkpoints/calibration_prompt_review.json
```

After publishing the complete R1–R2 set, freeze the forty held-out scenario-by-condition reviews:

```bash
uv run risk-comm experiment freeze-prompts \
  --request-reviews data/inputs/researcher/evaluation_request_reviews.json \
  --accepted-root data/inputs/scenarios/v2.0.0/accepted \
  --accepted-scenario-manifest data/inputs/scenarios/v2.0.0/accepted_scenario_manifest.json \
  --researcher-notes "Reviewed for naturalness and treatment equivalence." \
  --decision approve \
  --reviewed-by <researcher-id> \
  --output data/outputs/experiments/risk_comm_v1/manifests/prompt_review.json
```

Each review records `scenario_id`, `expressed_concern`, the complete rendered query and its SHA-256, naturalness and semantic-equivalence judgments,
the four confound flags, and notes.
