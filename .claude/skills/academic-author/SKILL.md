---
name: academic-author
description: "Writes new LaTeX academic sections from scratch or updates existing sections with new context, to publication quality. Use this skill when the user needs to write a new section, draft any part of a paper or dissertation, or update an existing section with new results, code, or analysis. Trigger on: write the methodology, draft the introduction, write up the results section, add a literature review, update the discussion with new findings, write a new section on X, draft this chapter. Also triggers when the user provides code, results, or data and wants it written up as an academic section. After writing a literature review, automatically runs the citation validator. Do NOT trigger when the user only wants content reviewed or improved — use tex-reviewer for that."
---

# Academic Author

Writes new LaTeX academic sections from scratch or updates existing sections with new context. The output bar is peer-reviewed publication quality.

Distinct from `tex-reviewer`: this skill **creates** content; tex-reviewer **critiques** existing content.

## When to invoke

- User wants a new section written (methodology, introduction, literature review, results, discussion, conclusion, or any custom section)
- User has new results, code, or analysis and wants it written up as an academic section
- User wants to update an existing section with new context or findings

After writing or updating a **literature review** section, the citation validator runs automatically.

## Running the script

```bash
# Write a new section from scratch
uv run python .claude/skills/academic-author/scripts/write_section.py \
  --section "Methodology"

# Write with code and results as context
uv run python .claude/skills/academic-author/scripts/write_section.py \
  --section "Results" \
  --code-dir experiments/ \
  --context experiments/results.json experiments/eval_metrics.csv

# Write with specific instructions
uv run python .claude/skills/academic-author/scripts/write_section.py \
  --section "Literature Review" \
  --instructions "Focus on: (1) existing deception detection methods, (2) gaps in financial AI agent evaluation, (3) benchmark datasets. Mention Smith 2023 and Jones 2024."

# Update an existing section with new findings
uv run python .claude/skills/academic-author/scripts/write_section.py \
  --section "Discussion" \
  --existing chapters/discussion.tex \
  --context experiments/ablation_results.json

# Full example: update methodology with code and extra instructions
uv run python .claude/skills/academic-author/scripts/write_section.py \
  --section "Methodology" \
  --existing chapters/methodology.tex \
  --code-dir src/models/ src/training/ \
  --context data/dataset_stats.csv \
  --instructions "Add a subsection on the ablation setup. Emphasise the cross-validation strategy."
```

## Arguments

| Argument | Description |
|----------|-------------|
| `--section NAME` | Section name (required). e.g. `"Literature Review"`, `"Methodology"`, `"Results"` |
| `--existing FILE` | Existing `.tex` file to update (omit to write from scratch) |
| `--context FILE ...` | Context files: results CSVs/JSONs, prior sections, notes, papers |
| `--code-dir DIR ...` | Code directories to include (respects 80KB/file, 400KB total limit) |
| `--instructions TEXT` | Freeform instructions: bullet points, specific claims to include, papers to mention |

## Output

- LaTeX section printed to stdout
- JSON (full structured output) + `.tex` (extracted tex) saved to `logs/academic_author/<timestamp>_<type>.{json,tex}`
- For literature review sections: citation validator runs immediately after

## Structured output fields

| Field | Description |
|-------|-------------|
| `tex_content` | The complete LaTeX section, ready to `\input{}` |
| `bib_entries_needed` | Papers needed in `references.bib` (for any `\cite{TODO}` inserted) |
| `figures_needed` | Figures or tables that need creating |
| `assumptions_made` | Editorial choices made where information was ambiguous |

## Writing standard enforced

**Argument and structure** — clear topic sentences; signposting throughout; every term defined on first use; logical paragraph flow

**Analytical rigour** — claims grounded in evidence; synthesis over catalogue; author's analytical voice visible; precise scope

**Literature review** — critical not descriptive; gaps and contradictions identified; citations earn their place

**Methodology** — every choice justified against alternatives; baselines and failure modes explicit; quantitative metrics defined

**Results/discussion** — findings interpreted against prior work; limitations specific and honest

**LaTeX conventions** — `\cite{key}` for known refs, `\cite{TODO}` for needed refs; `booktabs` tables; `\emph{}` for emphasis; valid LaTeX only in output

## Workflow

1. Ask the user for `--section`, whether this is a new write or an update, and what context files exist (code dirs, results, existing sections)
2. Ask for any specific instructions or points to include (`--instructions`)
3. Run the script with appropriate arguments
4. Present the tex output inline
5. Flag `bib_entries_needed` and `figures_needed` so the user knows what still needs doing
6. If literature review: report citation validator results
