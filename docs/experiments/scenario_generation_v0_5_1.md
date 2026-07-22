# V0.5.1 scenario generation and acceptance

## Inputs and ownership

The immutable researcher-owned inputs are:

- `data/inputs/scenarios/v0.5.1/scenario_generation_seeds.json`
- `data/inputs/scenarios/v0.5.1/scenario_generation_seed_schema.json`

The deployment evidence, construct criteria, and retain/refine/replace decisions for the ten families are recorded in `docs/research-plan/SCENARIO_FAMILY_AUDIT.md`.

`src/scenarios/seed_validation.py` verifies their approved byte hashes, Draft 2020-12 schema, exact CF001–CF010/50-scenario structure, two pair briefs, and absence of code-owned treatment keys.

Run the offline gate first:

```bash
uv run risk-comm maintenance validate-protocol
```

## Integrated generation

`src/scenarios/pipeline.py` requests one integrated generation response per scenario containing the visible source plus hidden facts, calculations, source-order metadata, and minimal complete response. Local code validates and assembles the candidate, then runs one combined candidate-quality review per scenario and one shared diversity review per R1-R4 batch. C1 scenarios do not receive a diversity review because they belong to different use cases. Automated revision repeats the integrated generation call with the findings and stops after two cycles; remaining failures become `manual_restructure` or `reject`.

Initial generation therefore uses 110 model calls before revisions: 50 integrated generation calls, 50 candidate-quality calls, and 10 shared R-batch diversity calls. There are no separate blueprint, source-rendering, fact-manifest, arithmetic, or minimal-response model calls.

Scenario generation is independent of the emotional-cue wording and does not require a cue-review manifest.

The default OpenRouter implementation is `src/scenarios/openrouter_backend.py`. Generation and review use different configured support models. Generate all ten C1 candidates in one lifecycle stage without creating R outputs early:

```bash
uv run risk-comm scenarios generate \
  --backend src.scenarios.openrouter_backend:create_openrouter_scenario_backend \
  --stage calibration \
  --execute-paid
```

Drafts and complete automated history are written below `data/outputs/scenario_generation/v0.5.1/`, which is ignored. No generator can publish into tracked accepted inputs.

## Deterministic construction and acceptance

- `src/scenarios/numeric_engine.py` recomputes only calculations explicitly returned in the integrated response. It uses `Decimal`, declared-order dependencies, fixed rounding, operation-arity checks, missing-operand checks, and division-by-zero checks, and requires the model-returned results to match. It does not infer which calculations are needed, validate unit compatibility, establish financial plausibility, or interpret formatted prose.
- `src/scenarios/source_rendering.py` creates canonical source A. It can derive B later, for the secondary four-use-case objective only, by pair swaps and neutral-order reversal from the identical item/value multiset.
- `src/scenarios/word_count.py` is the only word counter.
- `src/scenarios/acceptance.py` requires all final automated reviews and researcher review to pass, then publishes an immutable accepted artifact and complete history under `data/inputs/scenarios/v0.5.1/accepted/<scenario_id>/`.

### Worked arithmetic example

For a fictional cash-flow scenario, the integrated generation call might return this hidden numeric registry alongside the natural-language source:

```json
{
  "inputs": [
    {"value_id": "OLD_UTILITIES", "value": "160", "unit": "GBP/month", "source_note": "first period"},
    {"value_id": "NEW_UTILITIES", "value": "200", "unit": "GBP/month", "source_note": "latest period"}
  ],
  "calculations": [
    {
      "output_value_id": "UTILITY_INCREASE_PERCENT",
      "operation": "percentage_change",
      "operand_value_ids": ["OLD_UTILITIES", "NEW_UTILITIES"],
      "decimal_places": 1,
      "expected_unit": "percent"
    }
  ],
  "computed_values": [
    {
      "value_id": "UTILITY_INCREASE_PERCENT",
      "value": "25.0",
      "unit": "percent",
      "calculation": {
        "output_value_id": "UTILITY_INCREASE_PERCENT",
        "operation": "percentage_change",
        "operand_value_ids": ["OLD_UTILITIES", "NEW_UTILITIES"],
        "decimal_places": 1,
        "expected_unit": "percent"
      }
    }
  ]
}
```

The same response can contain the source sentence “Monthly utilities rose from £160 to £200, a 25% increase.” Code independently recomputes `(200 - 160) / 160 × 100 = 25.0` and rejects the candidate if the returned registry instead claims another result. The tested model sees only the rendered sentence, not the registry, fact units, calculation definition, source-order metadata, or minimal complete response.

This check catches inconsistent structured arithmetic, but it does not semantically prove that the prose used the registry correctly. The candidate-quality review still checks the rendered £160, £200, and 25% for consistency. If a scenario contains no derived quantity, its calculation list can be empty.

The main experiment always uses canonical source A with absent integrity. After primary scoring, `src/analysis/secondary_subset.py` selects the two use cases with the smallest and two with the largest mean initial pairwise disclosure gap. The same four families feed the later source-order and targeted-integrity studies. Order B can be derived without regeneration. Both studies are outcome-selected and reported separately.

