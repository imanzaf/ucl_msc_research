# Implementation status

**Active protocol:** selective risk communication under word-budget pressure and expressed concern

**Software:** 0.1.0

**Seed:** V0.5.2 (V0.5.1 preserved)

**Artifact schema:** 2.0.0

## Implemented offline

- Five-domain confirmatory composite with exact frozen weights, conditional applicability, signed/reverse pair gaps, and exact-span distortion exclusivity.
- Initial and cumulative scoring, with cumulative-minus-initial labelled spontaneous additional communication.
- Four cue pairs, R1–R4/C1 mappings, exact alternative-phrase rejection, 80-request review manifest, and persisted `expressed_concern` labels.
- Ten fixed natural follow-ups and removal of the active explicit risk-repair prompt/UI.
- Corrected immutable V0.5.2 seed and ten deterministic domain-native source renderers.
- Blinded pair diagnostics in the scenario viewer; researcher pair matching remains the acceptance control.
- Descriptive budget, length, coverage-rate, first-valence, acknowledgement, valence-allocation, and disclaimer metrics.
- Two-test scenario sign-flip inference, stratified scenario bootstrap, cluster-aware equivalence intervals, complete-design power simulation, and composite sensitivities.
- Exactly 80 calibration and 160 evaluation annotations, each once.
- Domain validation diagnostics plus hashed blinded validation-disposition manifest and proportional renormalisation logic.
- Separate 480/240/120 primary/material-priority/brevity-locus run-plan builders and output layouts.
- Stable exploratory paper-asset generators.

## Still gated

- Researcher acceptance of generated V0.5.2 scenarios and all 80 complete rendered requests.
- Model freeze, ample pilot, tight-limit freeze, scoring calibration, domain-gate freeze, and preregistration hashes.
- Batch-bound dry-run cost reports and explicit approvals for scenario generation and each 480/240/120 experiment run; provider-backed scoring remains separately gated by `--execute-paid`.
- Any scenario-generation, evaluated-model, or scoring-provider request.

## Required offline acceptance checks

```bash
uv run pytest
uv run pre-commit run --all-files
uv run risk-comm maintenance export-schemas
uv run risk-comm maintenance validate-protocol
uv run risk-comm maintenance validate-docs
```

The project code-review workflow must run after the implementation test suite is green. No reading-list artifact is changed by this protocol update.
