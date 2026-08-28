# Experiment Execution

All active experiment operations use `uv run risk-comm experiment ...`. The execution code is in `src/experiments/`, provider transport is in
`src/llm/openrouter.py`, and model declarations are in `src/settings/models.json`.

The retained experiment set is the one analysed in the dissertation:

| Artifact directory | Manuscript label | Responses |
|---|---|---:|
| `user_state_adaptation_v2` | Customer-state cues | 1,260 |
| `information_budget_v1` | Exact information budgets | 1,050 |
| `word_budget_external_validity_v1` | Natural word budgets | 630 |
| `single_fact_priority_v1` | Single priority | 210 |
| `ownership_role_control_v1` | Institutional affiliation | 462 |
| `option_first_v1` | Forced option choice | 210 |
| `commercial_interest_instruction_v1` | Commercial objective | 6,888 |
| **Total** | | **10,710** |

## 1. Build offline plans

```bash
uv run risk-comm experiment build-plan
```

The plans contain 1,260; 1,050; 630; 210; 462; 210; and 6,888 units, totalling 10,710. The 6,888-unit
`commercial_interest_instruction_v1` plan contains matched control and commercial-interest instructions across short neutral, anxious, and
frustrated queries, with a 160-word cap in every cell. It includes standard, single-fact, exact k={2,4}, and ownership-flip tasks. Each experiment
owns `config.json`, `run_plan.jsonl`, `results/`, `cache/`, `logs/`, `assets/`, and `checkpoints/` beneath
`data/outputs/experiments/<experiment-name>/`.

## 2. Approve and run operational preflight

Prepare a current-pricing estimate, then record explicit bounded approval for one compatibility call per evaluated model and scoring judge:

```bash
uv run risk-comm experiment approve-preflight \
  --estimated-max-cost 1.00 \
  --approved-max-cost 1.00 \
  --approved-by "RESEARCHER_ID" \
  --note "Eight bounded compatibility probes" \
  --output data/outputs/experiments/preflight_approval.json \
  --confirm-paid-preflight
```

Run the eight probes only after checking the amount and routes:

```bash
uv run risk-comm experiment preflight \
  --approval data/outputs/experiments/preflight_approval.json \
  --output data/outputs/experiments/preflight_results.jsonl
```

The command uses OpenRouter's default routing and each declared model-native control set. Routing requires the selected provider to support every sent
parameter. The preflight records the returned version, actual provider, provider request ID, gateway endpoint, and accepted controls. Unsupported
control sets fail preflight rather than being silently reduced.

## 3. Freeze the protocol

```bash
uv run risk-comm experiment freeze-protocol \
  --preflight-results data/outputs/experiments/preflight_results.jsonl
```

The frozen manifest binds the accepted-scenario and approved-query digest, seven evaluated models, scoring judge, returned versions, default-routing
policy, controls, and exact active counts. The command verifies both `manual_revisions/query_protocol_approval.json` and
`manual_revisions/prompt_protocol_approval.json` before freezing. Model-access groups are metadata for descriptive reporting, not ranking.

## 4. Estimate and approve evaluated execution

Create `model_costs.json` from current pricing, with one maximum USD amount per evaluated model. Then run:

```bash
uv run risk-comm experiment estimate-cost \
  --protocol-manifest data/outputs/experiments/final_protocol_manifest.json \
  --model-costs data/outputs/experiments/model_costs.json \
  --input-tokens INPUT_TOKEN_ESTIMATE \
  --output-token-ceiling OUTPUT_TOKEN_CEILING
```

After inspecting `data/outputs/experiments/cost_estimate.json`, create the exact-manifest approval:

```bash
uv run risk-comm experiment approve-execution \
  --protocol-manifest data/outputs/experiments/final_protocol_manifest.json \
  --cost-estimate data/outputs/experiments/cost_estimate.json \
  --approved-max-cost APPROVED_USD \
  --approved-by "RESEARCHER_ID" \
  --note "Approved final evaluated-model execution" \
  --output data/outputs/experiments/cost_approval.json \
  --confirm-paid-execution
```

No setup, planning, validation, test, schema, or asset command grants paid-call authority.

## 5. Execute immutable units

Materialise each experiment plan from accepted scenarios, controlled queries, the treatment cell, and the frozen provider metadata:

```bash
uv run risk-comm experiment build-bundles \
  --run-plan data/outputs/experiments/EXPERIMENT_NAME/run_plan.jsonl \
  --scenarios data/inputs/scenarios/v4.0.1/accepted_scenarios.jsonl \
  --protocol-manifest data/outputs/experiments/final_protocol_manifest.json \
  --output data/outputs/experiments/EXPERIMENT_NAME/execution_bundles.jsonl
```

Bundle construction fails if a scenario is not researcher accepted or if its scenario, query, model, or controls fall outside the frozen protocol.
The bounded unit entry point is:

```bash
uv run risk-comm experiment execute-unit \
  --bundle PATH_TO_EXECUTION_BUNDLE.json \
  --protocol-manifest data/outputs/experiments/final_protocol_manifest.json \
  --approval data/outputs/experiments/cost_approval.json \
  --estimated-cost UNIT_MAX_USD \
  --output PATH_TO_RUN_UNIT.json
```

Every task is single-turn. The first semantic provider answer is immutable. Malformed exact-budget JSON is recorded as non-adherence, not retried.
Only transport/provider failures with no semantic answer may be retried.
Every response records the actual routed provider, returned model version, native input/output token counts, and billed cost. Batch execution uses the
same immutable unit logic and writes resumable caches plus model-, experiment-, and protocol-level usage summaries:

```bash
uv run risk-comm experiment execute-batch \
  --bundles data/outputs/experiments/EXPERIMENT_NAME/execution_bundles.jsonl \
  --protocol-manifest data/outputs/experiments/final_protocol_manifest.json \
  --cost-estimate data/outputs/experiments/cost_estimate.json \
  --approval data/outputs/experiments/cost_approval.json
```

`commercial_interest_instruction_v1` is a core active experiment. Its 6,888 assignment IDs are deterministic functions of the scenario, model,
treatment cell, fact order, and active status. Re-running the same `execute-batch` command with the same frozen manifest and bundle file loads every
completed ID from `data/outputs/experiments/commercial_interest_instruction_v1/cache/` and calls the provider only for missing IDs. Each semantic
response is written to that cache immediately, so an interrupted run resumes from its last completed response. Do not re-freeze the manifest or
change treatment coordinates during a run; those changes intentionally require new bundles and approval. The approval ceiling is cumulative, so a
commercial-interest approval must cover already billed protocol cost plus the estimated ceiling for unfinished commercial-interest calls.