Every generated candidate receives one researcher review through the local application. Minimal-response approval may only add approval metadata. If its content needs editing, rebuild the candidate and rerun every automated review and the researcher review. Publish one reviewed bundle with:

```bash
uv run risk-comm scenarios publish \
  --candidate data/outputs/scenario_generation/v0.5.1/CF001_C1/candidate.json \
  --automated-reviews data/outputs/scenario_generation/v0.5.1/CF001_C1/automated_reviews.jsonl \
  --revision-cycles data/outputs/scenario_generation/v0.5.1/CF001_C1/revision_cycles.jsonl \
  --researcher-reviews data/outputs/review/records/scenario_reviews.jsonl \
  --approved-minimal-response data/outputs/review/records/approved_minimal_responses/CF001_C1.json \
  --accepted-root data/inputs/scenarios/v0.5.1/accepted \
  --accepted-by <researcher_id>
```

After the ten C1 bundles exist, create the calibration checkpoint manifest used by the ample pilot:

```bash
uv run risk-comm scenarios build-manifest \
  --accepted-root data/inputs/scenarios/v0.5.1/accepted \
  --scope calibration \
  --published-by <researcher_id> \
  --output data/inputs/scenarios/v0.5.1/accepted_calibration_manifest.json
```

After all 50 immutable bundles exist, create the complete accepted-set manifest:

```bash
uv run risk-comm scenarios build-manifest \
  --accepted-root data/inputs/scenarios/v0.5.1/accepted \
  --scope complete \
  --published-by <researcher_id> \
  --output data/inputs/scenarios/v0.5.1/accepted_scenario_manifest.json
```

Calibration C1 artifacts are completed before any R1–R4 evaluation artifact is frozen.

Build the evaluated-model freeze from three exact provider-returned snapshot JSON records:

```bash
uv run risk-comm experiment freeze-models \
  --evaluated-snapshot <snapshot_1.json> \
  --evaluated-snapshot <snapshot_2.json> \
  --evaluated-snapshot <snapshot_3.json> \
  --scoring-judge-model-id <independent_judge_alias> \
  --frozen-by <researcher_id> \
  --output <evaluated_model_manifest.json>
```

During the same researcher review phase, record the cue review against the exact active wording. The `APPROVE` decision is valid only when both cues are marked natural and equivalent and none of the confounding flags is set:

```bash
uv run risk-comm experiment freeze-prompts \
  --neutral-natural \
  --worried-natural \
  --semantic-request-equivalent \
  --decision approve \
  --notes <review_notes> \
  --reviewed-by <researcher_id> \
  --output <prompt_review_manifest.json>
```

Then run the separate 320-word adequacy pilot over all 60 C1/model/cue primary combinations:

```bash
uv run risk-comm calibration run-ample-pilot \
  --accepted-root data/inputs/scenarios/v0.5.1/accepted \
  --accepted-scenario-manifest data/inputs/scenarios/v0.5.1/accepted_calibration_manifest.json \
  --evaluated-model-manifest <evaluated_model_manifest.json> \
  --prompt-review-manifest <prompt_review_manifest.json> \
  --retry-policy <pilot_retry_policy.json> \
  --records data/outputs/scenario_generation/v0.5.1/ample_pilot_records.jsonl \
  --attempts data/outputs/scenario_generation/v0.5.1/ample_pilot_attempts.jsonl \
  --cache-dir data/outputs/scenario_generation/v0.5.1/cache \
  --execute-paid
```

Every record binds the accepted C1 artifact, exact model snapshot/version, cue prompt bytes under absent integrity, seed, finish reason, token usage, and response bytes. The runner resumes identical requests and refuses model-version drift. Freeze the ten C1-derived limits before generating R1–R4:

```bash
uv run risk-comm scenarios freeze-tight-limits \
  --accepted-root data/inputs/scenarios/v0.5.1/accepted \
  --calibration-scenario-manifest data/inputs/scenarios/v0.5.1/accepted_calibration_manifest.json \
  --evaluated-model-manifest <evaluated_model_manifest.json> \
  --prompt-review-manifest <prompt_review_manifest.json> \
  --pilot-records data/outputs/scenario_generation/v0.5.1/ample_pilot_records.jsonl \
  --frozen-by <researcher_id> \
  --output <tight_limit_manifest.json>
```

Generate each use case's four held-out scenarios with its accepted C1 candidate as a hash-authenticated diversity anchor:

```bash
uv run risk-comm scenarios generate \
  --backend src.scenarios.openrouter_backend:create_openrouter_scenario_backend \
  --stage evaluation --use-case-id CF001 \
  --tight-limit-manifest <tight_limit_manifest.json> \
  --calibration-candidate data/outputs/scenario_generation/v0.5.1/CF001_C1/candidate.json \
  --execute-paid
```

After all R1–R4 review and publication gates pass, finalize their 12-word headroom checks without altering the frozen limits:

```bash
uv run risk-comm scenarios finalize-word-budgets \
  --accepted-root data/inputs/scenarios/v0.5.1/accepted \
  --accepted-scenario-manifest data/inputs/scenarios/v0.5.1/accepted_scenario_manifest.json \
  --tight-limit-manifest <tight_limit_manifest.json> \
  --frozen-by <researcher_id> \
  --output <word_budget_manifest.json>
```
