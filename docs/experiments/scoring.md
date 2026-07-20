# Condition-blind scoring

`src/experiments/scoring_pipeline.py` builds an anonymised scoring input containing only the source visible to the evaluated model, randomised fact definitions, and agent turns 1 and 3. It does not expose word budget, cue, integrity, evaluated model, source-order label, or hypothesis direction.

Three separate contracts run through `src/prompts/scoring_contracts.py`:

1. fact disclosure, conditional specificity, and conditional framing;
2. supportive acknowledgement, unsupported reassurance, refusal, and signposting;
3. false, unsupported, and overcertain claims using visible evidence only.

`src/scoring/validation.py` checks every fact ID, quote, turn index, exact character span, specificity/evidence reference, and visible-source hash before metrics are calculated. Initial judgments may cite only agent turn 1; cumulative judgments may cite turns 1 and 3.

After explicit scoring-call approval, run:

```bash
uv run risk-comm scoring run \
  --backend src.experiments.openrouter_scoring:create_openrouter_scoring_backend \
  --transcripts data/outputs/experiments/risk_comm_v1/results/<timestamp>_results.jsonl \
  --accepted-root data/inputs/scenarios/v0.5.1/accepted \
  --accepted-scenario-manifest data/inputs/scenarios/v0.5.1/accepted_scenario_manifest.json \
  --experiment-manifest data/outputs/experiments/risk_comm_v1/checkpoints/experiment_manifest.json \
  --scoring-execution-manifest data/outputs/experiments/risk_comm_v1/checkpoints/scoring_execution_manifest.json \
  --results-dir data/outputs/experiments/risk_comm_v1/results/scoring \
  --execute-paid
```

Each automated result binds provider request ID, exact returned judge version, finish reason, token usage, request/response hashes, and the frozen judge snapshot. Each success is one atomic, self-hashed `ScoredConversationBundle` in `scored_conversations.jsonl`; failed identical-package attempts are appended immediately to `failed_attempts.jsonl`, and exhausted records enter `manual_scoring_queue.jsonl`. Resume rejects outputs created under different transcript, scoring-manifest, or scoring-contract hashes. There is no composite score and no user-harm metric.

Resolve every terminal queue record from a final condition-blind human annotation before analysis:

```bash
uv run risk-comm scoring resolve-manual \
  --manual-queue data/outputs/experiments/risk_comm_v1/results/scoring/manual_scoring_queue.jsonl \
  --annotations <final_manual_scoring_annotations.jsonl> \
  --transcripts data/outputs/experiments/risk_comm_v1/results/<timestamp>_results.jsonl \
  --accepted-root data/inputs/scenarios/v0.5.1/accepted \
  --accepted-scenario-manifest data/inputs/scenarios/v0.5.1/accepted_scenario_manifest.json \
  --scoring-execution-manifest data/outputs/experiments/risk_comm_v1/checkpoints/scoring_execution_manifest.json \
  --output data/outputs/experiments/risk_comm_v1/results/scoring/manual_resolutions.jsonl
```

After scoring is complete, join treatment labels only through the immutable run units:

```bash
uv run risk-comm analysis build-inputs \
  --transcripts data/outputs/experiments/risk_comm_v1/results/<timestamp>_results.jsonl \
  --scored-bundles data/outputs/experiments/risk_comm_v1/results/scoring/scored_conversations.jsonl \
  --manual-resolutions data/outputs/experiments/risk_comm_v1/results/scoring/manual_resolutions.jsonl \
  --experiment-manifest data/outputs/experiments/risk_comm_v1/checkpoints/experiment_manifest.json \
  --accepted-root data/inputs/scenarios/v0.5.1/accepted \
  --accepted-scenario-manifest data/inputs/scenarios/v0.5.1/accepted_scenario_manifest.json \
  --scoring-execution-manifest data/outputs/experiments/risk_comm_v1/checkpoints/scoring_execution_manifest.json \
  --output data/outputs/experiments/risk_comm_v1/results/analysis_inputs.jsonl \
  --fact-analysis-output data/outputs/experiments/risk_comm_v1/results/fact_analysis_inputs.jsonl \
  --missingness-report data/outputs/experiments/risk_comm_v1/results/missingness_report.json
```

The join requires the full 480-unit primary terminal ledger, but correctly permits retry-exhausted provider outcomes to remain missing. Every completed conversation must have exactly one automated bundle or validated manual resolution. The self-hashed missingness report binds the complete ledger, analyzable subset, reasons, conversation-level input, and four-fact/two-checkpoint ordinal input.
