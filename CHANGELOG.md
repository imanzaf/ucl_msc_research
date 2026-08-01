# Changelog

All notable changes to the active research implementation are recorded here. The project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Added the active V3.0.0 seed snapshot with the latest definitions and queries plus ten rebuilt C1 publications using explicit comparison fields.
- Added fresh 3.0.0 scoring and annotation contracts for six response-isolated calls: binary content, typed presentation shifts, and binary
  false-claim accuracy findings. Positive findings require behavior, exact quote/offsets, and a finding-specific reason.
- Added independently resumable response-contract-fact call artifacts, eighteen provider provenances per completed bundle, per-call retry/cache behavior, and
  terminal manual resolution when any one call exhausts retries.
- Added separate 0–1 `selective_communication_score`, `presentation_style_score`, and binary `factual_inaccuracy_score` outcomes, plus code-derived
  initial, follow-up, and cumulative checkpoints.
- Added the versioned `c1_llama_2x2_v8` scoring diagnostic and a 40-bundle/720-call validation report required before the main scoring contract can freeze.
- Added a hash-bound scoring-only rerun workflow that reuses the 40 completed Llama transcripts from `c1_llama_2x2_v3` without making new
  evaluated-model calls or altering historical experiment versions.
- Added staged human annotation that validates and locks the initial response before revealing the follow-up, six-construct validation, and separate
  confirmatory/secondary paper panels.
- Added the immutable V1.0.0 seed with separately authored natural `neutral_user_query` and `concerned_user_query` strings plus one generic
  `follow_up_query` for every scenario.
- Added immutable V0.8.0 seeds with generic deployment contexts, natural initial/follow-up messages, and a compact hidden decision/evidence/generation design.
- Added balanced benefit/downside evidence for both the customer-preferred and provider-preferred options, with provider-supporting-minus-customer-supporting pair direction.
- Added exact versioned system prompts for initial generation, finding-linked revision, candidate-quality review, and R1–R4 batch-diversity review.
- Added a calibration-only twenty-request prompt review so the ample pilot and tight-limit freeze occur before R1–R4 generation without depending on the final 80-request evaluation review.
- Added two-test scenario sign-flip inference, use-case-stratified scenario bootstrap intervals, and selective-score power simulation.
- Added calibration-derived expected 95% interval half-widths for the four initial secondary H1/H2 contrasts without treating them as powered outcomes.
- Added one-pass construct validation diagnostics, calibration-frozen gates, and hashed failed-construct disposition contingencies.
- Added separate 240-conversation `material_priority_v1` and 120-conversation `brevity_locus_v1` exploratory plans, manifests, layouts, analyses, and stable paper assets.
- Added batch-bound scenario-generation cost reports and researcher approvals that authenticate the V0.8.0 seed, model roles, backend, stage, and use-case scope before provider access.
- Added a separate hash-linked ample-pilot cost report and researcher approval that bind all 60 exact provider requests to the prompt package, seed, accepted C1 set, frozen model snapshots, reviewed prompts, retry policy, and pricing assumptions, with persisted success/failure attempts.
- Added exact-span adversarial fixtures and an offline plan-to-scoring-to-analysis workflow test.

### Changed

- Reclassified the CF001, CF002, and CF010 deploying entities as retail banks and made CF010's external SEPA route another retail-bank option.
- Simplified scenario authoring to one initial generation call, unrestricted parent-linked manual revisions, and researcher-selected publication.
  Automated review, regeneration, acceptance decisions, model/prompt freeze checks, pilots, and complete-batch requirements no longer gate this pipeline.
- Required R1/R2 generation examples to resolve exclusively from the matching currently published C1 record, independent of generation-run location.
- Reduced each R1/R2 example to the two published C1 option-information records; C1 deployment, decision, option names, ownership mechanism,
  comparison relationship, and queries are no longer rendered.
- Made initial selective communication the sole primary outcome: equal-weight coverage and specificity asymmetry. Presentation style and factual
  inaccuracy are prespecified secondary outcomes and no longer enter the headline score.
- Made fact, predefined-marker, and false-claim decisions binary. Every marker's stable ID and plain text are passed to its fact-level content calls.
- Replaced fact-level framing labels with span-level behavior enums (`certainty_shift`, `magnitude_shift`, `condition_shift`, `consequence_shift`,
  `qualification_shift`) plus weakening/strengthening direction. Ordering and emphasis are derived from exact content evidence.
- Changed content and presentation scoring to four independent fact-level calls per response. Each presentation fact may return zero or more typed
  shifts; accuracy remains one response-level call over all supplied facts.
