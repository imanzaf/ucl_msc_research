# Experiment Execution

All active experiment operations use `uv run risk-comm-v2 experiment ...`. The execution code is in `srcv2/experiments/`, provider transport is in
`srcv2/llm/openrouter.py`, and model declarations are in `srcv2/settings/models.json`.

## 1. Build offline plans

```bash
uv run risk-comm-v2 experiment build-plan --include-deferred
```

The active plans must contain 1,260; 1,050; 630; 210; 462; and 210 units, totalling 3,822. The optional flag also writes 210 units for
`balanced_prominence_mitigation_v1` with `execution_status=deferred`. Each experiment owns `config.json`, `run_plan.jsonl`, `results/`, `cache/`,
`logs/`, `assets/`, and `checkpoints/` beneath `data/outputs/experiments/<experiment-name>/`.

## 2. Approve and run operational preflight

Prepare a current-pricing estimate, then record explicit bounded approval for one compatibility call per evaluated model and scoring judge:

```bash
uv run risk-comm-v2 experiment approve-preflight \
  --estimated-max-cost 1.00 \
  --approved-max-cost 1.00 \
  --approved-by "RESEARCHER_ID" \
  --note "Eight bounded compatibility probes" \
  --output data/outputs/experiments/preflight_approval.json \
  --confirm-paid-preflight
```

Run the eight probes only after checking the amount and routes:

```bash
uv run risk-comm-v2 experiment preflight \
  --approval data/outputs/experiments/preflight_approval.json \
  --output data/outputs/experiments/preflight_results.jsonl
```

The command uses OpenRouter's default routing and each declared model-native control set. Routing requires the selected provider to support every sent
parameter. The preflight records the returned version, actual provider, provider request ID, gateway endpoint, and accepted controls. Unsupported
control sets fail preflight rather than being silently reduced.

## 3. Freeze the protocol

```bash
uv run risk-comm-v2 experiment freeze-protocol \
  --preflight-results data/outputs/experiments/preflight_results.jsonl
```

The frozen manifest binds the accepted-scenario and approved-query digest, seven evaluated models, scoring judge, returned versions, default-routing
policy, controls, and exact active counts. The command verifies both `manual_revisions/query_protocol_approval.json` and
`manual_revisions/prompt_protocol_approval.json` before freezing. Model-access groups are metadata for descriptive reporting, not ranking.

## 4. Estimate and approve evaluated execution

Create `model_costs.json` from current pricing, with one maximum USD amount per evaluated model. Then run:

```bash
uv run risk-comm-v2 experiment estimate-cost \
  --protocol-manifest data/outputs/experiments/final_protocol_manifest.json \
  --model-costs data/outputs/experiments/model_costs.json \
  --input-tokens INPUT_TOKEN_ESTIMATE \
  --output-token-ceiling OUTPUT_TOKEN_CEILING
```

After inspecting `data/outputs/experiments/cost_estimate.json`, create the exact-manifest approval:

```bash
uv run risk-comm-v2 experiment approve-execution \
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
uv run risk-comm-v2 experiment build-bundles \
  --run-plan data/outputs/experiments/EXPERIMENT_NAME/run_plan.jsonl \
  --scenarios data/inputs/scenarios/v4.0.1/accepted_scenarios.jsonl \
  --protocol-manifest data/outputs/experiments/final_protocol_manifest.json \
  --output data/outputs/experiments/EXPERIMENT_NAME/execution_bundles.jsonl
```

Bundle construction fails if a scenario is not researcher accepted or if its scenario, query, model, or controls fall outside the frozen protocol.
The bounded unit entry point is:

```bash
uv run risk-comm-v2 experiment execute-unit \
  --bundle PATH_TO_EXECUTION_BUNDLE.json \
  --protocol-manifest data/outputs/experiments/final_protocol_manifest.json \
  --approval data/outputs/experiments/cost_approval.json \
  --estimated-cost UNIT_MAX_USD \
  --output PATH_TO_RUN_UNIT.json
```

Every task is single-turn. The first semantic provider answer is immutable. Malformed exact-budget JSON is recorded as non-adherence, not retried.
Only transport/provider failures with no semantic answer may be retried. Deferred assignments fail closed.
Every response records the actual routed provider, returned model version, native input/output token counts, and billed cost. Batch execution uses the
same immutable unit logic and writes resumable caches plus model-, experiment-, and protocol-level usage summaries:

```bash
uv run risk-comm-v2 experiment execute-batch \
  --bundles data/outputs/experiments/EXPERIMENT_NAME/execution_bundles.jsonl \
  --protocol-manifest data/outputs/experiments/final_protocol_manifest.json \
  --cost-estimate data/outputs/experiments/cost_estimate.json \
  --approval data/outputs/experiments/cost_approval.json
```

## 6. Generate stable assets

```bash
uv run risk-comm-v2 experiment generate-assets
```

Before results exist, stable tables state that results are unavailable. Once result rows exist, the same filenames are regenerated by
`srcv2/experiments/assets.py`; no timestamps appear in paper asset names.
