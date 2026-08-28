# UCL MSc Research Project

Dissertation and reproducible experiments on selective and directional communication by financial-assistant language models.

## Commands

```bash
uv run python <script>          # always use uv run, never python directly
uv add <package>                # add deps — never pip install
uv run pytest                   # run tests
uv run pre-commit run --all-files  # run black + isort + flake8
uv run risk-comm --help         # inspect the unified workflow CLI
```

## Project structure

```
src/                    # experiment, scoring, and analysis implementation
src/settings/           # pydantic-settings classes and the model catalog
src/cli/                # unified risk-comm CLI and workflow commands
tests/                  # tests for the retained implementation
schemas/                # exported JSON Schemas for public models
scripts/                # launcher, focused audit, and repository-hook utilities
docs/experiments/       # current workflow guides
tex_src/v0.4.0/         # latest dissertation source and manuscript assets
data/                   # frozen inputs and outputs; do not mutate without explicit scope
.env.static             # base config (committed, contains placeholders)
```

## Environment and config

- Settings load from `.env.static` first, then `.env` — `.env` wins on conflicts
- Never read `os.environ` directly; use `get_<desc>_settings()` from `src/settings/`
- Python version is pinned to 3.11 via `.python-version`

## Code conventions

- Pydantic v2 (`BaseModel`, `Field`, `model_validator`) for all structured data crossing boundaries
- `str, Enum` for any field with a fixed set of string values — never bare `str` with a comment
- `BaseSettings` subclasses go in `src/settings/`, one class per concern, each with an `@lru_cache` getter
- Structured outputs saved as JSONL (records) or JSON (configs/summaries); include `schema_version`
- Line length: 150 (black + isort + flake8 all configured to match)

## Code style

**Functions** — single responsibility (one job per function; if you need "and" in the description, split it); exit early with guard clauses rather than deeply nested conditionals

**Comments** — every function must have a docstring: one sentence on what it does, followed by its arguments if non-obvious; inline comments explain *why* only when non-obvious

**Error handling** — never silently swallow errors (`except: pass` is always wrong); handle errors where there is a real recovery path or a useful message to surface, let everything else propagate

**Naming** — avoid abbreviations beyond common conventions (`idx`, `n`, `df`, `cls`)

**Types** — always type-hint function signatures; use `List[str]`, `Dict[str, int]` etc. from `typing`

## Decision logging

Decision logging is only for durable, dissertation-level choices. Log a decision only when it changes the research direction, paper framing, research questions, core dataset/benchmark/model-family choice, evaluation strategy, annotation rubric, scoring metric, or experimental protocol.

Do not log routine implementation choices, individual scenario edits, file additions, refactors, bug fixes, hook/config tweaks, docs cleanup, temporary analysis steps, or other local engineering decisions.

When a decision qualifies, write it on its own line in your response using exactly this format:

```
Research decision: <decision and brief rationale>
Methodology decision: <decision and brief rationale>
```

The `Stop` hook automatically scans your response for these lines and persists qualifying high-level entries to `logs/decisions/`. Do not paraphrase or vary the prefix — the hook matches the exact strings `Research decision:` and `Methodology decision:`. Keep each decision on a single line.

## Experiment logging

**Naming** — all experiments follow `<descriptive_name>_v<N>` (lowercase snake_case, explicit version suffix). Increment `N` rather than overwriting.

**Directory layout** — every experiment lives entirely under its own subdirectory:

```
data/outputs/experiments/
  <name>_v<N>/
    config.json          # full config used for this run
    results/             # raw outputs: JSONL records, CSVs
    cache/               # output caches (if relevant)
    logs/                # run logs, stderr captures
    assets/              # experiment-owned stable assets
    checkpoints/         # execution summaries and workflow checkpoints
```

Experiment output directories live under `data/outputs/experiments/`; keep this tree git-ignored.

**Paper assets** — the versioned generator under `tex_src/v0.4.0/` reads frozen experiment and scoring outputs and writes stable manuscript figures,
tables, and summaries alongside the current dissertation source. Do not generate placeholders in experiment directories.

**Saving conventions**
- Raw results: `data/outputs/experiments/<name>_v<N>/results/<YYYYMMDDTHHMMSS>_results.jsonl`
- Run log: `data/outputs/experiments/<name>_v<N>/logs/<YYYYMMDDTHHMMSS>_run.log`
- Config snapshot: `data/outputs/experiments/<name>_v<N>/config.json` (written before the run starts)
- Manuscript assets: `tex_src/v0.4.0/assets/<stable_filename>`

## Documentation

- Keep `README.md` current whenever the project structure, key features, or research direction changes — it is the first entry point for anyone reading the repo
- Document stable user-facing workflows under `docs/`, grouping related runners as sections rather than creating one file per command or run
- Put run-specific details in `config.json`, manifests, results, and logs; do not create Markdown records for individual executions
- Workflow guides must include the exact `uv run risk-comm ...` commands, relevant config/output paths, and direct source references
- Reference source files and scripts by path within docs so they stay navigable as the codebase grows

## Dissertation writing rules

- All `.tex` citations must resolve to `references.bib`
- Never fabricate citations, results, or metrics
