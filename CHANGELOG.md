# Changelog

All notable changes to the active research implementation are recorded here. The project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Added the preregistered 0–1 `selective_risk_communication_score`, combining coverage, specificity, framing/reassurance, salience, and factual integrity with frozen 30/15/20/15/20 weights.
- Added immutable V0.8.0 seeds with generic deployment contexts, natural initial/follow-up messages, and a compact hidden decision/evidence/generation design.
- Added balanced benefit/downside evidence for both the customer-preferred and provider-preferred options, with provider-supporting-minus-customer-supporting pair direction.
- Added exact versioned system prompts for initial generation, finding-linked revision, candidate-quality review, and R1–R4 batch-diversity review.
- Added a calibration-only twenty-request prompt review so the ample pilot and tight-limit freeze occur before R1–R4 generation without depending on the final 80-request evaluation review.
- Added two-test scenario sign-flip inference, use-case-stratified scenario bootstrap intervals, cluster-aware equivalence, five-domain composite power simulation, and prespecified composite sensitivities.
- Added one-pass domain validation diagnostics, calibration-frozen gates, and the hashed failed-domain disposition contingency.
- Added separate 240-conversation `material_priority_v1` and 120-conversation `brevity_locus_v1` exploratory plans, manifests, layouts, analyses, and stable paper assets.
- Added batch-bound scenario-generation cost reports and researcher approvals that authenticate the V0.8.0 seed, model roles, backend, stage, and use-case scope before provider access.
- Added a separate hash-linked ample-pilot cost report and researcher approval that bind all 60 exact provider requests to the prompt package, seed, accepted C1 set, frozen model snapshots, reviewed prompts, retry policy, and pricing assumptions, with persisted success/failure attempts.
- Added exact-span adversarial fixtures and an offline plan-to-scoring-to-analysis workflow test.

### Changed

- Retained `risk_comm_v1` as the 480-conversation primary 2×2 design while making the initial composite the confirmatory outcome for H1 budget and H2 expressed-concern effects.
- Renamed persisted emotional/worried fields to `expressed_concern`/`concerned` and moved incompatible persisted artifacts to schema 2.0.0 while retaining software release 0.1.0.
- Retained the evaluated-model prompt package while binding it to the V0.8.0 role/entity/task/Guidance contract, seed-owned customer turns, and fixed evidence packet.
- Reworked the scenario-generation prompt into a lean Context/Task/Output contract and reduced its payload to entity type, general task, initial question, hidden design, scenario brief, and evidence format.
- Required generated evidence packets to resemble domain-native artifacts naturally retrievable in deployment rather than natural-sounding benchmark narratives.
- Replaced legacy bespoke role/task context with explicit broad `deployment_context.role` and `deployment_context.task` fields, while removing named model-owner, response-genre, and redundant context fields.
- Added runtime rejection of simulation/research framing and hidden-design leakage in evaluated prompt content.
- Retained the three V1 experiment identities and moved incompatible generated/accepted scenario artifacts to schema 3.0.0 because the redesign occurred before any accepted scenario artifact, frozen experiment manifest, paid run, result, or paper asset existed.
- Made cumulative scoring a secondary measure of spontaneous additional communication after a natural follow-up.
- Generalised cost reports, approvals, scoring, analysis-input joining, and experiment layouts across the primary and both exploratory studies.
- Preserved V0.5.1–V0.7.0 unchanged, archived their scenario-generation runbooks, and made V0.8.0 active.

### Removed

- Removed the active repair prompt, repair metrics/UI, all source-order plans/fields/execution, targeted-integrity study, repeat annotations, and H2a/H2b framing.

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
