# Scenario authoring workflow

Scenario authoring is a deliberately separate pipeline from evaluated-model runs, prompt freezes, pilots, word limits, scoring, and analysis.

The workflow has only three actions:

1. generate an initial candidate;
2. edit it and save a new version as often as needed;
3. publish whichever current scenario versions the researcher chooses.

There are no automated-review, regeneration, researcher-decision, complete-batch, pilot, model-freeze, or rerun-review gates in this authoring path.
Hashes and revision records provide provenance only; they do not prevent edits or publication.

## Active inputs

The active scenario set is V3.0.0. It snapshots the latest V2.1.0 definitions and queries and contains newly published C1 bundles in the explicit
comparison-relationship form.

- definitions: `data/inputs/scenarios/v3.0.0/scenario_generation_seeds.json`
- definition schema: `data/inputs/scenarios/v3.0.0/scenario_generation_seed_schema.json`
- customer queries: `data/inputs/scenarios/v3.0.0/scenario_customer_queries.json`
- query schema: `data/inputs/scenarios/v3.0.0/scenario_customer_queries_schema.json`
- definitions SHA-256: `e5742071af91bf078c6405b2bbe64b868f61d2f145ab7402f3e604bf2201af83`
- definition-schema SHA-256: `ebbdaf983b6ad5c10ed6f9b09b44a5ff7a5c1ef4a4c62ebecd33caa52a8d9ab3`
- queries SHA-256: `647fc98ffb7bb1f3759d9e36f20353a5e37b41b78badf04fb81344963fb17604`
- query-schema SHA-256: `107d9b2b62549e1e93f7a0baca2d1d6dfb5595b0207b04f25bb49379e2a4bead`
- generation protocol: V1.1.1

The two `_schema.json` files are frozen, machine-readable descriptions of the definition and query JSON shapes. They let repository tools validate
required fields, types, enums, and scenario counts without executing Python, and their hashes identify the exact input contract used by a run.
They are structural validation and provenance files, not researcher-review or publication gates. The authoritative implementation models remain in
`src/data_models/scenarios.py`; the schemas are generated from those models and stored beside the seed so each version is self-contained.

The initial generation prompt receives no customer query. R1/R2 generation searches the published records for the matching C1 and includes only
its two option-information records as a style, detail, and output-structure example. The example excludes C1 deployment, decision, option names,
ownership mechanism, comparison relationship, and queries. Draft C1 candidates from the current or another run are never used. R1 always compares
two options from the same provider; R2 compares the current provider with one external option.

Relevant source: `src/cli/commands/scenarios/generate.py`, `src/scenarios/pipeline.py`, `src/scenarios/openrouter_backend.py`, and
`src/prompts/templates/scenario_generation.jinja2`.

## 1. Generate initial candidates

Generate all ten C1 candidates:

```bash
uv run risk-comm scenarios generate \
  --backend src.scenarios.openrouter_backend:create_openrouter_scenario_backend \
  --stage calibration \
  --run-id scenario_set_v1
```

Generate all twenty R candidates:

```bash
uv run risk-comm scenarios generate \
  --backend src.scenarios.openrouter_backend:create_openrouter_scenario_backend \
  --stage evaluation \
  --run-id scenario_set_v1
```

Every use case selected for R generation must first have its C1 published under
`data/inputs/scenarios/v3.0.0/accepted/<use-case-id>_C1/accepted_scenario.json`. The C1 may have been produced by any earlier run.

Or generate both R candidates for one use case:

```bash
uv run risk-comm scenarios generate \
  --backend src.scenarios.openrouter_backend:create_openrouter_scenario_backend \
  --stage evaluation \
  --use-case-id CF001 \
  --run-id scenario_set_v1
```

Use `--scenario-id CF001_R1` to generate one exact scenario. Repeating a completed selection is safe: the command reuses the candidate already in
the run. Generation makes one paid generator call per missing candidate and does not call an automated reviewer or revision model.

Each run lives at:

```text
data/outputs/scenario_generation/v3.0.0/<run-id>/
├── run_config.json
├── revision_history/
│   └── <scenario-id>.jsonl
└── <timestamp>/
    ├── invocation_config.json
    └── scenarios/<scenario-id>/
        ├── candidate.json
        └── revision_record.json  # revised versions only
```

The newest timestamped candidate for a scenario is its current version.

## 2. Edit and save versions in the UI

Launch the editor for a named run:

```bash
uv run risk-comm review launch --run-id scenario_set_v1
```

The editor keeps every current scenario selectable. It permits direct changes to:

- assistant task and authority limits;
- neutral, concerned, and follow-up customer messages;
- decision type and owner-benefit mechanism;
- option names and neutral descriptions;
- all four facts and their optional quantitative markers.

`Save revised version` validates the edited candidate, writes it in a new timestamped round, links it to the parent candidate hash, and appends one
simple record to `revision_history/<scenario-id>.jsonl`. It makes no provider call. `Publish this version` saves first when fields changed, then
publishes only that scenario.

Relevant source: `src/review_app.py` and `src/scenarios/revisions.py`.

## Edit JSON directly

You may instead edit a current `candidate.json` file directly, leaving its existing `candidate_sha256` value in place, then normalise and save it as
a new version:

```bash
uv run risk-comm scenarios save-revision \
  --run-id scenario_set_v1 \
  --file data/outputs/scenario_generation/v3.0.0/scenario_set_v1/<timestamp>/scenarios/CF001_R1/candidate.json \
  --edited-by imanzafar \
  --notes "Clarified the customer query and two facts."
```

The command replaces the edited file with its newly validated, re-hashed representation and also writes the new current version in a timestamped
round. A full candidate copied elsewhere may be passed with `--file` too; in that case its edited sections are applied to the current parent.

Relevant source: `src/cli/commands/scenarios/save_revision.py`.

## 3. Publish selected versions

Publish one or several named scenarios:

```bash
uv run risk-comm scenarios publish \
  --run-id scenario_set_v1 \
  --scenario-id CF001_R1 \
  --scenario-id CF001_R2 \
  --published-by imanzafar
```

Or publish every current candidate in the run:

```bash
uv run risk-comm scenarios publish \
  --run-id scenario_set_v1 \
  --all-current \
  --published-by imanzafar
```

Publication does not require automated reviews, a saved accept decision, seed-field equality, or a complete batch. Existing publications are
archived under `data/inputs/scenarios/v3.0.0/accepted/_history/` before a replacement becomes current. When the published directory contains all ten
C1 scenarios or all thirty scenarios, the corresponding downstream set manifest is refreshed automatically. Those manifests are inputs to the
separate evaluated-model pipeline; their downstream completeness requirements do not gate scenario editing or individual publication.

Relevant source: `src/cli/commands/scenarios/publish.py`, `src/scenarios/acceptance.py`, and
`src/cli/commands/scenarios/build_manifest.py`.
