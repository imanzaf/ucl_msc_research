---
name: tex-reviewer
description: "Reviews and improves existing LaTeX academic text to publication quality. Use this skill when the user has existing .tex content and wants it reviewed, improved, or critiqued — not when they need new content written. Trigger on: review my tex, improve this section, check my writing, critique this chapter, is this publication quality, peer review this, academic writing feedback. Do NOT trigger when the user needs to write a new section, draft content from scratch, or turn code/results/data into prose — use academic-author for those tasks."
---

# TeX Reviewer

Reviews and improves existing LaTeX academic text to publication quality.

Distinct from `academic-author`: this skill **critiques and improves existing content**; `academic-author` **creates new content**. If the user does not already have a `.tex` section to hand, use `academic-author` instead.

## When to invoke

- User has existing `.tex` content and wants it reviewed, improved, or critiqued
- User asks for feedback on academic tone, argument rigour, or citation practice
- User wants to assess whether an existing section meets publication standard
- User is polishing a draft section of a paper or dissertation

Do **not** use this skill when the user needs to write a new section, draft content from scratch, or convert code/results/data into prose — use `academic-author` for those tasks.

## Running the script

```bash
# Review and rewrite a full tex file
uv run python .claude/skills/tex-reviewer/scripts/review_tex.py chapters/literature_review.tex

# Target a specific section by name
uv run python .claude/skills/tex-reviewer/scripts/review_tex.py chapters/methodology.tex --section "Methodology"

# Target by line range
uv run python .claude/skills/tex-reviewer/scripts/review_tex.py chapters/results.tex --section 45-120

# Provide supporting context files
uv run python .claude/skills/tex-reviewer/scripts/review_tex.py chapters/results.tex \
  --support experiments/results.json experiments/eval.py

# Critique only (no rewrite)
uv run python .claude/skills/tex-reviewer/scripts/review_tex.py chapters/intro.tex --mode review
```

## Arguments

| Argument | Description |
|----------|-------------|
| `file` | Path to the `.tex` file (required) |
| `--section NAME\|N-M` | Section name (e.g. `"Literature Review"`) or line range (e.g. `45-120`) |
| `--support FILE ...` | Additional context files referenced in the section |
| `--mode rewrite\|review` | `rewrite` returns improved tex; `review` returns critique only (default: `rewrite`) |

## Output

- Improved tex block (or critique) printed to stdout
- Always saved to `logs/tex_reviews/<timestamp>_<mode>.tex`

## Writing standard enforced

The system prompt holds the model to peer-review publication quality across all dimensions:

**Argument and analytical rigour** — every claim grounded in evidence or explicitly flagged as the author's own argument; synthesis over summary; precise scope; analytical voice visible

**Literature review** — critical not descriptive; gaps, contradictions, and unresolved debates identified; citations earn their place; research question emerges as the inevitable response to the gap

**Methodology** — every choice justified against alternatives; operationalisation, baselines, evaluation protocol, and failure modes explicit; quantitative metrics defined and reported

**Results and discussion** — discussion interprets and contextualises findings against prior work; does not restate results; limitations specific and honest

**Prose and structure** — formal precise English; signposting throughout; technical terms defined on first use; coherent paragraph structure and logical flow

**LaTeX conventions** — existing `\cite{}`, `\ref{}`, `\label{}` preserved; `\cite{TODO}` inserted where citations are missing; valid LaTeX returned only

## Workflow

1. Identify the tex file and section from the user's request
2. Ask about supporting files if the section references results or experiments and none were provided
3. Run the script with appropriate arguments
4. Present the improved tex output inline
5. Flag anything that still needs manual attention (e.g. missing citations to add, figures that need creating)
