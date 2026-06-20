---
name: research-auditor
description: "Agentic research integrity auditor: verifies that claims in a research paper are grounded in actual code and experimental results in the repository. ONLY invoke this skill when the user explicitly asks to run a research audit or integrity check — do NOT trigger automatically. This skill is expensive (many API calls per run) and MUST ask the user for confirmation before executing. Trigger phrases: run the research audit, audit my paper, integrity check, verify my claims against the repo, check for hallucinations in my paper."
---

# Research Auditor

**IMPORTANT: Always ask the user for explicit confirmation before running this skill. It is expensive — it makes multiple OpenAI API calls per claim and can take several minutes. Do not invoke it unless the user has clearly asked for it and confirmed they want to proceed.**

Orchestrates a three-phase multi-agent audit loop to verify that every claim in a research paper is supported by actual code, data pipelines, and experimental results in the repository. Agents navigate the codebase autonomously using read-only file tools.

## Architecture

```
[Paper .tex file]
       │
       ▼
┌─────────────────────┐
│  Supervisor Agent   │  Phase 1: extract structured claims
└──────────┬──────────┘
           │
           ▼ (per claim)
┌─────────────────────┐
│  Verifier Agent     │  Phase 2: autonomous repo navigation + verdict
│  (Code Scout +      │  Tools: list_directory, read_file, search_repo,
│   Log Analyst)      │         parse_python_ast, find_result_files,
└──────────┬──────────┘         read_json_result
           │
           ▼
┌─────────────────────┐
│   AuditReport       │  Phase 3: compile + save JSON report
└─────────────────────┘
```

All file access is **read-only**. The agent never writes to or executes anything in the repository.

## When to invoke

Only when the user **explicitly asks** for a research audit or integrity check, AND confirms they want to run it. Before running, say:

> "This will run a multi-agent audit — approximately N API calls per claim (up to 20 claims). Shall I proceed?"

Do NOT trigger from general mentions of "checking" or "verifying" writing — use `tex-reviewer` or `citation-validator` for those.

## Running the script

```bash
# Audit the full paper against the current repo
uv run python .Codex/skills/research-auditor/scripts/audit_research.py \
  --paper chapters/dissertation.tex

# Specify the repo root explicitly
uv run python .Codex/skills/research-auditor/scripts/audit_research.py \
  --paper chapters/dissertation.tex \
  --repo .

# Limit to the N most salient claims (cheaper, faster)
uv run python .Codex/skills/research-auditor/scripts/audit_research.py \
  --paper chapters/dissertation.tex \
  --max-claims 10
```

## Arguments

| Argument | Description |
|----------|-------------|
| `--paper FILE` | `.tex` paper or dissertation file (required) |
| `--repo DIR` | Repository root to audit (default: `.`) |
| `--max-claims N` | Max claims to verify — default 20; reduce for a cheaper spot-check |

## What is verified

The Supervisor agent reads the paper and extracts:
- **Metric claims** — quantitative results (accuracy, F1, loss, etc.)
- **Methodology claims** — design choices traceable to code
- **Dataset claims** — data sources, sizes, processing steps
- **Finding claims** — key qualitative or comparative conclusions

Each claim is then verified by the Verifier agent, which autonomously:
1. Maps the repo structure with `list_directory`
2. Searches for relevant code with `search_repo` (regex across file types)
3. Reads specific files and traces logic with `read_file` + `parse_python_ast`
4. Finds and parses result files with `find_result_files` + `read_json_result`
5. Renders a verdict: `confirmed`, `contradicted`, `unverifiable`, or `not_found`

## Output

- Human-readable summary printed to stdout with per-claim verdicts and evidence
- Full JSON report saved to `logs/research_audits/<timestamp>_audit_report.json`
- Exit code 1 if any claims are contradicted

## Integrity score

`confirmed / total_claims`. A score < 1.0 means some claims could not be verified from the repo — investigate `not_found` and `contradicted` items before submission.

## Requirements

- `OPENAI_API_KEY_RESEARCH_AUDITOR` set in `.env` or `.env.static`
- Result files accessible under the repo root (`.json`, `.csv`, `.log`, etc.)
