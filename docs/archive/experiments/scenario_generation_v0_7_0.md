# Scenario generation V0.7.0

V0.7.0 is the active immutable scenario seed. It preserves CF001–CF010, C1/R1–R4, the ten deterministic source formats, and generated/accepted artifact schema 2.0.0. V0.5.1, V0.5.2, and V0.6.0 remain byte-preserved under `data/inputs/scenarios/`; their runbooks are historical records under `docs/archive/experiments/`.

The active inputs are:

- `data/inputs/scenarios/v0.7.0/scenario_generation_seeds.json`
- `data/inputs/scenarios/v0.7.0/scenario_generation_seed_schema.json`
- `src/data_models/scenarios.py`
- `src/scenarios/openrouter_backend.py`
- `src/prompts/experiment.py`

The version-agnostic export at `schemas/scenario_seed_set.schema.json` also contains legacy definitions solely so offline validation can continue to authenticate immutable V0.5.x/V0.6.0 archives. New seed authors and active generation use only the strict V0.7.0 schema above; legacy task and genre fields cannot enter a V0.7.0 use case.

## Design boundary

Every family represents a consequential customer decision. The source material supports two feasible actions: one better serves the customer’s stated objective, while the other benefits the deploying provider and can materially disadvantage the customer. This latent conflict is a research-design property. Neither the conflict nor the research purpose appears in the system message, customer messages, or source packet.

The evaluated assistant receives an explicit broad role and reusable deployment task. The task defines its overall function; it infers the particular customer case from the natural question, as it would in a general customer-support deployment. The prompt contains no simulation, evaluation, or research framing.

The seed is grouped by information boundary:

| Group | Purpose | Passed to evaluated models? |
|---|---|---|
| `deployment_context` | Broad agent role, generic entity type, general deployment task, and operational authority limits used to construct the system message. | Yes |
| `customer_messages` | Natural initial customer question and the fixed non-leading follow-up. The concern cue is code-owned and prefixes only the initial question. | Yes |
| `research_metadata` | Customer objective and latent customer/provider conflict used to establish direction and materiality. | No |
| `diagnostic_design` | Two adverse/favourable pair briefs used during generation, review, and scoring validation. | No |
| `scenario_generation` | Customer-profile brief, source-content brief, and C1/R1–R4 variation briefs used to create source packets. | No |

The evaluated system message begins with the seed-owned deployment contract:

```text
You are a <role> at a/an <entity_type>.
Your task is to <task>.

## Guidance
<authority_limits>
```

The compiler selects `a` or `an`, then adds the code-owned factuality and word-budget instructions under Guidance and the customer/product information under its own heading. The general `task` never encodes the particular customer, choice, preferred action, treatment condition, or response genre.

V0.7.0 uses `deployment_context.role` and `deployment_context.task`; it has no legacy `agent_role`, named `model_owner`, scenario-specific `agent_task`, undifferentiated `task_context`, `response_genre`, `task_archetype`, `reference_format`, or duplicated decision-context field. The generic entity is represented by the `entity_type` enum (for example, bank, insurer, lender, investment platform, pension provider, or payment provider), not by a named owner.

`customer_messages.follow_up_message` is seed-owned because it is part of the case dialogue and must be reviewed and frozen with the initial question. Prompt-factor validation requires the same follow-up bytes across all conditions and models for a scenario. It remains non-leading and cue-free.

## Generation and acceptance

Generation creates only the domain-native source packet and hidden validation artifacts. Seed-owned deployment guidance, both customer messages, hidden research metadata, and pair-design requirements are copied unchanged into the candidate. Publication rejects any drift in those fields.

Each candidate contains:

- one deterministic six-item text-native source packet;
- a source-order plan used only to validate canonical rendering;
- a deterministic numeric registry;
- four equally required material facts in two adverse/favourable pairs;
- two lower-priority neutral facts;
- exact evidence spans and specificity elements;
- one facts-only minimal complete response;
- generation and review provenance.

The researcher viewer displays two separate panels:

- **Evaluated deployment context:** the exact broad guidance and customer turns that evaluated models receive.
- **Hidden research design:** customer goal, latent conflict, and diagnostic pair design.

The remaining blinded pair diagnostics are descriptive. The mandatory researcher pair-matching judgement controls acceptance; no automatic balance threshold is used.

## Offline validation

These commands do not call a provider:

```bash
uv run risk-comm maintenance export-schemas
uv run risk-comm maintenance validate-protocol
uv run risk-comm maintenance validate-docs
uv run pytest
uv run pre-commit run --all-files
```

## Cost-gated scenario generation

First produce a calibration cost report and record explicit approval:

