# V9 implementation status and lifecycle gates

## Implemented offline foundation

- V6/V0.4 documentation archived; V8 preserved unchanged; V9 active.
- V0.5.1 supplied seed/schema imported byte-for-byte and hash-validated.
- Strict immutable factor, seed, scenario, review, manifest, transcript, scoring, annotation, and analysis models.
- Unicode word counter, 12-word headroom rule, 114/120 ample gate, deterministic arithmetic and source ordering.
- Three-review/three-revision pipeline, researcher acceptance boundary, and accepted-only loader.
- Local-only six-page Streamlit review application with atomic JSONL and 14-day washout.
- Eight-cell randomised runner with exact prompt isolation, immutable retries, immediate persistence, and 1,920/3,840 count gates.
- Three condition-blind scoring contracts, exact-span validation, separate metrics, and hard reliability gates.
- Python bootstrap/Holm/power/equivalence/assets and a complete `renv` graph with synthetic `lmer`/`glmer`/fact-level `clmm` smoke fitting.
- Terminal provider failures preserved in a self-hashed missingness report; terminal scoring failures have a blinded manual-resolution importer.
- Deterministic plans are rebuilt from frozen accepted scenarios, exact evaluated snapshots, limits, prompts, and seed before preregistration and paid execution.
- Direct `uv` dependencies, strict schemas, CI, offline simulated tests, and runbooks.

## Deliberately incomplete research artifacts

No model-generated scenario, calibration output, accepted-scenario set, tight-limit/budget freeze, main transcript, automated/manual score, or confirmatory result is claimed complete by this code migration.

The next blocking gate is the structured researcher prompt/cue review followed by exact evaluated-model snapshot selection. Both must be frozen before the first paid model-generated calibration call. Main execution additionally requires the preregistration package, dry-run report, and explicit linked cost approval.

Legacy reproducibility point: commit `e6b83d2`. Historical inputs and runs remain untouched and are excluded from active V9 loaders.
