# UCL MSc Research: Selective Financial-Risk Communication

This repository contains the dissertation and reproducible implementation for a controlled study of how financial-assistant models select,
realise, and present matched facts under user-state, information-budget, word-budget, ownership-role, option-priority, and commercial-interest
instruction treatments.

The active study is implemented independently in `srcv2/` and run with `uv run risk-comm-v2 ...`. Its tests live in `tests_v2/`, public schemas in
`schemas_v2/`, and scenario inputs in `data/inputs/scenarios/v4.0.1/`. The `srcv2` package does not import the historical `src` package. The existing
`uv run risk-comm ...` command remains available for reproducibility but is not used to operate the active study.
Scenario-generation provenance is stored separately from evaluated experiments under
`data/outputs/scenario_generation/v4.0.1/scenario_fact_generation_v1/`.

The canonical design is [RESEARCH_PLAN.md](docs/research-plan/RESEARCH_PLAN.md). Durable inclusion, modification, rejection, and deferral reasons are
recorded separately in [V4_REDESIGN_DECISIONS.md](docs/research-plan/V4_REDESIGN_DECISIONS.md).

## Study at a glance

The corpus contains 30 fictional financial scenarios across mortgages, credit and repayment, savings, investment platforms, insurance settlements,
and international payments. Each scenario contains three same-valence matched pairs: six facts in total, three facts per option, three
owner-supporting facts, three countervailing facts, and one atomic specificity anchor per fact. Customer valence is balanced 90/90 across the
180-fact corpus.

| Artifact directory | Manuscript label | Design | Responses |
|---|---|---|---:|
| `user_state_adaptation_v2` | Customer-state cues | 30 scenarios × 3 affects × 2 lengths × 7 models | 1,260 |
| `information_budget_v1` | Exact information budget | Neutral k={2,4,6}; anxious k={2,4}; fact IDs selected before prose | 1,050 |
| `word_budget_external_validity_v1` | Natural word budget | Neutral 40/80/160-word instructions | 630 |
| `single_fact_priority_v1` | Single-priority fact | One naturally expressed most-important fact | 210 |
| `ownership_role_control_v1` | Institutional affiliation | 11 scenarios × 3 roles × 2 jointly counterbalanced renderings × 7 models | 462 |
| `option_first_v1` | Forced option choice | One response choosing and explaining one option | 210 |
| `commercial_interest_instruction_v1` | Commercial objective | Control/protect instruction × 3 affects × standard, single-fact, k={2,4}, and ownership tasks | 6,888 |
| **Total** | | | **10,710** |

`balanced_prominence_mitigation_v1` is implemented as a deferred 210-response matrix and is excluded from the active total.
Every commercial-interest cell uses the scenario's short query and a 160-word response cap. The ownership subset uses the 11 eligible scenarios,
two employer coordinates, and two jointly counterbalanced renderings.

The principal direction-sensitive outcome is the signed directional gap (D). Pairwise imbalance (A), total material coverage (T), pair states,
specificity, presentation, factual error, empathy/referral, density, and length are reported separately. The primary analysis contains five RQ1
commercial-objective directional tests adjusted together with Holm's procedure: standard, single-priority, exact k=4, exact k=2, and ownership flip.
The anxious-versus-neutral RQ2 test and exact-budget k=2-versus-k=6 RQ3 test are singleton families and retain their raw p-values.
The forced-option experiment additionally retains a three-way owner-relative choice label derived from explicit recommendation or, when absent,
directional framing; balanced or unassessable responses remain no discernible choice.

## Current execution boundary

Offline protocol construction is implemented. The supplied source archive is preserved at `data/inputs/scenarios/v4.0.0.zip` with SHA-256
`b9fb39abb4be8cdda91de2f3d9817cb2febda0437fc2cb47abbf75b6e8add790`; its audited seed corpus is under
`data/inputs/scenarios/v4.0.1/`. GPT-5.4 generated one semantic response for each scenario through the pinned OpenAI endpoint, and the complete
180-fact corpus received manual financial, arithmetic, completeness, and language review. Researcher-approved corrections are stored as a separate
hash-bound curation layer; the source requests, responses, and provider caches remain unchanged. All scenarios are accepted and republished with six
researcher-approved natural queries: neutral, anxious, and frustrated wording in short and long forms. The 3,822 responses from the first six
experiments are complete with per-response provider, token, and billed-cost records, and their 30,576 GPT-5.4 Mini judge calls have been adjudicated.
The 6,888-response commercial-interest experiment and its 55,104 Gemini 3.1 Flash Lite judge calls are also complete. The three judge contracts and
their shared 191-response development workflow were frozen before application to that experiment. The content contract separates underlying proposition
presence from specificity-anchor retention. Exact-budget
selection scoring retains strict format adherence separately while recovering otherwise valid exact-k JSON from one complete Markdown fence; its
prose field is judged without the JSON wrapper. Across all 3,570 exact-budget responses, 3,569 selections are usable and one wrong-k response remains
unusable. Accuracy judging
uses the visible assistant context, customer query, option names, and six facts, while hidden research metadata remains excluded. Raw judge outputs
remain immutable; confirmed corrections are stored in separate override ledgers. Final adjudicated labels have been joined into one response-score
record for each of the 10,710 evaluated responses. Each experiment now owns its judge-development artifacts, raw judge calls, correction ledger,
final judgments, and calculated scores under `scoring/`. A complete copy of the pre-restructure experiment tree is preserved under
`data/outputs/archive/experiments/`.

Evaluated prompts take their natural domain role, fictional employer, task, and single authority limit from the final seed. They expose named
options, six product-information statements, and the customer message while keeping decision context and analytical coordinates hidden.

## Offline setup and validation

```bash
uv run risk-comm-v2 scenarios import-package
uv run risk-comm-v2 scenarios validate
uv run risk-comm-v2 scenarios build-generation-requests
uv run risk-comm-v2 scenarios build-queries
uv run risk-comm-v2 experiment build-plan --include-deferred
uv run risk-comm-v2 maintenance export-schemas
uv run risk-comm-v2 experiment generate-assets
uv run risk-comm-v2 scoring show-prompts --experiment commercial_interest_instruction_v1
uv run risk-comm-v2 scoring calculate-outcomes --experiment commercial_interest_instruction_v1
uv run risk-comm-v2 analysis option-first-choices
uv run risk-comm-v2 maintenance validate-isolation
uv run pytest
uv run pre-commit run --all-files
```

These commands do not authorise paid calls. Paid preflight and execution require cost estimates plus explicit, hash-bound approval artifacts; see
[experiment_execution.md](docs/experiments/experiment_execution.md).

## Workflow guides

- [Scenario workflow](docs/experiments/scenario_workflow.md)
- [Experiment execution](docs/experiments/experiment_execution.md)
- [Scoring and validation](docs/experiments/scoring_and_validation.md)
- [Analysis](docs/experiments/analysis.md)
- [Scenario-family research](docs/experiments/scenario_research.md)

Experiment artifacts are written beneath `data/outputs/experiments/<experiment-name>/`. Evaluated-model outputs remain in `results/`; every scoring
artifact, from raw judge calls through manual corrections and final response scores, is kept in that experiment's `scoring/` directory. The experiment
also owns `config.json`, `cache/`, `logs/`, `assets/`, and `checkpoints/`.

## Protected launcher compatibility

The unchanged `risk-comm` regression fixture continues to recognise its packaged `V3.0.0` seed, schema `9.0.0`, and fixture counts `240`, `120`,
and `60`. These identifiers exist only to verify that the protected launcher remains operational; they are not inputs to the active study.
