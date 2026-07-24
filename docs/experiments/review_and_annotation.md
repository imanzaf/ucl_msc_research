# Local scenario review and blinded annotation

Launch the local-only interface:

```bash
uv run risk-comm review launch --server-address 127.0.0.1
```

The two pages are scenario review and one-pass conversation annotation. [src/review_app.py](../../src/review_app.py) contains no API client and exposes no generation, experiment, or scoring action.

For each V0.9.0 candidate, the scenario page separates the exact evaluated deployment context and customer turns from the hidden source/research
design. It also shows the deterministic text-native evidence packet, canonical validation facts, and both blinded pair diagnostics. The diagnostics
include proposition/evidence length, literal numeric, conditional, and hedging burden, readability, fixed source position, shared number strings,
and materiality ratings. They are descriptive: `pair_matching_acceptable` remains the mandatory researcher judgement and there is no automatic
threshold. Arithmetic dependency is false because V0.9.0 has no numeric registry or generated calculation layer.

The scenario page uses a point-and-click decision form. Select a decision, complete the named checklist, and optionally copy zero to three exact
phrases per material fact for later specificity scoring. A blank fact is valid and receives no specificity score. Selected phrases are stored
separately as `specificity_elements`; they are not generated or embedded in material-fact records. One submission writes the schema-3.0.0 researcher
review and optional marker selection. There is no reference-response review or approval step. Progress remains resumable if the browser closes.

Exactly 80 calibration and 160 locked evaluation conversations are annotated once. There is no repeat, resolution, or outcome-enriched annotation path. Records are atomically persisted as strict JSONL.

Create condition-blind inputs and the evaluation sample manifest:

```bash
uv run risk-comm scoring sample-annotations \
  --stage evaluation \
  --transcripts data/outputs/experiments/risk_comm_v1/results/<YYYYMMDDTHHMMSS>_results.jsonl \
  --accepted-root data/inputs/scenarios/v0.9.0/accepted \
  --accepted-scenario-manifest data/inputs/scenarios/v0.9.0/accepted_scenario_manifest.json \
  --scoring-execution-manifest data/outputs/experiments/risk_comm_v1/manifests/scoring_execution.json \
  --scoring-input-root data/outputs/experiments/risk_comm_v1/checkpoints/blind_inputs \
  --output-manifest data/outputs/experiments/risk_comm_v1/manifests/evaluation_annotation_sample.json
```

Use `--stage calibration` with the complete 120-conversation calibration transcript. Sampling is seeded and the manifest persists every inclusion probability.

After calibration, the researcher supplies thresholds and rationales for all five domains and freezes them against the exact calibration source:

```bash
uv run risk-comm scoring freeze-validation-gates \
  --gates-json data/inputs/researcher/validation_gates.json \
  --calibration-source data/outputs/experiments/risk_comm_v1/results/calibration_annotations.jsonl \
  --frozen-by <researcher-id> \
  --output data/outputs/experiments/risk_comm_v1/manifests/domain_validation_gates.json
```

Calculate complete blinded diagnostics:

```bash
uv run risk-comm scoring validate \
  --annotation-sample-manifest data/outputs/experiments/risk_comm_v1/manifests/evaluation_annotation_sample.json \
  --annotations data/outputs/review/records/conversation_annotations.jsonl \
  --scored-bundles data/outputs/experiments/risk_comm_v1/results/scoring/scored_conversations.jsonl \
  --source-transcripts data/outputs/experiments/risk_comm_v1/results/<YYYYMMDDTHHMMSS>_results.jsonl \
  --domain-gate-manifest data/outputs/experiments/risk_comm_v1/manifests/domain_validation_gates.json \
  --output data/outputs/experiments/risk_comm_v1/results/scoring_validation_report.json
```

If any domain fails, inspect the complete blinded report and record exactly one permitted disposition per failed domain:

```bash
uv run risk-comm scoring record-validation-disposition \
  --validation-report data/outputs/experiments/risk_comm_v1/results/scoring_validation_report.json \
  --actions-json data/inputs/researcher/validation_dispositions.json \
  --researcher-id <researcher-id> \
  --rationale "Decision made while treatment labels and effect estimates remained unavailable." \
  --output data/outputs/experiments/risk_comm_v1/manifests/validation_disposition.json
```

The permitted actions are `full_manual_scoring`, `remove_and_renormalise`, and `withhold_confirmatory_inference`. The resulting score weights and decision are self-hashed.
