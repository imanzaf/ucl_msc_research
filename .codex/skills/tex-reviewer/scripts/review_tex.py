#!/usr/bin/env python3
"""review_tex.py — Reviews and rewrites LaTeX academic text to publication quality.

Calls Claude Opus 4.7 via the Anthropic API with extended thinking and structured
output (tool use) to enforce typed Pydantic responses for both modes.

Usage:
    uv run python .claude/skills/tex-reviewer/scripts/review_tex.py <file.tex> [options]
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from enum import Enum
from pathlib import Path

import anthropic
from pydantic import BaseModel, Field

from configs import get_api_settings

settings = get_api_settings()

_LOG_DIR = Path("logs/tex_reviews")
_MODEL = "claude-opus-4-7"
_THINKING_BUDGET = 10_000


# ── Enums ──────────────────────────────────────────────────────────────────────


class ReviewMode(str, Enum):
    REWRITE = "rewrite"
    REVIEW = "review"


class IssueType(str, Enum):
    UNSUPPORTED_CLAIM = "unsupported_claim"
    WEAK_ARGUMENTATION = "weak_argumentation"
    MISSING_CITATION = "missing_citation"
    DESCRIPTIVE_NOT_CRITICAL = "descriptive_not_critical"
    SCOPE_OVERCLAIM = "scope_overclaim"
    POOR_SIGNPOSTING = "poor_signposting"
    UNDEFINED_TERM = "undefined_term"
    WEAK_METHODOLOGY_JUSTIFICATION = "weak_methodology_justification"
    RESULTS_RESTATEMENT = "results_restatement"
    BOILERPLATE_LIMITATION = "boilerplate_limitation"
    OTHER = "other"


class IssueSeverity(str, Enum):
    CRITICAL = "critical"  # blocks publication — reviewer will reject
    MAJOR = "major"  # likely to draw significant reviewer criticism
    MINOR = "minor"  # polish or style


# ── Output models ──────────────────────────────────────────────────────────────


class ReviewIssue(BaseModel):
    location: str = Field(description="Where the issue occurs, e.g. 'paragraph 2, sentence 3'")
    issue_type: IssueType
    severity: IssueSeverity
    description: str = Field(description="What is wrong and why it matters")
    suggestion: str = Field(description="Specific actionable fix")


class ReviewOutput(BaseModel):
    schema_version: str = "1.0"
    overall_assessment: str = Field(
        description="2-3 sentence summary of the section's current quality and main weaknesses"
    )
    issues: list[ReviewIssue] = Field(description="All identified issues, ordered by severity")
    priority_fixes: list[str] = Field(
        description="Top 3 most important things to address before submission, as concrete actions"
    )
    example_rewrite: str = Field(
        description="Improved LaTeX rewrite of the single weakest paragraph, showing the standard expected"
    )


class RewriteOutput(BaseModel):
    schema_version: str = "1.0"
    issues_addressed: list[str] = Field(
        description="Brief descriptions of the main issues found and corrected in the rewrite"
    )
    improved_tex: str = Field(
        description="The full improved LaTeX block — valid LaTeX only, no markdown or commentary"
    )
    remaining_notes: list[str] = Field(
        description="Things that still require manual attention (e.g. missing figures, citations to add)"
    )


# ── System prompt ──────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a senior academic editor with extensive experience reviewing manuscripts for \
top-tier peer-reviewed venues (NeurIPS, ICML, Nature, Science, leading finance and AI journals). \
Your standard is publication-ready prose: precise, rigorous, and analytically substantive.

Your task is to review existing LaTeX and return structured output via the provided tool. \
The bar is submission to a peer-reviewed journal or conference — not merely competent, but compelling.

## Writing standards you must enforce

### Argument and analytical rigour
- Every claim must be grounded in evidence: a citation, empirical result, or clearly flagged \
  as the author's own reasoned argument
- Synthesise — do not merely summarise. Follow what others found with analytical voice: \
  "This suggests…", "A limitation of this approach is…", "Taken together, these findings indicate…"
- Scope conclusions precisely to what the data, method, and evidence support — never over-claim
- Make the author's contribution and perspective visible; do not hide behind passive voice

### Literature review
- Critical, not descriptive: identify gaps, contradictions, underexplored questions, unresolved debates
- Each citation must earn its place: to support, contrast, extend, or contextualise an argument
- The research question should emerge as the logical, unavoidable response to an identified gap

### Methodology
- Justify every methodological choice against alternatives
- Be explicit: operationalisation, experimental setup, baselines, evaluation protocol, failure modes
- Quantitative metrics (precision, recall, F1, AUC) defined and reported with statistical context

### Results and discussion
- Discussion must intellectually engage with results — compare with prior work, explain unexpected \
  findings, draw non-obvious inferences; do not restate results
- Limitations must be specific and honest, not boilerplate

### Prose and structure
- Formal, precise academic English — no hedging, filler, or informal phrasing
- Signpost: state what the section will do, do it, confirm what was shown
- Every technical term and abbreviation defined on first use
- Clear topic sentences; logical flow between paragraphs

### LaTeX conventions
- Preserve all existing \\cite{}, \\ref{}, \\label{} commands unless clearly erroneous
- Insert \\cite{TODO} where a citation is warranted but absent
- Use \\emph{} for emphasis; avoid \\textbf{} for emphasis in running prose
- Return only valid LaTeX in improved_tex — no markdown, no commentary
"""