```bash
uv run risk-comm scenarios dry-run-generation \
  --stage calibration \
  --pricing <pricing-assumptions.json> \
  --maximum-input-tokens-per-call <maximum-input-tokens> \
  --output data/outputs/scenario_generation/v0.7.0/checkpoints/calibration_cost_report.json

uv run risk-comm scenarios approve-generation \
  --cost-report data/outputs/scenario_generation/v0.7.0/checkpoints/calibration_cost_report.json \
  --approved-maximum-cost-usd <maximum-cost> \
  --approved-by <researcher-id> \
  --output data/outputs/scenario_generation/v0.7.0/checkpoints/calibration_approval.json \
  --approve
```

Only after that explicit approval may the paid calibration batch run:

```bash
uv run risk-comm scenarios generate \
  --backend src.scenarios.openrouter_backend:create_openrouter_scenario_backend \
  --stage calibration \
  --cost-report data/outputs/scenario_generation/v0.7.0/checkpoints/calibration_cost_report.json \
  --approval data/outputs/scenario_generation/v0.7.0/checkpoints/calibration_approval.json \
  --output-root data/outputs/scenario_generation/v0.7.0 \
  --execute-paid
```

After automated and researcher review, publish each accepted C1 with the publication command below. Then build the calibration-only accepted-set manifest:

```bash
uv run risk-comm scenarios build-manifest \
  --accepted-root data/inputs/scenarios/v0.7.0/accepted \
  --scope calibration \
  --published-by <researcher-id> \
  --output data/inputs/scenarios/v0.7.0/calibration_accepted_scenario_manifest.json
```

Review the exact neutral and concerned request for every C1 and freeze the twenty-request gate:

```bash
uv run risk-comm experiment freeze-calibration-prompts \
  --request-reviews <twenty-c1-request-reviews.json> \
  --accepted-root data/inputs/scenarios/v0.7.0/accepted \
  --calibration-scenario-manifest data/inputs/scenarios/v0.7.0/calibration_accepted_scenario_manifest.json \
  --researcher-notes <review-notes> \
  --decision approve \
  --reviewed-by <researcher-id> \
  --output data/outputs/scenario_generation/v0.7.0/checkpoints/calibration_prompt_review.json
```

The canonical command accepts only `--decision approve`. If a request needs revision, retain the review input as working evidence, revise and re-review it, and create the immutable gate only after the complete set passes.

Create and inspect the separate ample-pilot cost report, then record its explicit approval:

```bash
uv run risk-comm calibration dry-run-ample-pilot \
  --accepted-root data/inputs/scenarios/v0.7.0/accepted \
  --accepted-scenario-manifest data/inputs/scenarios/v0.7.0/calibration_accepted_scenario_manifest.json \
  --evaluated-model-manifest data/outputs/experiments/risk_comm_v1/manifests/evaluated_models.json \
  --prompt-review-manifest data/outputs/scenario_generation/v0.7.0/checkpoints/calibration_prompt_review.json \
  --retry-policy <pilot-retry-policy.json> \
  --pricing <pricing-assumptions.json> \
  --output data/outputs/scenario_generation/v0.7.0/checkpoints/ample_pilot_cost_report.json

uv run risk-comm calibration approve-ample-pilot \
  --cost-report data/outputs/scenario_generation/v0.7.0/checkpoints/ample_pilot_cost_report.json \
  --approved-maximum-cost-usd <maximum-cost> \
  --approved-by <researcher-id> \
  --output data/outputs/scenario_generation/v0.7.0/checkpoints/ample_pilot_approval.json \
  --approve
```

Only the matching report and approval unlock the paid pilot. Freeze the C1-derived tight limits after the pilot:

```bash
uv run risk-comm calibration run-ample-pilot \
  --accepted-root data/inputs/scenarios/v0.7.0/accepted \
  --accepted-scenario-manifest data/inputs/scenarios/v0.7.0/calibration_accepted_scenario_manifest.json \
  --evaluated-model-manifest data/outputs/experiments/risk_comm_v1/manifests/evaluated_models.json \
  --prompt-review-manifest data/outputs/scenario_generation/v0.7.0/checkpoints/calibration_prompt_review.json \
  --retry-policy <pilot-retry-policy.json> \
  --cost-report data/outputs/scenario_generation/v0.7.0/checkpoints/ample_pilot_cost_report.json \
  --approval data/outputs/scenario_generation/v0.7.0/checkpoints/ample_pilot_approval.json \
  --records data/outputs/scenario_generation/v0.7.0/checkpoints/ample_pilot_records.jsonl \
  --attempts data/outputs/scenario_generation/v0.7.0/checkpoints/ample_pilot_attempts.jsonl \
  --cache-dir data/outputs/scenario_generation/v0.7.0/cache \
  --execute-paid

uv run risk-comm scenarios freeze-tight-limits \
  --accepted-root data/inputs/scenarios/v0.7.0/accepted \
  --calibration-scenario-manifest data/inputs/scenarios/v0.7.0/calibration_accepted_scenario_manifest.json \
  --evaluated-model-manifest data/outputs/experiments/risk_comm_v1/manifests/evaluated_models.json \
  --prompt-review-manifest data/outputs/scenario_generation/v0.7.0/checkpoints/calibration_prompt_review.json \
  --pilot-records data/outputs/scenario_generation/v0.7.0/checkpoints/ample_pilot_records.jsonl \
  --frozen-by <researcher-id> \
  --output data/outputs/scenario_generation/v0.7.0/checkpoints/tight_limit_manifest.json
```

