# Implementation status

**Active protocol:** selective risk communication under word-budget pressure and expressed concern

**Software:** 0.1.0

**Seed:** V0.9.0 (V0.5.1–V0.8.0 preserved)

**Generated/accepted scenario artifact schema:** 3.0.0

The V0.9.0 seed, source-only generation contract, manual specificity-marker review flow, and downstream scoring linkage are implemented and tested.
Prior ignored V0.8.0 C1 candidates are superseded and cannot be published through the active V0.9 paths. No V0.9 candidate has researcher
acceptance, and no V1 experiment output or accepted scenario artifact exists.

## Implemented offline

- Five-domain confirmatory composite with exact frozen weights, conditional applicability, signed/reverse pair gaps, and exact-span distortion exclusivity.
- Initial and cumulative scoring, with cumulative-minus-initial labelled spontaneous additional communication.
- Four cue pairs, R1–R4/C1 mappings, exact alternative-phrase rejection, separate 20-request C1 and 80-request evaluation review manifests, and persisted `expressed_concern` labels.
- Seed-owned natural initial/follow-up customer messages and removal of the active explicit risk-repair prompt/UI.
- Immutable V0.9.0 high-stakes decision-support seed with neutral two-option source blueprints and separate hidden research mappings.
- Source generation returns four canonical facts first and four matching natural evidence items second; there is no fixed neutral-fact inventory,
  and numeric registries and generated titles, headings, labels, reference responses, and specificity fields are absent.
- Seed/code-owned neutral labels and presentation orders, counterbalanced 25/25 across all scenarios and 2/2 within every R1–R4 use-case set.
- Researcher review optionally selects zero to three exact fact-linked specificity phrases per fact; unmarked facts have no specificity score.
- Budget calibration counts and hashes the four canonical facts directly, with no minimal-response review or approval workflow.
- Explicit deployment role/entity/general-task/authority context and natural initial/follow-up messages, separated from one compact hidden decision/evidence/generation design.
- Balanced benefit/downside evidence for both options, with code-owned provider-supporting versus customer-supporting scoring direction.
- Ten deterministic domain-native evidence renderers and one fixed, seed-ordered packet per scenario; presentation order is controlled but not an
  experimental factor.
- One semantic review per C1 and one combined semantic/diversity review per R1–R4 batch, with one automated revision round and deterministic structural validation.
- Resumable per-C1 persistence, raw structured-response audit logs, pipeline failure records, prompt-hash-aware review invalidation, archived superseded artifacts, and non-blocking incomplete numeric-diagnostic mappings.
- Generator-boundary normalisation for non-arithmetic values, optional numeric references, repeated exact evidence, and percentage-point multiplication while retaining strict calculation dependencies and verbatim source support.
- Separate evaluated-deployment and hidden-research panels plus blinded descriptive pair diagnostics, including hedging burden; researcher
  high-stakes, conflict, direction, isolation, and pair-matching checks control acceptance without automatic artifact thresholds.
- Descriptive budget, length, coverage-rate, first-alignment, acknowledgement, alignment-allocation, option × polarity coverage, and disclaimer metrics.
- Two-test scenario sign-flip inference, stratified scenario bootstrap, cluster-aware equivalence intervals, complete-design power simulation, and composite sensitivities.
- Exactly 80 calibration and 160 evaluation annotations, each once.
- Domain validation diagnostics plus hashed blinded validation-disposition manifest and proportional renormalisation logic.
- Separate 480/240/120 primary/material-priority/brevity-locus run-plan builders and output layouts.
- Stable exploratory paper-asset generators.

## Still gated

- Fresh paid generation and researcher acceptance of ten V0.9.0 C1 scenarios, all twenty C1 rendered requests, and all 80 held-out requests.
- Canonical model freeze, hash-linked ample pilot with a complete success/failure attempt audit, tight-limit and final word-budget freezes, scoring calibration, domain-gate freeze, and preregistration hashes.
- Batch-bound dry-run cost reports and explicit approvals for R1–R4 scenario generation, the 60-response ample pilot, and each 480/240/120 experiment run; provider-backed scoring remains separately gated by `--execute-paid`.
- Any further scenario-generation, evaluated-model, or scoring-provider request.

## Required offline acceptance checks

```bash
uv run pytest
uv run pre-commit run --all-files
uv run risk-comm maintenance export-schemas
uv run risk-comm maintenance validate-protocol
uv run risk-comm maintenance validate-docs
```

The project code-review workflow must run after the implementation test suite is green. No reading-list artifact is changed by this protocol update.
