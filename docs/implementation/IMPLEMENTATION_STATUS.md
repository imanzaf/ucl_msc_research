# Implementation status

**Active protocol:** selective risk communication under word-budget pressure and expressed concern

**Software:** 0.1.0

**Seed:** V0.7.0 (V0.5.1, V0.5.2, and V0.6.0 preserved)

**Artifact schema:** 2.0.0

No V1 experiment output or generated/accepted schema-2.0.0 scenario artifact exists. The V0.7.0 change therefore updates the pre-execution protocol without reusing or overwriting a frozen run.

## Implemented offline

- Five-domain confirmatory composite with exact frozen weights, conditional applicability, signed/reverse pair gaps, and exact-span distortion exclusivity.
- Initial and cumulative scoring, with cumulative-minus-initial labelled spontaneous additional communication.
- Four cue pairs, R1–R4/C1 mappings, exact alternative-phrase rejection, separate 20-request C1 and 80-request evaluation review manifests, and persisted `expressed_concern` labels.
- Seed-owned natural initial/follow-up customer messages and removal of the active explicit risk-repair prompt/UI.
- Immutable V0.7.0 high-stakes decision-support seed with a latent customer/provider conflict in all ten families.
- Explicit deployment role/entity/general-task/authority context, customer-message, hidden-research, diagnostic, and generation-input groups, with legacy scenario-specific task and genre fields removed.
- Ten V0.7.0 deterministic domain-native source renderers plus rejection of hidden-conflict and simulation-framing leakage.
- Separate evaluated-deployment and hidden-research panels plus blinded pair diagnostics in the scenario viewer; researcher high-stakes, conflict, direction, isolation, and pair-matching checks control acceptance.
- Descriptive budget, length, coverage-rate, first-valence, acknowledgement, valence-allocation, and disclaimer metrics.
- Two-test scenario sign-flip inference, stratified scenario bootstrap, cluster-aware equivalence intervals, complete-design power simulation, and composite sensitivities.
- Exactly 80 calibration and 160 evaluation annotations, each once.
- Domain validation diagnostics plus hashed blinded validation-disposition manifest and proportional renormalisation logic.
- Separate 480/240/120 primary/material-priority/brevity-locus run-plan builders and output layouts.
- Stable exploratory paper-asset generators.

## Still gated

- Researcher acceptance of generated V0.7.0 scenarios, all twenty C1 requests, and all 80 held-out requests.
- Canonical model freeze, hash-linked ample pilot with a complete success/failure attempt audit, tight-limit and final word-budget freezes, scoring calibration, domain-gate freeze, and preregistration hashes.
- Batch-bound dry-run cost reports and explicit approvals for scenario generation, the 60-response ample pilot, and each 480/240/120 experiment run; provider-backed scoring remains separately gated by `--execute-paid`.
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
