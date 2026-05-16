# UCL MSc Research Project

Dissertation + experiments on AI deception detection in financial agents.

## Commands

```bash
uv run python <script>          # always use uv run, never python directly
uv add <package>                # add deps — never pip install
uv run pytest                   # run tests
uv run pre-commit run --all-files  # run black + isort + flake8
```

## Project structure

```
.codex/skills/          # project skills (citation-validator, tex-reviewer, academic-author)
configs/                 # pydantic-settings classes, one file per concern
scripts/                 # runnable scripts (log_decisions.py)
src/                     # source code for research and experiments
.env.static              # base config (committed, contains placeholders)
```

## Environment and config

- Settings load from `.env.static` first, then `.env` — `.env` wins on conflicts
- Never read `os.environ` directly; use `get_<desc>_settings()` from `configs/`
- Python version is pinned to 3.11 via `.python-version`

## Code conventions

- Pydantic v2 (`BaseModel`, `Field`, `model_validator`) for all structured data crossing boundaries
- `str, Enum` for any field with a fixed set of string values — never bare `str` with a comment
- `BaseSettings` subclasses go in `configs/`, one class per concern, each with an `@lru_cache` getter
- Structured outputs saved as JSONL (records) or JSON (configs/summaries); include `schema_version`
- Line length: 150 (black + isort + flake8 all configured to match)

## Code style

**Functions** — single responsibility (one job per function; if you need "and" in the description, split it); exit early with guard clauses rather than deeply nested conditionals

**Comments** — every function must have a docstring: one sentence on what it does, followed by its arguments if non-obvious; inline comments explain *why* only when non-obvious

**Error handling** — never silently swallow errors (`except: pass` is always wrong); handle errors where there is a real recovery path or a useful message to surface, let everything else propagate

**Naming** — avoid abbreviations beyond common conventions (`idx`, `n`, `df`, `cls`)

**Types** — always type-hint function signatures; use `List[str]`, `Dict[str, int]` etc. from `typing`

## Academic skills (`.codex/skills/`)

| Skill | When to use | Script |
|-------|-------------|--------|
| `academic-author` | Write new sections or update existing with new context | `write_section.py` |
| `tex-reviewer` | Critique and improve existing `.tex` content | `review_tex.py` |
| `citation-validator` | Validate `.bib` entries against CrossRef + semantic check | `validate_citations.py` |

All three use the Anthropic or OpenAI API — keys must be set in `.env`.

## Decision logging

Whenever you identify or make a research or methodology decision — a choice of approach, model, dataset, evaluation strategy, framing, or any other consequential research choice — write it on its own line in your response using exactly this format:

```
Research decision: <decision and brief rationale>
Methodology decision: <decision and brief rationale>
```

The `Stop` hook automatically scans your response for these lines and persists them to `logs/decisions/`. Do not paraphrase or vary the prefix — the hook matches the exact strings `Research decision:` and `Methodology decision:`. Keep each decision on a single line.

## Documentation

- Keep `README.md` current whenever the project structure, key features, or research direction changes — it is the first entry point for anyone reading the repo
- Document every experiment runner or evaluation procedure in its own file under `docs/` (e.g. `docs/experiments/deception_eval.md`); include the exact `uv run ...` command to run it, all relevant config and output paths, and direct file references (e.g. `src/models/detector.py`, `configs/experiment_settings.py`)
- Reference source files and scripts by path within docs so they stay navigable as the codebase grows

## Dissertation writing rules

- All `.tex` citations must resolve to `references.bib`
- Never fabricate citations, results, or metrics