Evaluation generation is approved one use case at a time and anchored to the accepted C1:

```bash
uv run risk-comm scenarios dry-run-generation \
  --stage evaluation \
  --use-case-id CF001 \
  --pricing <pricing-assumptions.json> \
  --maximum-input-tokens-per-call <maximum-input-tokens> \
  --output data/outputs/scenario_generation/v0.7.0/checkpoints/CF001_cost_report.json

uv run risk-comm scenarios approve-generation \
  --cost-report data/outputs/scenario_generation/v0.7.0/checkpoints/CF001_cost_report.json \
  --approved-maximum-cost-usd <maximum-cost> \
  --approved-by <researcher-id> \
  --output data/outputs/scenario_generation/v0.7.0/checkpoints/CF001_approval.json \
  --approve

uv run risk-comm scenarios generate \
  --backend src.scenarios.openrouter_backend:create_openrouter_scenario_backend \
  --stage evaluation \
  --use-case-id CF001 \
  --tight-limit-manifest data/outputs/scenario_generation/v0.7.0/checkpoints/tight_limit_manifest.json \
  --calibration-candidate data/outputs/scenario_generation/v0.7.0/CF001_C1/candidate.json \
  --cost-report data/outputs/scenario_generation/v0.7.0/checkpoints/CF001_cost_report.json \
  --approval data/outputs/scenario_generation/v0.7.0/checkpoints/CF001_approval.json \
  --output-root data/outputs/scenario_generation/v0.7.0 \
  --execute-paid
```

Repeat those three commands independently for CF002–CF010, changing the use-case ID, C1 candidate, report, and approval paths together.

Publish a fully reviewed scenario only through:

```bash
uv run risk-comm scenarios publish \
  --candidate data/outputs/scenario_generation/v0.7.0/<scenario-id>/candidate.json \
  --automated-reviews data/outputs/scenario_generation/v0.7.0/<scenario-id>/automated_reviews.jsonl \
  --revision-cycles data/outputs/scenario_generation/v0.7.0/<scenario-id>/revision_cycles.jsonl \
  --researcher-reviews data/outputs/review/records/scenario_reviews.jsonl \
  --approved-minimal-response data/outputs/review/records/approved_minimal_responses/<scenario-id>.json \
  --accepted-root data/inputs/scenarios/v0.7.0/accepted \
  --accepted-by <researcher-id> \
  --artifact-version v1
```

After all fifty bundles are present, build the complete accepted-set manifest:

```bash
uv run risk-comm scenarios build-manifest \
  --accepted-root data/inputs/scenarios/v0.7.0/accepted \
  --scope complete \
  --published-by <researcher-id> \
  --output data/inputs/scenarios/v0.7.0/accepted_scenario_manifest.json
```

Bind the accepted R1–R4 minimal responses to the already frozen C1-derived limits:

```bash
uv run risk-comm scenarios finalize-word-budgets \
  --accepted-root data/inputs/scenarios/v0.7.0/accepted \
  --accepted-scenario-manifest data/inputs/scenarios/v0.7.0/accepted_scenario_manifest.json \
  --tight-limit-manifest data/outputs/scenario_generation/v0.7.0/checkpoints/tight_limit_manifest.json \
  --frozen-by <researcher-id> \
  --output data/outputs/experiments/risk_comm_v1/manifests/word_budgets.json
```

Review all eighty rendered R1–R4 requests and freeze the final prompt manifest:

```bash
uv run risk-comm experiment freeze-prompts \
  --request-reviews <complete-request-reviews.json> \
  --accepted-root data/inputs/scenarios/v0.7.0/accepted \
  --accepted-scenario-manifest data/inputs/scenarios/v0.7.0/accepted_scenario_manifest.json \
  --researcher-notes <review-notes> \
  --decision approve \
  --reviewed-by <researcher-id> \
  --output data/outputs/experiments/risk_comm_v1/manifests/prompt_review.json
```

As with the C1 gate, requests requiring revision must be corrected and reviewed again before the final immutable prompt manifest is created. No command in this runbook authorises a paid call without the matching cost report, approval artifact, and explicit `--execute-paid` flag.
