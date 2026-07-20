# V0.5.1 scenario generation and acceptance

## Inputs and ownership

The immutable researcher-owned inputs are:

- `data/inputs/scenarios/v0.5.1/scenario_generation_seeds.json`
- `data/inputs/scenarios/v0.5.1/scenario_generation_seed_schema.json`

`src/scenarios/seed_validation.py` verifies their approved byte hashes, Draft 2020-12 schema, exact CF001–CF010/50-scenario structure, two pair briefs, and absence of code-owned treatment keys.

Run the offline gate first:

```bash
uv run python scripts/validate_v9_protocol.py
```

## Staged generation

`src/scenarios/pipeline.py` executes typed blueprint generation, deterministic arithmetic, source/fact/minimal-response construction, separate construct and finance reviews, lifecycle-stage batch-diversity review, controlled field-level revision, full dependency rebuilding, and all-review reruns. Automated revision stops after three cycles; remaining failures become `manual_restructure` or `reject`.

Build the self-review record first. Approval is rejected unless both exact active cues are natural, semantically matched, and unconfounded:

```bash
uv run python scripts/build_prompt_review_manifest.py \
  --neutral-natural --worried-natural --semantic-request-equivalent \
  --decision approve --notes <notes> --reviewed-by <researcher_id> \
  --output <prompt_review_manifest.json>
```

The default OpenRouter implementation is `src/scenarios/openrouter_backend.py`. Generation and review use different configured support models. Generate all ten C1 candidates together so batch diversity is reviewed without creating R outputs early:

```bash
uv run python scripts/run_scenario_generation.py \
  --backend src.scenarios.openrouter_backend:create_openrouter_scenario_backend \
  --stage calibration \
  --prompt-review-manifest <prompt_review_manifest.json> \
  --execute-paid
```

Drafts and complete automated history are written below `data/outputs/scenario_generation/v0.5.1/`, which is ignored. No generator can publish into tracked accepted inputs.

## Deterministic construction and acceptance

- `src/scenarios/numeric_engine.py` calculates registered values with `Decimal`.
- `src/scenarios/source_rendering.py` creates source A and derives B by pair swaps and neutral-order reversal from the identical item/value multiset.
- `src/scenarios/word_count.py` is the only word counter.
- `src/scenarios/acceptance.py` requires all final automated reviews and researcher review to pass, then publishes an immutable accepted artifact and complete history under `data/inputs/scenarios/v0.5.1/accepted/<scenario_id>/`.

Every generated candidate must receive an initial and delayed repeat review through the local application; disagreements require a separate resolution. Minimal-response approval may only add approval metadata. If its content needs editing, rebuild the candidate and rerun every automated and researcher review. Publish one reviewed bundle with:

```bash
uv run python scripts/publish_accepted_scenario.py \
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
uv run python scripts/build_accepted_scenario_manifest.py \
  --accepted-root data/inputs/scenarios/v0.5.1/accepted \
  --scope calibration \
  --published-by <researcher_id> \
  --output data/inputs/scenarios/v0.5.1/accepted_calibration_manifest.json
```

After all 50 immutable bundles exist, create the complete accepted-set manifest:

```bash
uv run python scripts/build_accepted_scenario_manifest.py \
  --accepted-root data/inputs/scenarios/v0.5.1/accepted \
  --scope complete \
  --published-by <researcher_id> \
  --output data/inputs/scenarios/v0.5.1/accepted_scenario_manifest.json
```

Calibration C1 artifacts are completed before any R1–R4 evaluation artifact is frozen.

Build the evaluated-model freeze from three exact provider-returned snapshot JSON records:

```bash
uv run python scripts/build_evaluated_model_manifest.py \
  --evaluated-snapshot <snapshot_1.json> \
  --evaluated-snapshot <snapshot_2.json> \
  --evaluated-snapshot <snapshot_3.json> \
  --scoring-judge-model-id <independent_judge_alias> \
  --frozen-by <researcher_id> \
  --output <evaluated_model_manifest.json>
```

Then run the separate 320-word adequacy pilot over all 120 C1/model/cue/integrity combinations:

```bash
uv run python scripts/run_ample_pilot.py \
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

Every record binds the accepted C1 artifact, exact model snapshot/version, cue/integrity prompt bytes, seed, finish reason, token usage, and response bytes. The runner resumes identical requests and refuses model-version drift. Freeze the ten C1-derived limits before generating R1–R4:

```bash
uv run python scripts/build_tight_limit_manifest.py \
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
uv run python scripts/run_scenario_generation.py \
  --backend src.scenarios.openrouter_backend:create_openrouter_scenario_backend \
  --stage evaluation --use-case-id CF001 \
  --prompt-review-manifest <prompt_review_manifest.json> \
  --tight-limit-manifest <tight_limit_manifest.json> \
  --calibration-candidate data/outputs/scenario_generation/v0.5.1/CF001_C1/candidate.json \
  --execute-paid
```

After all R1–R4 review and publication gates pass, finalize their 12-word headroom checks without altering the frozen limits:

```bash
uv run python scripts/build_word_budget_manifest.py \
  --accepted-root data/inputs/scenarios/v0.5.1/accepted \
  --accepted-scenario-manifest data/inputs/scenarios/v0.5.1/accepted_scenario_manifest.json \
  --tight-limit-manifest <tight_limit_manifest.json> \
  --frozen-by <researcher_id> \
  --output <word_budget_manifest.json>
```