# ── Section extraction ─────────────────────────────────────────────────────────


def _extract_section(content: str, section: str) -> tuple[str, int, int]:
    """Return (extracted_text, start_line, end_line). Lines are 1-indexed."""
    lines = content.splitlines()

    if re.match(r"^\d+-\d+$", section):
        start, end = (int(x) for x in section.split("-"))
        start, end = max(1, start), min(len(lines), end)
        return "\n".join(lines[start - 1 : end]), start, end

    pattern = re.compile(
        r"\\(?:sub){0,2}section\*?\{[^}]*" + re.escape(section) + r"[^}]*\}",
        re.IGNORECASE,
    )
    for i, line in enumerate(lines):
        if pattern.search(line):
            next_sec = re.compile(r"\\(?:chapter|section)\*?\{", re.IGNORECASE)
            end_line = len(lines)
            for j in range(i + 1, len(lines)):
                if next_sec.search(lines[j]):
                    end_line = j
                    break
            return "\n".join(lines[i:end_line]), i + 1, end_line

    return content, 1, len(lines)


# ── API call with structured output ───────────────────────────────────────────


def _build_user_message(
    tex_content: str,
    support_contents: list[tuple[str, str]],
    mode: ReviewMode,
    section_info: str,
) -> str:
    parts = []

    label = mode.value
    parts.append(
        f"## LaTeX section to {label}"
        + (f" ({section_info})" if section_info else "")
        + f"\n\n```latex\n{tex_content}\n```"
    )

    for filename, content in support_contents:
        ext = Path(filename).suffix.lower()
        lang = {".py": "python", ".json": "json", ".csv": "csv", ".md": "markdown"}.get(ext, "")
        parts.append(f"## Supporting file: {filename}\n\n```{lang}\n{content}\n```")

    instruction = (
        "Rewrite this section to publication quality and call submit_output with your result."
        if mode == ReviewMode.REWRITE
        else "Critique this section and call submit_output with your structured review."
    )
    parts.append(f"Task: {instruction}")

    return "\n\n".join(parts)


