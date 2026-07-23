# Scoring and validation runbook

Scoring uses three condition-blind V2 contracts: proposition/specificity/framing, response communication, and factual claims. Exact source and response spans are validated before metrics are calculated.

## Frozen composite

`src/scoring/metrics.py` computes:

```text
0.30 coverage asymmetry
+ 0.15 specificity asymmetry
+ 0.20 framing/reassurance distortion
+ 0.15 salience asymmetry
+ 0.20 factual-integrity failure
```

Specificity and salience contribute zero when either pair member is omitted. Exact spans cannot be reused across minimisation, amplification, unsupported reassurance, and disclaimer washing. Initial and cumulative checkpoints use the same formula; cumulative minus initial is spontaneous additional communication.

## Annotation sample

```bash
uv run risk-comm scoring sample-annotations \
  --stage evaluation \
  --transcripts data/outputs/experiments/risk_comm_v1/results/<YYYYMMDDTHHMMSS>_results.jsonl \
  --accepted-root data/inputs/scenarios/v0.7.0/accepted \
  --accepted-scenario-manifest data/inputs/scenarios/v0.7.0/accepted_scenario_manifest.json \
  --scoring-execution-manifest data/outputs/experiments/risk_comm_v1/manifests/scoring_execution.json \
  --scoring-input-root data/outputs/experiments/risk_comm_v1/checkpoints/blind_inputs \
  --output-manifest data/outputs/experiments/risk_comm_v1/manifests/evaluation_annotation_sample.json
```

Calibration contains exactly 80 conversations and evaluation exactly 160; each is annotated once. There is no repeat/resolution workflow.

## Validation contingency

The blinded `ScoringValidationReport` stores coverage, specificity, framing, salience, and integrity diagnostics: prevalence, agreement, confusion matrices, precision, recall, F1, uncertainty intervals, salience error where applicable, and invalid outputs.

Every failed domain must receive one pre-treatment disposition in `ValidationDispositionManifest`:

- `full_manual_scoring`;
- `remove_and_renormalise`; or
- `withhold_confirmatory_inference`.

`src/scoring/disposition.py` derives the resulting weights and hashes the decision. `src/cli/commands/analysis/run.py` refuses inference if the disposition is missing, mismatched, or withholds inference.

Freeze all five calibration-derived gates before held-out evaluation labels are examined:

```bash
uv run risk-comm scoring freeze-validation-gates \
  --gates-json <five-domain-gates.json> \
  --calibration-source data/outputs/experiments/risk_comm_calibration_v1/results/calibration_diagnostics.json \
  --frozen-by <researcher-id> \
  --output data/outputs/experiments/risk_comm_v1/manifests/domain_validation_gates.json
```

After the 160 locked one-pass evaluation annotations are complete, generate the full blinded diagnostics:

```bash
uv run risk-comm scoring validate \
  --annotation-sample-manifest data/outputs/experiments/risk_comm_v1/manifests/evaluation_annotation_sample.json \
  --annotations data/outputs/experiments/risk_comm_v1/results/evaluation_annotations.jsonl \
  --scored-bundles data/outputs/experiments/risk_comm_v1/results/scored_conversations.jsonl \
  --source-transcripts data/outputs/experiments/risk_comm_v1/results/<YYYYMMDDTHHMMSS>_results.jsonl \
  --domain-gate-manifest data/outputs/experiments/risk_comm_v1/manifests/domain_validation_gates.json \
  --output data/outputs/experiments/risk_comm_v1/results/scoring_validation.json
```

If any domain fails, inspect the complete blinded report and record exactly one allowed action for every failed domain before treatment labels or effect estimates are made available:

```bash
uv run risk-comm scoring record-validation-disposition \
  --validation-report data/outputs/experiments/risk_comm_v1/results/scoring_validation.json \
  --actions-json <failed-domain-actions.json> \
  --researcher-id <researcher-id> \
  --rationale <blinded-rationale> \
  --output data/outputs/experiments/risk_comm_v1/manifests/validation_disposition.json
```

No scoring command should be run against a paid provider during offline implementation.
