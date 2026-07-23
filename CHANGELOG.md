# Changelog

All notable changes to the active research implementation are recorded here. The project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Added the preregistered 0–1 `selective_risk_communication_score`, combining coverage, specificity, framing/reassurance, salience, and factual integrity with frozen 30/15/20/15/20 weights.
- Added V0.5.2 corrected scenario seeds, ten deterministic text-native source renderers, pair diagnostics, four cue pairs, and ten use-case-specific natural follow-ups.
- Added two-test scenario sign-flip inference, use-case-stratified scenario bootstrap intervals, cluster-aware equivalence, five-domain composite power simulation, and prespecified composite sensitivities.
- Added one-pass domain validation diagnostics, calibration-frozen gates, and the hashed failed-domain disposition contingency.
- Added separate 240-conversation `material_priority_v1` and 120-conversation `brevity_locus_v1` exploratory plans, manifests, layouts, analyses, and stable paper assets.
- Added batch-bound scenario-generation cost reports and researcher approvals that authenticate the V0.5.2 seed, model roles, backend, stage, and use-case scope before provider access.
- Added exact-span adversarial fixtures and an offline plan-to-scoring-to-analysis workflow test.

### Changed

- Retained `risk_comm_v1` as the 480-conversation primary 2×2 design while making the initial composite the confirmatory outcome for H1 budget and H2 expressed-concern effects.
- Renamed persisted emotional/worried fields to `expressed_concern`/`concerned` and moved incompatible persisted artifacts to schema 2.0.0 while retaining software release 0.1.0.
- Made cumulative scoring a secondary measure of spontaneous additional communication after a natural follow-up.
- Generalised cost reports, approvals, scoring, analysis-input joining, and experiment layouts across the primary and both exploratory studies.
- Preserved V0.5.1 unchanged and archived the predecessor research plan.

### Removed

- Removed the active repair prompt, repair metrics/UI, outcome-selected source-order execution, targeted-integrity study, repeat annotations, and H2a/H2b framing.

## [0.1.0] - 2026-07-20

### Added

- Reproducible risk-communication experiment protocol with strict Pydantic boundaries, generated JSON Schemas, lifecycle manifests, and offline validation.
- Integrated scenario generation returning visible source content, hidden facts, calculations, source-order metadata, and a minimal complete response in one model call.
- One candidate-quality review per scenario and one batch-diversity review per held-out scenario batch, with at most two revision cycles.
- Canonical source-order execution and exploratory source-order subset selection using the two smallest-gap and two largest-gap use cases.
- Unified `risk-comm` CLI for scenario, calibration, experiment, scoring, analysis, maintenance, and review workflows.
- Local Streamlit review and blinded annotation application.

### Changed

- Moved project commands from top-level scripts into organized modules under `src/cli/commands/`.
- Moved environment settings and the model catalog from `configs/` into `src/settings/`.
- Reduced `scripts/` to repository hook tooling and a compatibility entry point for cached hook commands.
- Removed implementation-era `V9` labels from active modules, tests, documentation, schemas, messages, and paths; the active implementation is now identified by package release version only.

### Removed

- Separate blueprint, source-rendering, fact-manifest, arithmetic-generation, and minimal-response model calls from scenario generation.
- Cue-review gating from scenario generation.
- Routine delayed scenario re-review; each generated scenario receives one initial researcher review.