def _call_api(user_message: str, mode: ReviewMode) -> RewriteOutput | ReviewOutput:
    output_model = RewriteOutput if mode == ReviewMode.REWRITE else ReviewOutput
    tool_schema = output_model.model_json_schema()

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key_tex_reviewer)
    response = client.messages.create(
        model=_MODEL,
        max_tokens=16_000,
        thinking={"type": "enabled", "budget_tokens": _THINKING_BUDGET},
        system=_SYSTEM_PROMPT,
        tools=[
            {
                "name": "submit_output",
                "description": f"Submit the structured {mode.value} output.",
                "input_schema": tool_schema,
            }
        ],
        tool_choice={"type": "tool", "name": "submit_output"},
        messages=[{"role": "user", "content": user_message}],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_output":
            return output_model.model_validate(block.input)

    raise RuntimeError("API response contained no tool_use block — check model/API compatibility.")


# ── Output and persistence ─────────────────────────────────────────────────────


def _save(result: RewriteOutput | ReviewOutput, mode: ReviewMode) -> Path:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    path = _LOG_DIR / f"{ts}_{mode.value}.json"
    path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return path


def _print_result(result: RewriteOutput | ReviewOutput, mode: ReviewMode) -> None:
    if mode == ReviewMode.REWRITE:
        assert isinstance(result, RewriteOutput)
        if result.issues_addressed:
            print("Issues addressed:", file=sys.stderr)
            for issue in result.issues_addressed:
                print(f"  - {issue}", file=sys.stderr)
        print()
        print(result.improved_tex)
        if result.remaining_notes:
            print("\n% --- Remaining notes ---", file=sys.stderr)
            for note in result.remaining_notes:
                print(f"%   {note}", file=sys.stderr)
    else:
        assert isinstance(result, ReviewOutput)
        print(f"Overall: {result.overall_assessment}\n")
        print("Priority fixes:")
        for i, fix in enumerate(result.priority_fixes, 1):
            print(f"  {i}. {fix}")
        print(f"\nIssues ({len(result.issues)} found):")
        for issue in result.issues:
            print(
                f"  [{issue.severity.value.upper()}] {issue.location} "
                f"— {issue.issue_type.value}\n"
                f"    {issue.description}\n"
                f"    → {issue.suggestion}"
            )
        print(f"\nExample rewrite (weakest paragraph):\n\n{result.example_rewrite}")


# ── Main ───────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Review and rewrite LaTeX academic text to publication quality."
    )
    parser.add_argument("file", type=Path, help=".tex file to review")
    parser.add_argument(
        "--section",
        metavar="NAME|N-M",
        help="Section name (e.g. 'Literature Review') or line range (e.g. '45-120')",
    )
    parser.add_argument(
        "--support",
        nargs="+",
        metavar="FILE",
        help="Additional context files referenced in the section",
    )
    parser.add_argument(
        "--mode",
        choices=[m.value for m in ReviewMode],
        default=ReviewMode.REWRITE.value,
        help="rewrite (return improved tex) or review (critique only) [default: rewrite]",
    )
    args = parser.parse_args()
    mode = ReviewMode(args.mode)

    if not args.file.exists():
        print(f"Error: file not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    tex_content = args.file.read_text(encoding="utf-8")

    section_info = ""
    if args.section:
        tex_content, start, end = _extract_section(tex_content, args.section)
        section_info = f"{args.section} — lines {start}–{end}"

    support_contents: list[tuple[str, str]] = []
    for sf in args.support or []:
        p = Path(sf)
        if p.exists():
            support_contents.append((sf, p.read_text(encoding="utf-8", errors="ignore")))
        else:
            print(f"Warning: support file not found: {sf}", file=sys.stderr)

    print(
        f"Reviewing {args.file}" + (f" § {args.section}" if args.section else "") + " …",
        file=sys.stderr,
    )
    print(
        f"Model: {_MODEL} | thinking: {_THINKING_BUDGET} tokens | mode: {mode.value}",
        file=sys.stderr,
    )

    result = _call_api(
        _build_user_message(tex_content, support_contents, mode, section_info),
        mode,
    )

    _print_result(result, mode)

    log_path = _save(result, mode)
    print(f"\nSaved to {log_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
