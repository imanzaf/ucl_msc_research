# Changelog

All notable changes to the active research implementation are recorded here. The project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Reduced the primary experiment and calibration designs to the four integrity-absent word-budget × emotional-cue cells.
- Moved targeted integrity to a secondary study over the same two best- and two worst-scoring scenario families selected for source-order research.
- Corrected per-model summaries to derive 160 expected conversations from the 480-conversation primary design.
- Clarified that cue review is completed during researcher review and gates calibration, not scenario generation.
- Consolidated the live research plan around the current design, including the shared secondary-subset rule, exact 192-conversation integrity and order studies, M1/M2/O1 estimands, reporting boundaries, and primary-data secondary analyses.
- Removed superseded execution language, historical implementation notes, and unspecified alternate-cue or stochastic runs from the active research plan; design history now lives in this changelog and the documentation archive.

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
