# Repository Instructions

This repository contains code, experiments, notes, and dissertation material for the UCL IFT MSc research project. Treat `DISTINCTION_GUIDE.md` as the project rubric and writing standard when working on dissertation-facing content.

## Python And Environment Rules

- Use `uv` for Python environment management, dependency management, tests, scripts, and experiment runs.
- Add dependencies with `uv add` or `uv add --dev`; do not use `pip install`, `conda`, `poetry`, or `pipenv` for this repo.
- Run project commands through `uv run`, for example `uv run pytest`, `uv run python path/to/script.py`, or `uv run ruff check`.
- Do not commit virtual environments, generated caches, or local runtime state.


## Configuration And Settings

- Use `pydantic-settings` `BaseSettings` subclasses for all environment variables and file-based config — never read `os.environ` directly in application code.
- Separate settings classes by concern rather than putting everything in one class: e.g. `APISettings` for external API credentials, `ExperimentSettings` for run parameters, `DataSettings` for paths, etc. Each class should have a single, clear purpose.
- Store settings classes under `configs/`, one file per class, re-exported from `configs/__init__.py`.
- Each `BaseSettings` subclass should load from `env.static` first then `.env` (`.env` takes precedence), using `env_file=["env.static", ".env"]` in `SettingsConfigDict`.
- Instantiate each settings class once via an `@lru_cache`-wrapped getter (e.g. `get_api_settings()`), never construct settings objects inline or in loops.

## Data Models And Interfaces

- Use Pydantic for structured data models that cross boundaries: configs, datasets, experiment records, metrics, model outputs, API payloads, persisted JSON/JSONL, and LLM structured outputs.
- Prefer Pydantic v2 style: `BaseModel`, `Field`, `ConfigDict`, `field_validator`, and `model_validator`.
- For any field with a fixed set of valid string values, define a `str, Enum` and use it as the field type — do not use bare `str` with a comment listing allowed values. This applies to model outputs, status fields, verdict fields, and any categorical label.
- Define explicit schema versions for persisted records that may evolve.
- Keep models close to the boundary they validate unless the same schema is shared across modules.
- Avoid untyped dictionaries for research data. If a dict survives beyond a tiny local block, make it a Pydantic model.

## Structured Outputs

- Persist experiment outputs as structured files: JSONL for records, JSON for configs/summaries, CSV/Parquet for tabular data.
- LLM calls must request structured output when the result is consumed by code or used as evidence.
- Raw model outputs may be saved only as provenance alongside parsed structured records; do not use raw text as the only experiment artifact.
- Include enough metadata to reproduce each result: timestamp, code version or commit, command, config path, random seed, model/provider, dataset/source identifiers, and schema version.

## Data Verification

- Validate external data at ingestion with Pydantic models or explicit schema checks.
- Verify required columns, types, ID uniqueness, missing-value policy, label definitions, split membership, and row counts before analysis.
- Guard against train/test leakage and duplicate records across splits.
- For datasets and paper corpora, preserve source URLs/DOIs, retrieval dates, and any filtering criteria.
- Treat all quantitative claims as requiring reproducible evidence from checked-in code, saved outputs, or cited sources.

## Experiment Standards

- Experiments must be runnable from a documented `uv run ...` command.
- Prefer small smoke-test fixtures before full experiment runs.
- Store configs separately from code when parameters affect reported results.
- Use deterministic seeds where possible and report nondeterminism where not possible.
- Never overwrite important experiment outputs without preserving provenance or making the replacement explicit.

## Research Integrity

- Never fabricate citations, datasets, metrics, or results.
- Dissertation TeX files should cite sources with citation commands that resolve to `references.bib`.
- Harvard formatting for TeX output should be handled by the LaTeX bibliography/citation style, while `references.bib` stores verified source metadata.
- Record important research choices by writing prompts or notes with an explicit line such as `Research decision: ...` or `Methodology decision: ...`; the repo hook logs those lines locally.
