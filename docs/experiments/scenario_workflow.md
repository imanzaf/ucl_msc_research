# Scenario Workflow

All active scenario operations use `srcv2/scenarios/` through `risk-comm-v2`. The immutable source is
`data/inputs/scenarios/v4.0.0.zip`; corrected seed inputs and their provenance record are in `data/inputs/scenarios/v4.0.1/`.

## 1. Verify and import the supplied package

```bash
uv run risk-comm-v2 scenarios import-package \
  --source /Users/iman/Downloads/scenario_generation_v4.0.0_package.zip
```

The importer in `srcv2/scenarios/import_package.py` verifies the expected SHA-256, preserves the archive, balances option presentation order, and
replaces bundled required-specificity declarations with one atomic anchor. It refuses a checksum mismatch or a conflicting preserved archive.

## 2. Audit the corrected corpus

```bash
uv run risk-comm-v2 scenarios validate
```

The report at `data/inputs/scenarios/v4.0.1/corpus_audit.json` must show: six domains; 30 scenarios; 180 briefs; 90 pairs; 90 owner-supporting and 90
countervailing briefs; 90 favourable and 90 adverse briefs; 15 scenarios in each option-order condition; and eleven ownership-eligible scenarios.

## 3. Build controlled inputs

```bash
uv run risk-comm-v2 scenarios build-generation-requests
```

This command writes 30 one-shot generation requests.

## 4. Generate facts once

Generation uses GPT-5.4 through the OpenAI endpoint on OpenRouter, with fallback disabled. Price the exact hash-bound request batch first:

```bash
uv run risk-comm-v2 scenarios estimate-generation-cost
```

After the researcher approves a bounded amount, record that approval and run the resumable workflow:

```bash
uv run risk-comm-v2 scenarios approve-generation \
  --approved-max-cost 1.25 \
  --approved-by "Researcher" \
  --note "Approved GPT-5.4 fact generation through the pinned OpenAI endpoint." \
  --confirm-paid-generation
uv run risk-comm-v2 scenarios run-generation
```

The runner in `srcv2/scenarios/execution.py` uses strict JSON-schema output, reasoning effort `none`, temperature 0, seed 7, and a 2,048-token
per-request ceiling. Each record in `data/inputs/scenarios/v4.0.1/generation_requests.jsonl` may produce one semantic generation only. A malformed
semantic response is retained for review and is not replaced. Provider retries are allowed only when no semantic response was received. Config,
approval, preflight, raw records, caches, and logs are stored under
`data/outputs/scenario_generation/v4.0.1/scenario_fact_generation_v1/`; valid visible outputs are written to
`data/inputs/scenarios/v4.0.1/generated_outputs.jsonl`.

The returned facts must validate against accepted-scenario schema `10.0.0` in `schemas_v2/accepted_scenario.schema.json`. Arithmetic is checked in
code wherever the stated terms determine an exact value.

After all 30 semantic outputs have been retained, join them to the frozen hidden metadata for manual audit:

```bash
uv run risk-comm-v2 scenarios assemble-generated \
  --generated-outputs data/inputs/scenarios/v4.0.1/generated_outputs.jsonl
```

This rejects missing, duplicate, renamed, re-paired, re-assigned, or re-anchored fact slots.

The manual audit is recorded in `data/inputs/scenarios/v4.0.1/manual_review_audit.json`. If corrections are required, bind the researcher's approval
to the exact seed set, generated-output set, request batch, audit, and individual replacements before applying them:

```bash
uv run risk-comm-v2 scenarios approve-curation \
  --approved-by "Researcher" \
  --note "Approved the corrections documented in manual_review_audit.json." \
  --confirm-researcher-curation
uv run risk-comm-v2 scenarios apply-curation
uv run risk-comm-v2 scenarios validate \
  --seed-set data/inputs/scenarios/v4.0.1/curated_scenario_generation_seeds.json \
  --report data/inputs/scenarios/v4.0.1/curated_corpus_audit.json
```

The approval is stored at `data/inputs/scenarios/v4.0.1/manual_revisions/corpus_curation_approval.json`. Application preserves
`scenario_generation_seeds.json`, `generation_requests.jsonl`, `generated_outputs.jsonl`, and the provider caches byte-for-byte. It writes the
approved copies to `curated_scenario_generation_seeds.json` and `curated_generated_outputs.jsonl`, then rebuilds `pending_scenarios.jsonl` from
those copies while retaining the original request hashes. Arithmetic gates are rerun during assembly, and `curated_corpus_audit.json` records the
final structural audit.

## 5. Researcher disposition and publication

Each curated scenario receives exactly one accept-or-revise record defined in `srcv2/scenarios/review.py`. A revise disposition contains explicit
instructions; an accepted disposition contains none. Publication fails unless every scenario has exactly one accepted review. There is no separate
scenario pilot.

Review status is read-only:

```bash
uv run risk-comm-v2 review scenario-status \
  --reviews data/inputs/scenarios/v4.0.1/reviews.jsonl
```

Publish only after all 30 dispositions are accepted:

```bash
uv run risk-comm-v2 review publish-scenarios \
  --scenarios data/inputs/scenarios/v4.0.1/pending_scenarios.jsonl \
  --reviews data/inputs/scenarios/v4.0.1/reviews.jsonl \
  --output data/inputs/scenarios/v4.0.1/accepted_scenarios.jsonl
```

Only accepted scenario text is rendered to evaluated models. Hidden direction, ownership, institutional benefit, materiality, pair-matching, and
mutual-exclusivity fields are joined later for scoring and analysis.

## 6. Approve natural queries and republish

Each record in `data/inputs/scenarios/v4.0.1/query_families.jsonl` contains six scenario-specific queries: neutral, anxious, and frustrated wording
in short and long forms. The queries do not assume that the customer knows there are exactly two options. Bind approval to the accepted corpus and
the exact authored query content, then republish:

```bash
uv run risk-comm-v2 scenarios approve-query-protocol \
  --approved-by "Researcher" \
  --note "Approved the natural affect-by-length query families." \
  --confirm-query-protocol
uv run risk-comm-v2 scenarios apply-query-protocol
```

The approval is stored at `data/inputs/scenarios/v4.0.1/manual_revisions/query_protocol_approval.json`. Application writes 180 variants to
`query_variants.jsonl` and updates only each accepted scenario's `query_stem` to its neutral short form. Fact text, hidden metadata, generation
request hashes, generated-output hashes, and accepted review records are preserved.

## 7. Approve seed-owned prompt contexts

The six natural deployment contexts are declared in `prompt_contexts.json`. Each contains a use-case role, the existing fictional employer, a
plain-language task, and one short authority-limit sentence. Apply them to a final active seed and the accepted scenarios:

```bash
uv run risk-comm-v2 scenarios approve-prompt-protocol \
  --approved-by "Researcher" \
  --note "Approved the seed-owned evaluated-prompt contexts." \
  --confirm-prompt-protocol
uv run risk-comm-v2 scenarios apply-prompt-protocol
```

The resulting `final_scenario_generation_seeds.json` is the active planning seed. The preserved source generation seed, request hashes, generated
facts, hidden fact metadata, and accepted review records are not changed. Evaluated prompts exclude decision context, research-facing language,
visible option coordinates, and the redundant user-state task.
