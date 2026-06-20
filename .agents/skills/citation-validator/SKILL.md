---
name: citation-validator
description: "Validates BibTeX citations in LaTeX research projects. Use this skill whenever the user is working with .bib or .tex files and wants to verify citation metadata, check papers are cited correctly before a commit or submission, audit whether .tex prose fairly represents what cited papers actually claim, or run a bibliography health check. Trigger on: validate citations, check my bib, verify references, are my citations right, citation audit, check bibliography, validate my references before I submit, or any time the user modifies .bib files and asks for a review. Only .bib and .tex files are relevant."
---

# Citation Validator

Validates BibTeX entries in a LaTeX project through three layers:

1. **Metadata verification** — fetches CrossRef metadata for each DOI and flags field mismatches (wrong title, year, journal, etc.)
2. **DOI resolution** — uses Playwright to follow the DOI.org redirect and extract the paper's abstract from the publisher landing page
3. **Semantic accuracy** — calls an OpenAI stored prompt to compare how each paper is cited in `.tex` prose against what the paper actually claims

Only `.bib` and `.tex` files are analysed. Ignore all other file types.

## Running the script

The script lives inside this skill bundle. Always run it from the project root using the bundle path:

```bash
# git-diff modified entries in current directory (default)
uv run python .Codex/skills/citation-validator/scripts/validate_citations.py

# All entries under chapters/
uv run python .Codex/skills/citation-validator/scripts/validate_citations.py chapters/ --bib all

# Specific keys
uv run python .Codex/skills/citation-validator/scripts/validate_citations.py --bib vaswani2017attention devlin2018bert

# Single key, metadata-only
uv run python .Codex/skills/citation-validator/scripts/validate_citations.py --bib vaswani2017attention --no-semantic
```

Reports are always saved to `logs/Codex/citations/<timestamp>_citation_report.json` and printed to stdout.

## First-time setup

```bash
uv add bibtexparser playwright openai pydantic httpx pydantic-settings
uv run playwright install chromium
```

Set `OPENAI_API_KEY` in `.env` or `env.static` (read by `configs/settings.py`).

## Workflow

1. Run the appropriate command above (default git-diff mode; use `--all` for a full audit).
2. Parse the JSON output and present a human-readable summary:
   - Metadata mismatches (wrong title/year/journal)
   - Citation keys whose DOI does not resolve
   - Semantic issues flagged by the AI, grouped by citation key
3. For each issue suggest a concrete fix: corrected BibTeX field, or a rewording of the `.tex` sentence that better reflects the paper's claims.
4. Exit code 1 means semantic errors were found; exit code 0 means clean.

## Output format

```json
{
  "schema_version": "1.0",
  "summary": { "total": 3, "ok": 1, "warnings": 1, "errors": 1 },
  "results": [
    {
      "bib_key": "vaswani2017attention",
      "doi": "10.48550/arXiv.1706.03762",
      "doi_resolves": true,
      "title": "Attention Is All You Need",
      "metadata_mismatches": [],
      "citation_contexts": [
        { "tex_file": "chapter2.tex", "line_number": 47,
          "context": "...the transformer \\cite{vaswani2017attention} replaces recurrence..." }
      ],
      "semantic_issues": [],
      "status": "ok"
    }
  ]
}
```

`status` is one of `ok`, `warning` (metadata mismatch or unresolved DOI), or `error` (semantic issues flagged by the AI).