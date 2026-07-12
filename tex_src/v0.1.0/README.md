# Nothing Untrue — LaTeX thesis draft

This project is a modular first draft for a thesis on omission, pragmatic distortion, and risk communication in financial LLM agents.

The core thesis chapters are approximately 10,000 words by `texcount`, excluding the detailed appendices and bibliography.

## Build

```bash
make
```

This runs `pdflatex`, `bibtex`, and two further `pdflatex` passes. The compiled document is `main.pdf`.

## Project structure

- `main.tex` — document entry point
- `preamble.tex` — packages, typography, and red placeholder macros
- `sections/00_abstract.tex`
- `sections/01_introduction.tex`
- `sections/02_literature_review.tex`
- `sections/03_methodology.tex`
- `sections/04_results.tex`
- `sections/05_discussion.tex`
- `sections/06_conclusion.tex`
- `appendices/A_prompt_templates.tex`
- `appendices/B_annotation_schema.tex`
- `appendices/C_reporting_checklist.tex`
- `references.bib` — BibTeX database

## Placeholder conventions

Red text is intentional and marks unresolved design decisions, experiment-dependent results, missing metadata, and material requiring final verification.

- `\placeholder{...}` — content to complete or verify
- `\decision{...}` — design decision to close
- `\resultcell` — table or inline numerical result to replace
- `placeholderblock` — longer red editorial instruction

Before submission, search the source tree for `PLACEHOLDER`, `DECISION REQUIRED`, `TBD`, and `placeholderblock`.
