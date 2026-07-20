# Local scenario review and blinded annotation

Launch only on localhost:

```bash
uv run streamlit run scripts/review_app.py --server.address 127.0.0.1
```

The six pages are scenario initial review, scenario delayed repeat, scenario resolution, conversation initial annotation, conversation delayed repeat, and conversation resolution. `src/review_app.py` contains no API client and exposes no generation, experiment, or scoring action.

Scenario inputs are hash-valid candidates under `data/outputs/scenario_generation/v0.5.1/`; only after initial/repeat/resolution review and minimal-response approval are they published into `data/inputs/scenarios/v0.5.1/accepted/`. Condition-blind conversation inputs come from `data/outputs/review/scoring_inputs/`. Records are atomically persisted as strict JSONL under `data/outputs/review/records/`; there is no database.

Repeat records are unavailable until 14 elapsed days. Conversation repeats receive a new opaque identifier and a deterministic non-identical fact order. Repeat pages return the source artifact only and do not load or display previous decisions, notes, or labels. Resolution pages are the only workflows that may show both completed passes.

Required samples are:

- all 50 scenarios initially reviewed;
- delayed repeat review of all 10 C1 calibration scenarios and all 40 R1-R4 evaluation scenarios after 14 days;
- at least 80 calibration conversations for rubric/judge development;
- 160 locked evaluation conversations, four per evaluation scenario;
- at least 40 delayed evaluation repeats.

Create the condition-blind local inputs and frozen sample manifest from a complete transcript file:

```bash
uv run python scripts/build_annotation_sample.py \
  --stage evaluation \
  --transcripts data/outputs/experiments/risk_comm_v1/results/<timestamp>_results.jsonl \
  --accepted-root data/inputs/scenarios/v0.5.1/accepted \
  --accepted-scenario-manifest data/inputs/scenarios/v0.5.1/accepted_scenario_manifest.json \
  --scoring-execution-manifest data/outputs/experiments/risk_comm_v1/checkpoints/scoring_execution_manifest.json \
  --scoring-input-root data/outputs/review/evaluation_scoring_inputs \
  --output-manifest data/outputs/experiments/risk_comm_v1/checkpoints/evaluation_annotation_sample_manifest.json
```

Use `--stage calibration` with the complete 240-conversation calibration transcript to select the 80 rubric-development conversations. Selection is seeded probability sampling: calibration samples one available model within every C1 × cell stratum; evaluation samples one available conversation within every scenario × word-budget × integrity stratum. The manifest records every inclusion probability. Evaluation also freezes one seeded repeat item per scenario.

After annotation and condition-blind automated scoring, calculate rather than hand-enter the hard gates:

```bash
uv run python scripts/build_scoring_validation_report.py \
  --annotation-sample-manifest data/outputs/experiments/risk_comm_v1/checkpoints/evaluation_annotation_sample_manifest.json \
  --annotations data/outputs/review/records/conversation_annotations.jsonl \
  --scored-bundles data/outputs/experiments/risk_comm_v1/results/scoring/scored_conversations.jsonl \
  --source-transcripts data/outputs/experiments/risk_comm_v1/results/<timestamp>_results.jsonl \
  --failed-actions data/outputs/experiments/risk_comm_v1/checkpoints/failed_construct_actions.json \
  --output data/outputs/experiments/risk_comm_v1/results/scoring_validation_report.json \
  --reassurance-used-in-headline
```

The failed-actions file is a strict `1.0.0` JSON object with an `actions` mapping from each failed construct name to `full_manual_scoring`, `demote_to_exploratory`, or `remove`, chosen while treatment labels remain hidden.

`src/scoring/reliability.py` enforces the disclosure, omission, false-claim, framing, and reassurance gates. False claims are matched one-to-one by checkpoint, error type, turn, and the frozen ≥50%-of-shorter-span overlap rule; unsupported and overcertain claims cannot inflate false-claim precision/recall. A failed construct must be assigned full manual scoring, exploratory demotion, or removal while conditions remain blinded.

After the final evaluation annotations close, build the human-reference sensitivity rows:

```bash
uv run python scripts/build_human_reference_analysis_inputs.py \
  --annotation-sample-manifest data/outputs/experiments/risk_comm_v1/checkpoints/evaluation_annotation_sample_manifest.json \
  --annotations data/outputs/review/records/conversation_annotations.jsonl \
  --transcripts data/outputs/experiments/risk_comm_v1/results/<timestamp>_results.jsonl \
  --accepted-root data/inputs/scenarios/v0.5.1/accepted \
  --accepted-scenario-manifest data/inputs/scenarios/v0.5.1/accepted_scenario_manifest.json \
  --scoring-execution-manifest data/outputs/experiments/risk_comm_v1/checkpoints/scoring_execution_manifest.json \
  --output data/outputs/experiments/risk_comm_v1/results/human_reference_analysis_inputs.jsonl
```
