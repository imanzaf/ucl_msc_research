# Analysis runbook

The confirmatory input is the initial `selective_risk_communication_score`. H1 is tight minus ample; H2 is concerned minus neutral. Both average paired repeated cells within scenario.

## Frozen inference

- two-sided scenario-level paired sign-flip tests;
- exactly 100,000 seeded permutations;
- Holm correction across H1 and H2;
- exactly 10,000 use-case-stratified scenario-bootstrap draws for 95% intervals; and
- cluster-aware 90% bootstrap intervals for equivalence.

```bash
uv run risk-comm analysis run \
  --analysis-input data/outputs/experiments/risk_comm_v1/results/analysis_input.jsonl \
  --fact-analysis-input data/outputs/experiments/risk_comm_v1/results/fact_analysis_input.jsonl \
  --human-reference-analysis-input data/outputs/experiments/risk_comm_v1/results/human_reference.jsonl \
  --missingness-report data/outputs/experiments/risk_comm_v1/results/missingness.json \
  --experiment-manifest data/outputs/experiments/risk_comm_v1/manifests/experiment_manifest.json \
  --preregistration-manifest data/outputs/experiments/risk_comm_v1/manifests/preregistration.json \
  --annotation-sample-manifest data/outputs/experiments/risk_comm_v1/manifests/evaluation_annotation_sample.json \
  --scoring-validation-report data/outputs/experiments/risk_comm_v1/results/scoring_validation.json \
  --validation-disposition-manifest data/outputs/experiments/risk_comm_v1/manifests/validation_disposition.json \
  --smallest-effect-manifest data/outputs/experiments/risk_comm_v1/manifests/smallest_effects.json \
  --analysis-plan docs/research-plan/RESEARCH_PLAN.md \
  --protocol-deviations data/outputs/experiments/risk_comm_v1/manifests/protocol_deviations.json \
  --output-summary data/outputs/experiments/risk_comm_v1/results/confirmatory_summary.json \
  --sensitivity-summary data/outputs/experiments/risk_comm_v1/results/sensitivity_summary.json \
  --equivalence-summary data/outputs/experiments/risk_comm_v1/results/equivalence_summary.json \
  --r-input-csv data/outputs/experiments/risk_comm_v1/results/r_input.csv \
  --r-output-summary data/outputs/experiments/risk_comm_v1/results/r_summary.json \
  --assets-dir data/outputs/experiments/risk_comm_v1/assets
```

If the blinded validation disposition chooses full-sample manual scoring for any failed domain, add `--manual-domain-analysis-input data/outputs/experiments/risk_comm_v1/results/manual_domain_analysis_input.jsonl`.

The sensitivity summary reports H1/H2 for every domain, every signed and reverse pairwise gap, the cumulative composite, and cumulative-minus-initial spontaneous additional communication. Robustness includes cue-template fixed effects/heterogeneity, fact/pair/scenario random effects, leave-one-template-out, equal-domain, and leave-one-domain-out analyses. Exploratory experiments use paired estimates and scenario-cluster intervals without confirmatory p-values.

Relevant code: `src/analysis/estimands.py`, `src/analysis/sign_flip.py`, `src/analysis/bootstrap.py`, `src/analysis/equivalence.py`, `src/analysis/sensitivities.py`, `src/analysis/power.py`, and `analysis/r/run_mixed_models.R`.
