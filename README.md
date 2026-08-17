# UCL MSc Research: Selective Financial-Risk Communication

This repository contains the dissertation and reproducible implementation for a controlled study of how financial-assistant models select,
realise, and present matched facts under user-state, information-budget, word-budget, ownership-role, and option-priority treatments.

The active study is implemented independently in `srcv2/` and run with `uv run risk-comm-v2 ...`. Its tests live in `tests_v2/`, public schemas in
`schemas_v2/`, and scenario inputs in `data/inputs/scenarios/v4.0.1/`. The `srcv2` package does not import the historical `src` package. The existing
`uv run risk-comm ...` command remains available for reproducibility but is not used to operate the active study.

The canonical design is [RESEARCH_PLAN.md](docs/research-plan/RESEARCH_PLAN.md). Durable inclusion, modification, rejection, and deferral reasons are
recorded separately in [V4_REDESIGN_DECISIONS.md](docs/research-plan/V4_REDESIGN_DECISIONS.md).

## Study at a glance

The corpus contains 30 fictional financial scenarios across mortgages, credit and repayment, savings, investment platforms, insurance settlements,
and international payments. Each scenario contains three same-valence matched pairs: six facts in total, three facts per option, three
owner-supporting facts, three countervailing facts, and one atomic specificity anchor per fact. Customer valence is balanced 90/90 across the
180-fact corpus.

| Experiment | Design | Responses |
|---|---|---:|
| `user_state_adaptation_v2` | 30 scenarios × 3 affects × 2 lengths × 7 models | 1,260 |
| `information_budget_v1` | Neutral k={2,4,6}; anxious k={2,4}; fact IDs selected before prose | 1,050 |
| `word_budget_external_validity_v1` | Neutral 40/80/160-word instructions | 630 |
| `single_fact_priority_v1` | One naturally expressed most-important fact | 210 |
| `ownership_role_control_v1` | 11 scenarios × 3 roles × 2 jointly counterbalanced renderings × 7 models | 462 |
| `option_first_v1` | One response choosing and explaining one option | 210 |
| **Total** | | **3,822** |

`balanced_prominence_mitigation_v1` is implemented as a deferred 210-response matrix and is excluded from the active total.

The principal direction-sensitive outcome is the signed directional gap (D). Pairwise imbalance (A), total material coverage (T), pair states,
specificity, presentation, factual error, empathy/referral, density, and length are reported separately. The confirmatory family contains only two
Holm-corrected tests: anxious versus neutral (D), and the ordered k=6→4→2 change in selection-ID (D).

## Current execution boundary

Offline protocol construction is implemented. The supplied source archive is preserved at `data/inputs/scenarios/v4.0.0.zip` with SHA-256
`b9fb39abb4be8cdda91de2f3d9817cb2febda0437fc2cb47abbf75b6e8add790`; its audited seed corpus is under
`data/inputs/scenarios/v4.0.1/`. GPT-5.4 generated one semantic response for each scenario through the pinned OpenAI endpoint, and the complete
180-fact corpus received manual financial, arithmetic, completeness, and language review. Researcher-approved corrections are stored as a separate
hash-bound curation layer; the source requests, responses, and provider caches remain unchanged. All scenarios are accepted and republished with six
researcher-approved natural queries: neutral, anxious, and frustrated wording in short and long forms. All 3,822 evaluated-model responses are
complete with per-response provider, token, and billed-cost records. The three GPT-5.4 Mini judge contracts and their 191-response development
workflow are implemented. The active content contract separates underlying proposition presence from specificity-anchor retention. Exact-budget
selection scoring retains strict format adherence separately while recovering otherwise valid exact-k JSON from one complete Markdown fence; its
prose field is judged without the JSON wrapper. Of 1,050 selections, 954 are usable and 96 prose or invalid outputs remain unusable. Accuracy judging
uses the visible assistant context, customer query, option names, and six facts, while hidden research metadata remains excluded. The content and
presentation calls were retained unchanged while all 191 accuracy calls were rerun with the visible option names. The complete pilot has been
reviewed, corrected through the immutable override ledger, and frozen. Statistical results remain pending the cost-approved full scoring run.

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
uv run risk-comm-v2 scoring show-prompts
uv run risk-comm-v2 scoring sample-pilot
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

Experiment artifacts are written beneath `data/outputs/experiments/<experiment-name>/`, with `config.json`, `results/`, `cache/`, `logs/`, `assets/`,
and `checkpoints/` owned by each experiment.

## Protected launcher compatibility

The unchanged `risk-comm` regression fixture continues to recognise its packaged `V3.0.0` seed, schema `9.0.0`, and fixture counts `240`, `120`,
and `60`. These identifiers exist only to verify that the protected launcher remains operational; they are not inputs to the active study.
