# Scenario generation V0.5.2

> Historical protocol only. V0.5.2 is preserved unchanged; the active implementation uses V0.6.0.

V0.5.2 is a corrected immutable derivative of V0.5.1. It preserves ten use cases and C1/R1–R4 identifiers. The V0.5.1 files remain unchanged and are independently hash-validatable.

Offline validation:

```bash
uv run risk-comm maintenance validate-protocol
```

Before any provider call, create and inspect a conservative batch-specific cost report, then record an explicit approval. For the ten C1 calibration scenarios:

```bash
uv run risk-comm scenarios dry-run-generation \
  --stage calibration \
  --pricing <pricing-assumptions.json> \
  --maximum-input-tokens-per-call <maximum-input-tokens> \
  --output data/outputs/scenario_generation/v0.5.2/checkpoints/calibration_cost_report.json

uv run risk-comm scenarios approve-generation \
  --cost-report data/outputs/scenario_generation/v0.5.2/checkpoints/calibration_cost_report.json \
  --approved-maximum-cost-usd <maximum-cost> \
  --approved-by <researcher-id> \
  --output data/outputs/scenario_generation/v0.5.2/checkpoints/calibration_approval.json \
  --approve
```

Only the matching, self-hashed report and approval unlock candidate generation:

```bash
uv run risk-comm scenarios generate \
  --backend src.scenarios.openrouter_backend:create_openrouter_scenario_backend \
  --stage calibration \
  --cost-report data/outputs/scenario_generation/v0.5.2/checkpoints/calibration_cost_report.json \
  --approval data/outputs/scenario_generation/v0.5.2/checkpoints/calibration_approval.json \
  --output-root data/outputs/scenario_generation/v0.5.2 \
  --execute-paid
```

For each evaluation batch, replace `--stage calibration` with `--stage evaluation --use-case-id CF001`, use fixed `CF001_cost_report.json` and `CF001_approval.json` checkpoint paths, and pass the frozen `--tight-limit-manifest` plus the accepted `--calibration-candidate`. Repeat independently for CF002–CF010; an approval for one batch cannot unlock another.

Generated sources use the ten deterministic templates in `src/scenarios/source_rendering.py`. Pair diagnostics are calculated by `src/scenarios/pair_diagnostics.py` and displayed in `src/review_app.py`; they do not impose automatic balance thresholds.

After all automated/researcher gates and minimal-response approval, publish only to `data/inputs/scenarios/v0.5.2/accepted/`, then build the V2 manifest:

```bash
uv run risk-comm scenarios build-manifest \
  --accepted-root data/inputs/scenarios/v0.5.2/accepted \
  --scope complete \
  --published-by <researcher-id> \
  --output data/inputs/scenarios/v0.5.2/accepted_scenario_manifest.json
```

Then review all 80 exact rendered requests—neutral and concerned for every R1–R4 scenario—and bind those actual request bytes to the accepted scenario manifest:

```bash
uv run risk-comm experiment freeze-prompts \
  --request-reviews <complete-request-reviews.json> \
  --accepted-root data/inputs/scenarios/v0.5.2/accepted \
  --accepted-scenario-manifest data/inputs/scenarios/v0.5.2/accepted_scenario_manifest.json \
  --researcher-notes <review-notes> \
  --decision approve \
  --reviewed-by <researcher-id> \
  --output data/outputs/experiments/risk_comm_v1/manifests/prompt_review.json
```

Relevant code: `src/cli/commands/scenarios/dry_run_generation.py`, `src/cli/commands/scenarios/approve_generation.py`, `src/cli/commands/scenarios/generate.py`, `src/scenarios/source_rendering.py`, `src/scenarios/pair_diagnostics.py`, and `src/prompts/experiment.py`.
