# Implementation status

**Active protocol:** selective risk communication under word-budget pressure and expressed concern

**Software:** 0.1.0

**Seed:** V0.11.0 (V0.5.1–V0.10.0 preserved)

**Generated/accepted scenario artifact schema:** 4.1.0

The V0.11.0 task-family seed, V0.10.1 option-information generation contract, manual specificity-marker review flow, and downstream scoring linkage
are implemented and tested. Prior candidates are superseded and cannot be published through the active V0.11 paths. No V0.11 candidate has
researcher acceptance, and no V1 experiment output or accepted scenario artifact exists.

The runtime supports only seed V0.11.0 and generated/accepted schema 4.1.0. Historical seeds and archived runbooks remain as provenance, but their Pydantic models, source
renderers, numeric engine, validation branches, schemas, and tests have been removed.

## Implemented offline

- Five-domain confirmatory composite with exact frozen weights, conditional applicability, signed/reverse pair gaps, and exact-span distortion exclusivity.
- Initial and cumulative scoring, with cumulative-minus-initial labelled spontaneous additional communication.
- Four cue pairs, R1–R2/C1 mappings, exact alternative-phrase rejection, separate 20-request C1 and 40-request evaluation review manifests, and persisted `expressed_concern` labels.
- Seed-owned natural initial/follow-up customer messages and removal of the active explicit risk-repair prompt/UI.
- Immutable V0.11.0 task-family seed with three distinct decisions per family and separate hidden ownership mappings.
- Source generation returns one neutral operating description, one favourable fact, and one adverse fact per option. Only the four directional
  facts enter scoring; there is no evidence packet or fixed neutral-fact inventory, and numeric registries and generated titles, headings, labels,
  reference responses, and specificity fields are absent.
- Seed/code-owned presentation orders and customer-supporting option IDs, each counterbalanced 15/15 overall and 5/5 within C1.
- Researcher review optionally selects zero to three exact fact-linked specificity phrases per fact; unmarked facts have no specificity score.
- Budget calibration counts and hashes the four canonical facts directly, with no minimal-response review or approval workflow.
- Explicit deployment role/entity/general-task context, action-only authority limits, and natural initial/follow-up messages, separated from one
  compact hidden decision/evidence/generation design. The shared factuality/plain-language paragraph and inactive integrity-treatment field are absent.
- Balanced benefit/downside facts for both options, with code-owned provider-supporting versus customer-supporting scoring direction.
- Direct deterministic rendering of the four accepted propositions; presentation order is controlled but not an experimental factor.
- One semantic review per C1 and one combined semantic/diversity review per R1–R2 batch, with one automated revision round and deterministic structural validation.
- Seed-version output roots containing fresh UTC-stamped logical runs, timestamped per-command invocation records and provider logs, scenario-scoped
  artifacts, explicit `--run-id` continuation, pipeline failure records, prompt-hash-aware review invalidation, and archived superseded artifacts.
  Exact scenario selection permits C1, R1, and R2 to be invoked separately while preserving the required complete-family R review.
- Human-readable evaluated-context, option-information, and hidden-design panels plus compact blinded pair diagnostics. Five concise criteria guide
  one researcher `accept` or `revise` decision without separate checkbox fields or automatic artifact thresholds.
- Descriptive budget, length, coverage-rate, first-alignment, acknowledgement, alignment-allocation, option × polarity coverage, and disclaimer metrics.
- Two-test scenario sign-flip inference, stratified scenario bootstrap, cluster-aware equivalence intervals, complete-design power simulation, and composite sensitivities.
- Exactly 80 calibration and 160 evaluation annotations, each once.
- Domain validation diagnostics plus hashed blinded validation-disposition manifest and proportional renormalisation logic.
- Separate 240/120/60 primary/material-priority/brevity-locus run-plan builders and output layouts.
- Stable exploratory paper-asset generators.

## Still gated

- Fresh paid generation and researcher acceptance of ten V0.11.0 C1 scenarios, all twenty C1 rendered requests, and all 40 held-out requests.
- Canonical model freeze, hash-linked ample pilot with a complete success/failure attempt audit, tight-limit and final word-budget freezes, scoring calibration, domain-gate freeze, and preregistration hashes.
- Scenario generation runs directly and retains provider-reported token usage and costs in per-call audit records. The 60-response ample pilot and
  each 240/120/60 experiment run retain their batch-bound dry-run cost reports and explicit approvals; provider-backed scoring remains separately
  gated by `--execute-paid`.
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
