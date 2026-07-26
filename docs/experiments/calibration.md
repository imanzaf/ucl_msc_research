# Calibration matrix

The rubric-development experiment is `risk_comm_calibration_v1`: ten accepted C1 scenarios × three frozen evaluated models × four primary cells, or
120 conversations and 240 assistant responses. Each scenario has one fixed four-fact list. Calibration is excluded from held-out confirmatory
estimates.

After the ample pilot, all scenario reviews, and the final ten-use-case budget freeze, use the exact `risk-comm experiment build-manifests` command in [risk_comm_v1.md](risk_comm_v1.md) to create the self-hashed `CalibrationExperimentManifest`. It binds the complete accepted scenario manifest, evaluated snapshots, reviewed prompts, word budgets, active prompt-package hash, temperature-zero decoding, seed, and retry policy. Then build the config and plan:

```bash
uv run risk-comm calibration build-plan \
  --calibration-manifest data/outputs/experiments/risk_comm_calibration_v1/checkpoints/calibration_manifest.json \
  --accepted-root data/inputs/scenarios/v0.11.0/accepted \
  --accepted-scenario-manifest data/inputs/scenarios/v0.11.0/accepted_scenario_manifest.json \
  --evaluated-model-manifest <evaluated_model_manifest.json> \
  --prompt-review-manifest <prompt_review_manifest.json> \
  --word-budget-manifest <word_budget_manifest.json>
```

The builder writes `data/outputs/experiments/risk_comm_calibration_v1/config.json` before `checkpoints/run_plan.jsonl` and validates all 30 randomised four-cell blocks.

Execute with immediate resumable persistence:

```bash
uv run risk-comm calibration run \
  --calibration-manifest data/outputs/experiments/risk_comm_calibration_v1/checkpoints/calibration_manifest.json \
  --accepted-root data/inputs/scenarios/v0.11.0/accepted \
  --accepted-scenario-manifest data/inputs/scenarios/v0.11.0/accepted_scenario_manifest.json \
  --evaluated-model-manifest <evaluated_model_manifest.json> \
  --prompt-review-manifest <prompt_review_manifest.json> \
  --word-budget-manifest <word_budget_manifest.json> \
  --results data/outputs/experiments/risk_comm_calibration_v1/results/<timestamp>_results.jsonl \
  --log data/outputs/experiments/risk_comm_calibration_v1/logs/<timestamp>_run.log \
  --execute-paid
```

Create the 80-conversation seeded blind rubric-development sample with the scoring manifest's exact fact-order seed:

```bash
uv run risk-comm scoring sample-annotations \
  --stage calibration \
  --transcripts data/outputs/experiments/risk_comm_calibration_v1/results/<timestamp>_results.jsonl \
  --accepted-root data/inputs/scenarios/v0.11.0/accepted \
  --accepted-scenario-manifest data/inputs/scenarios/v0.11.0/accepted_scenario_manifest.json \
  --scoring-execution-manifest <scoring_execution_manifest.json> \
  --scoring-input-root data/outputs/review/calibration_scoring_inputs \
  --output-manifest data/outputs/experiments/risk_comm_calibration_v1/checkpoints/calibration_annotation_sample_manifest.json
```

After calibration reporting, generate the stable completion asset:

```bash
uv run risk-comm calibration assets \
  --transcripts data/outputs/experiments/risk_comm_calibration_v1/results/<timestamp>_results.jsonl \
  --assets-dir data/outputs/experiments/risk_comm_calibration_v1/assets
```

Calibration may refine rubric wording and judge selection. Held-out R1–R2 artifacts and evaluation results must not be consulted for those changes;
the final scoring-execution and main experiment manifests are frozen only afterward.

Relevant code: `src/cli/commands/calibration/build_plan.py`, `src/cli/commands/calibration/run.py`, `src/experiments/scenario_runner.py`, and `src/cli/commands/scoring/sample_annotations.py`.