- Tightened judge grounding so evidence quotes are contiguous response substrings, accuracy evidence references supplied fact IDs, and alternative
  recommendations cannot be misclassified as weakening an omitted fact. Exact visible propositions are mapped deterministically to their fact IDs,
  high-overlap quote edge errors are trimmed to the stored verbatim response span, marker evidence expands only to the smallest nearby approved
  exact value, unsupported marker-positive decisions become binary absent, forbidden marker IDs are cleared from fact evidence, and presentation
  findings for content-absent facts are excluded before metric calculation.
- Updated metrics and analysis-row schemas to 4.0.0, redesigned scoring/result/annotation/bundle schemas to 3.0.0, and regenerated active JSON Schemas.
- Updated analysis-assumption and power-assumption schemas to 4.0.0 and the power-report schema to 3.0.0 for secondary precision inputs and outputs.
- Restricted confirmatory inference to H1/H2 on initial selective communication with Holm adjustment. Initial secondary outcomes and follow-up or
  cumulative checkpoints receive paired estimates and scenario-bootstrap intervals without confirmatory p-values.
- Activated generation protocol V1.0.5 and candidate/accepted schema 6.0.0. Generation now returns exact quantitative specificity markers with
  each fact, and researcher review persists editable fact text, marker lists, and per-fact notes through acceptance or regeneration.
- Activated generation protocol V1.0.10 and candidate/accepted schema 9.0.0. The provider output is now the canonical persisted two-option structure;
  stable fact, marker, pair, polarity, and owner-alignment fields are derived deterministically for review, rendering, scoring, and analysis.
- Reframed fact matching as two coherent cross-option customer trade-offs, allowing facts on the same dimension to have opposite polarity instead
  of forcing the favourable and adverse slots to form same-dimension pairs.
- Replaced reusable cue prefixes and cue-template assignment with direct seed-authored condition queries in prompt compilation, review manifests,
  factor-isolation validation, analysis inputs, and power assumptions.
- Reduced the hidden decision mechanism to `owner_supporting_option` and `owner_benefit_mechanism`; the other option is now an alternative with no
  assumed customer-optimal status. Directional facts and diagnostics are owner-supporting versus owner-countervailing.
- Activated seed and generation protocol V1.0.0, prompt package V9, candidate/accepted schema 5.0.0, prompt-review schema 3.0.0, and conversation
  metrics, analysis-input, and power-assumption schema 3.0.0.
- Retained `risk_comm_v1` as the primary 2×2 design while making initial selective communication the confirmatory outcome for H1 budget and H2 expressed-concern effects.
- Renamed persisted emotional/worried fields to `expressed_concern`/`concerned` and moved incompatible persisted artifacts to schema 2.0.0 while retaining software release 0.1.0.
- Retained the evaluated-model prompt package while binding it to the V0.8.0 role/entity/task/Guidance contract, seed-owned customer turns, and fixed evidence packet.
- Reworked the scenario-generation prompt into a lean Context/Task/Output contract and reduced its payload to entity type, general task, initial question, hidden design, scenario brief, and evidence format.
- Required generated evidence packets to resemble domain-native artifacts naturally retrievable in deployment rather than natural-sounding benchmark narratives.
- Replaced legacy bespoke role/task context with explicit broad `deployment_context.role` and `deployment_context.task` fields, while removing named model-owner, response-genre, and redundant context fields.
- Added runtime rejection of simulation/research framing and hidden-design leakage in evaluated prompt content.
- Retained the three V1 experiment identities and moved incompatible generated/accepted scenario artifacts to schema 3.0.0 because the redesign occurred before any accepted scenario artifact, frozen experiment manifest, paid run, result, or paper asset existed.
- Made follow-up-only and code-derived cumulative scoring prespecified secondary checkpoints after a natural follow-up.
- Generalised cost reports, approvals, scoring, analysis-input joining, and experiment layouts across the primary and both exploratory studies.
- Preserved V0.5.1–V0.7.0 unchanged, archived their scenario-generation runbooks, and made V0.8.0 active.

### Removed

- Removed the five-domain weighted composite, partial fact/specificity credit, aggregate fact framing, response-communication contract, generic-risk
  disclaimer and disclaimer-washing classes, acknowledgement/reassurance/refusal/signposting fields, and claim counts/severity ladders.
- Removed active equal-domain, leave-one-domain-out, spontaneous-change, unused-budget/ratio, per-100-word, character-share, first-evidence, and
  duplicate salience diagnostics and their legacy code, scripts, schemas, and workflow documentation.
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
