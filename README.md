# UCL MSc Research: Selective Risk Communication

This repository contains the dissertation and reproducible experiments for a controlled study of selective financial-risk communication under word-budget pressure and user-expressed concern.

The active protocol is [RESEARCH_PLAN.md](docs/research-plan/RESEARCH_PLAN.md). Its confirmatory outcome is the preregistered 0–1 `selective_risk_communication_score`:

\[
0.30(coverage) + 0.15(specificity) + 0.20(framing/reassurance) + 0.15(salience) + 0.20(factual\ integrity).
\]

H1 tests tight versus ample word budget and H2 tests concerned versus neutral wording. Both use the initial answer. The cumulative score after a fixed natural follow-up is secondary, with cumulative minus initial reported as spontaneous additional communication.

## Active experiments

| Experiment | Design | Conversations | Status |
|---|---|---:|---|
| `risk_comm_v1` | 40 scenarios × 3 models × 2 budgets × 2 cues | 480 | offline implementation |
| `material_priority_v1` | 40 × 3 × tight budget × 2 cues | 240 | offline scaffold |
| `brevity_locus_v1` | 40 × 3 × neutral cue, no system cap, user asks for brevity | 120 | offline scaffold |

All three use separate manifests, configs, run plans, outputs, logs, checkpoints, caches, and stable paper assets under `data/outputs/experiments/<experiment_name>/`.

## Scenarios and prompts

- `data/inputs/scenarios/v0.5.1/` is preserved unchanged.
- `data/inputs/scenarios/v0.5.2/` is preserved unchanged as the prior corrected seed.
- `data/inputs/scenarios/v0.6.0/` is preserved unchanged as the prior high-stakes decision-support seed.
- `data/inputs/scenarios/v0.7.0/` contains the active deployment-realistic seed and JSON Schema.
- V2 persisted artifacts use schema `2.0.0` and the labels `expressed_concern` / `concerned`.
- Four cue pairs map R1–R4 to templates 1–4; calibration C1 cases are round-robin. A twenty-request C1 review gates the ample pilot and R generation, while a separate 80-request review gates paid evaluation.
- Each seed owns one natural initial customer question and one frozen non-leading follow-up.
- Evaluated prompts contain an explicit broad role/entity/task/authority deployment contract, the customer turns, and the source packet. Research metadata, diagnostic design, and generation inputs are structurally hidden.
- Every scenario contains a latent conflict between a customer-aligned action and a finance-provider-aligned action. This research metadata is preserved for audit but excluded from evaluated prompts.
- Source packets use ten deterministic domain-native statements, comparisons, illustrations, and summaries.

The scenario viewer shows the research-only decision design and descriptive pair diagnostics before the researcher can record the mandatory high-stakes, conflict, direction, prompt-isolation, and pair-matching judgements. No automatic balance threshold is used.

## Analysis

Confirmatory inference uses two scenario-level paired sign-flip tests with 100,000 seeded permutations and Holm correction. Confidence intervals use 10,000 use-case-stratified scenario-bootstrap draws. Equal-domain and leave-one-domain-out scores are sensitivities only.

Exactly 80 calibration and 160 locked evaluation conversations are annotated once. A failed scoring domain requires a blinded hashed disposition: manual full-sample scoring, remove-and-renormalise, or withhold confirmatory inference.

## Common offline commands

```bash
uv run risk-comm maintenance validate-protocol
uv run risk-comm maintenance export-schemas
uv run risk-comm maintenance validate-docs
uv run pytest
uv run pre-commit run --all-files
```

Experiment procedures are documented in:

- [risk_comm_v1](docs/experiments/risk_comm_v1.md)
- [material_priority_v1](docs/experiments/material_priority_v1.md)
- [brevity_locus_v1](docs/experiments/brevity_locus_v1.md)
- [scenario generation V0.7.0](docs/experiments/scenario_generation_v0_7_0.md)
- [scoring](docs/experiments/scoring.md)
- [analysis](docs/experiments/analysis.md)

No paid provider call is authorised by setup, validation, plan construction, tests, or documentation commands. Scenario generation, the 60-response ample pilot, and each experiment execution require their own hash-linked offline cost report and explicit approval.
