---
name: code-review
description: "Performs a thorough code review of local changes in this research codebase. ALWAYS invoke this skill when: (1) the user asks for a code review, review of a component, file, directory, or the full codebase; (2) after the agent completes a major feature addition, significant refactor, or new experiment scaffold. Trigger phrases: review this, code review, review the changes, check my code, review src/, did I do this right, is this correct, review before I commit, or any explicit request to check code quality. Also auto-trigger after the agent writes a new experiment runner, adds a new settings class, or does a multi-file refactor — even if the user did not explicitly ask for a review."
---

# Code Review

Performs a multi-agent code review of local changes against project standards. Works on recent git changes (default) or a specific path if given.

## Input

The user may pass an optional path argument (file, directory, or glob). If no path is given, review the diff of the current branch against `main` (or `HEAD` if on main).

## Process

Follow all steps in order. Do not skip steps.

### Step 1: Determine scope

If the user provided a path, use that. Otherwise run:

```bash
git diff --name-only main...HEAD 2>/dev/null || git diff --name-only HEAD~1
```

If there are no changed files, say "No changes to review." and stop.

Also grab the AGENTS.md for context:

```bash
cat AGENTS.md
```

### Step 2: Check eligibility

Skip the review if the diff is trivially small (e.g., only a version bump, only whitespace, or only a single config value change with no logic). In that case say "Diff is too small to warrant a full review." and stop.

### Step 3: Get a change summary

Spawn a Haiku subagent to read `git diff main...HEAD` (or the relevant path diff) and return a 3–5 sentence summary of what changed and why. This summary is passed to all review agents in step 4.

### Step 4: Launch 5 parallel review agents (Sonnet)

Spawn these five agents **in the same turn**. Each agent should read the actual diff (via `git diff main...HEAD -- <files>` or `git diff HEAD~1 -- <files>` for a path-scoped review) and return a list of issues with:
- A short description of the issue
- The file path and approximate line number
- The reason it was flagged (AGENTS.md rule, bug, structural violation, etc.)
- A confidence score 0–100 (rubric below)

**Agent 1 — AGENTS.md compliance**

Read AGENTS.md (already provided in context) and check the diff against every applicable rule. Focus on:
- `uv run python` / `uv add` (never `python` directly, never `pip install`)
- Pydantic v2 (`BaseModel`, `Field`, `model_validator`) for all structured data crossing boundaries
- `str, Enum` for fixed string fields — never bare `str` with a comment
- `BaseSettings` subclasses in `src/settings/`, one class per concern, each with an `@lru_cache` getter
- Settings accessed via `get_<desc>_settings()` from `src/settings/`, never `os.environ` directly
- Structured outputs saved as JSONL (records) or JSON (configs/summaries); must include `schema_version`
- Line length ≤ 150

Note: AGENTS.md is guidance for AGENTS writing code. Not all rules apply to review (e.g., "never pip install" applies to AGENTS's shell commands, not to user code). Use judgment to flag only rules that are genuinely violated in the code itself.

**Agent 2 — Bugs (major and minor)**

Read the diff and flag bugs at two levels:

Major (will cause incorrect behaviour or data loss in practice):
- Logic errors (off-by-one, wrong condition, inverted boolean)
- Data loss or silent corruption (e.g., overwriting a file without checking)
- `except: pass` or `except Exception: pass` silently swallowing errors
- Type mismatches that would cause a runtime crash (not ones a type checker catches)
- Unhandled exceptions where a real recovery path exists but is missing

Minor (won't crash but will produce wrong results or cause confusion in edge cases):
- Edge cases that are reachable but unhandled (empty list, zero, None input)
- Off-by-one in slice or range that only triggers on boundary values
- A condition that is almost always right but silently wrong in one case
- Resource not closed/released on the non-happy path (file handles, connections)

Ignore: style, imports, test coverage, general security. Ignore pre-existing issues on lines not in the diff. Label each issue **[major]** or **[minor]** in your output.

**Agent 3 — Type hints and docstrings**

Read the diff and check that every new or modified function:
- Has a complete type-annotated signature (`List[str]`, `Dict[str, int]` etc. from `typing`, not `list[str]`)
- Has a docstring (at minimum one sentence on what it does; args documented if non-obvious)
- Does not have a docstring that just restates the function name or explains WHAT the code does (it should explain WHY, or be a concise description of responsibility)

Flag missing or inadequate docstrings/types for any function added or substantially modified in the diff.

**Agent 4 — Experiment structure compliance** (only if `experiments/` appears in the diff)

If no `experiments/` files are in the diff, this agent returns "No experiment files changed — skipped."

Otherwise check:
- Experiment directories follow `<name>_v<N>` naming (lowercase snake_case, explicit version)
- Directory layout has `config.json`, `results/`, `logs/`, `assets/`
- Eval scripts have an accompanying `generate_assets.py` or `generate_paper_assets()` function
- Raw results saved as `<YYYYMMDDTHHMMSS>_results.jsonl`
- Run logs saved as `<YYYYMMDDTHHMMSS>_run.log`
- Paper assets include at least one `.tex` table or `.pdf` figure
- No fabricated metrics or hardcoded result values

**Agent 5 — Simplification**

Read the diff and flag code that is needlessly complex, redundant, or abstracted beyond what the task requires. Focus on:
- Duplicate logic that could be a single function or loop (three similar lines is fine; four+ identical blocks is not)
- Premature abstractions: helper functions, base classes, or indirection added for hypothetical future use rather than a current need
- Variables or intermediate values that only exist to be immediately returned or passed once — inline them
- Nested conditionals that could be flattened with an early return or guard clause
- Reuse of a stdlib or already-imported utility where a manual re-implementation was written instead

Do not flag: necessary abstractions, complexity that serves readability, or any style issue a linter would catch. Only flag things a senior engineer would push back on in review as over-engineered or unnecessarily verbose.

### Step 5: Score and filter

For each issue returned by the five agents, use this rubric to assign (or verify) a confidence score:

- **0** — False positive; doesn't hold up to light scrutiny, or is pre-existing
- **25** — Might be real but unverified; stylistic issue not explicitly in AGENTS.md
- **50** — Real issue but minor or infrequent in practice
- **75** — Verified real issue, important, will be hit in practice; or directly named in AGENTS.md
- **100** — Certain; confirmed, frequent, evidence is direct

Drop any issue with confidence < 75. If nothing remains, output "No issues found." (see format below).

For AGENTS.md issues: double-check that the AGENTS.md actually names the rule being cited before scoring ≥ 75.

For type/docstring issues: only score ≥ 75 if the function was added or substantially changed in this diff (not pre-existing).

### Step 6: Output the report

Print the report directly in the conversation. No file output, no GitHub comment.

---

## Output format

### If issues found:

```
### Code review

Found N issues:

1. <brief description> — `path/to/file.py:~line`
   AGENTS.md: "<exact rule quoted>"   (or: Bug: <reason>  /  Structure: <reason>)

2. ...
```

### If no issues:

```
### Code review

No issues found. Checked AGENTS.md compliance, bugs, type hints/docstrings, experiment structure, and simplification.
```

Rules for the report:
- No emojis
- No trailing summaries or "hope this helps" padding
- Each issue fits on 1–2 lines
- Quote the AGENTS.md rule verbatim when citing it
- Include approximate line numbers where possible
- Brief is better than thorough — a senior engineer should be able to scan it in 30 seconds
