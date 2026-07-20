# UCL MSc Research — risk communication study

This repository contains the dissertation and reproducible experiment code for a controlled study of how word-budget pressure and a minimal worried cue affect material financial risk communication by language models.

The active protocol is the [Research Plan](docs/research-plan/RESEARCH_PLAN.md). It replaces the archived V6/V0.4 implementation with a 2 × 2 primary study of word budget × emotional cue and a matched four-cell integrity-mitigation rerun. The target `risk_comm_v1` design is 40 held-out scenarios × 3 evaluated models × canonical source order A × 8 cells: 960 conversations and 1,920 agent responses. Source-order sensitivity is a later exploratory objective on the two smallest- and two largest-gap use cases.

## Current gate

The current code, strict schemas, offline validators, review application, runner, scoring contracts, analysis code, and tests are implemented. The supplied V0.5.1 seed and schema are committed byte-for-byte.

Paid generation and evaluation are deliberately not complete. Scenario generation does not require cue approval. The experiment prompts and exactly three evaluated model snapshots must be frozen before the ample-limit pilot. Accepted scenarios, the 120-output pilot, budget manifest, rubric/judge validation, preregistration package, dry-run cost report, and explicit paid-execution approval remain lifecycle gates.

## Active structure

- `data/inputs/scenarios/v0.5.1/` — immutable supplied seed/schema and, after review, tracked accepted artifacts.
- `src/data_models/` — strict Pydantic v2 protocol boundaries and frozen manifests.
- `src/settings/` — environment settings and the packaged model catalog.
- `src/cli/` — the unified `risk-comm` CLI and grouped workflow commands.
- `src/scenarios/` — seed validation, one-call integrated generation, Unicode word counting, narrow arithmetic validation, review, and acceptance.
- `src/experiments/` — model catalog, eight-cell runner, condition-blind scoring pipeline, and paper assets.
- `src/scoring/` — exact-span validation, separate metrics, and scoring-reliability gates.
- `src/analysis/` and `analysis/r/` — Python estimands/bootstrap/power/equivalence and locked R robustness models.
- `src/review_app.py` — local-only Streamlit scenario and conversation review workflows.
- `schemas/` — generated JSON Schemas validated in CI.
- `docs/experiments/` — exact commands, inputs, outputs, and protocol runbooks.
- `scripts/hooks/` — repository automation that is not part of the research package.
- `data/outputs/experiments/risk_comm_v1/` — ignored config, results, cache, logs, assets, and checkpoints.

V6/V0.4 documentation is archived under `docs/archive/v6_v0_4/`. The original external V8 plan is archived unchanged under `docs/archive/external-review/`. Commit `e6b83d2` is the legacy V6 reproducibility point; historical data remain committed but cannot be loaded by current accepted-only paths. Release history is recorded in [CHANGELOG.md](CHANGELOG.md).

## Offline validation

```bash
uv run risk-comm maintenance export-schemas
uv run risk-comm maintenance validate-protocol
uv run pytest
uv run mypy scripts src
uv run pre-commit run --all-files
```

These commands make no paid API calls. CI enforces `CI_PAID_API_CALLS_DISABLED=1` inside the OpenRouter client; its R job restores `analysis/r/renv.lock` and runs a synthetic mixed-model smoke fit without any model API.

## Review application

```bash
uv run risk-comm review launch --server-address 127.0.0.1
```

The application only reads generated candidate scenarios or condition-blind conversation artifacts and atomically writes schema-validated JSON/JSONL. It has no generation, execution, scoring, or API controls. Each scenario receives one researcher review. Conversation-annotation repeats remain locked for 14 days and never show previous labels; only reviewed candidates can later be published as accepted inputs.

## Experiment lifecycle

1. Validate the immutable scenario seed; scenario generation does not depend on cue approval.
2. Generate, review once, and publish the ten C1 scenarios.
3. Freeze the experiment prompts and three evaluated snapshots, run the 120-output pilot, and freeze the C1-derived tight limits.
4. Generate R1–R4 in C1-anchored batches; publish all 50 accepted scenarios and finalize headroom without changing a limit.
5. Run the 240-conversation calibration matrix and freeze rubrics, exact judge snapshots, effects, power assumptions, retries, and analysis inputs.
6. Rebuild and authenticate the 960-unit canonical-order plan from frozen scenarios/models/budgets/prompts, then preregister it.
7. Produce the dry-run call/token/cost report and obtain a linked approval before paid main execution.
8. Preserve exhausted provider calls as reasoned missingness, manually resolve persistent blind-scoring failures, validate the 160/40 human sample, and run gated analysis.

Exact commands and file contracts are in [the risk_comm_v1 runbook](docs/experiments/risk_comm_v1.md).

## Reproducibility rules

- Python 3.11 is pinned; use `uv run` and `uv add`, never `pip`.
- Structured boundaries reject unknown fields and include schema versions.
- Primary decoding is temperature 0; retries reuse identical request bytes.
- No persona or user simulator is active. The study makes no user-harm inference.
- Coverage, specificity, framing, salience, reassurance, false claims, and repair remain separate; there is no composite score.
- Raw outputs stay under `data/outputs/`; only accepted V0.5.1 scenarios, complete review history, hashes, and manifests enter tracked inputs.
