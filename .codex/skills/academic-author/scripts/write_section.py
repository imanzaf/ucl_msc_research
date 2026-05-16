#!/usr/bin/env python3
"""write_section.py — Writes or updates LaTeX academic sections to publication quality.

Calls Claude Opus 4.7 via the Anthropic API with extended thinking and structured
output. Accepts code directories, context files, existing sections, and freeform
instructions. Automatically invokes the citation validator after literature review
sections.

Usage:
    uv run python .claude/skills/academic-author/scripts/write_section.py [options]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from enum import Enum
from pathlib import Path

import anthropic
from pydantic import BaseModel, Field

from configs import get_api_settings

settings = get_api_settings()

_LOG_DIR = Path("logs/academic_author")
_MODEL = "claude-opus-4-7"
_THINKING_BUDGET = 12_000
_MAX_FILE_BYTES = 80_000  # per file
_MAX_TOTAL_BYTES = 400_000  # total context ceiling

_CODE_EXTENSIONS = {
    ".py",
    ".ipynb",
    ".r",
    ".R",
    ".ts",
    ".js",
    ".sh",
    ".sql",
    ".yaml",
    ".yml",
    ".toml",
    ".json",
    ".csv",
    ".md",
    ".txt",
}

_LIT_REVIEW_NAMES = {"literature review", "related work", "background", "prior work"}


# ── Enums ──────────────────────────────────────────────────────────────────────


class SectionType(str, Enum):
    ABSTRACT = "abstract"
    INTRODUCTION = "introduction"
    LITERATURE_REVIEW = "literature_review"
    METHODOLOGY = "methodology"
    RESULTS = "results"
    DISCUSSION = "discussion"
    CONCLUSION = "conclusion"
    CUSTOM = "custom"


class WriteMode(str, Enum):
    WRITE = "write"  # new section from scratch
    UPDATE = "update"  # existing section updated with new context


# ── Output models ──────────────────────────────────────────────────────────────


class AuthorOutput(BaseModel):
    schema_version: str = "1.0"
    section_type: SectionType
    mode: WriteMode
    tex_content: str = Field(
        description="The complete LaTeX section — valid LaTeX only, no markdown or commentary outside the tex block"
    )
    bib_entries_needed: list[str] = Field(
        description="Descriptions of papers that need to be found and added to references.bib (for any \\cite{TODO} inserted)"
    )
    figures_needed: list[str] = Field(
        description="Figures or tables that need to be created and referenced in the section"
    )
    assumptions_made: list[str] = Field(
        description="Assumptions or editorial choices made when information was ambiguous or missing"
    )


# ── System prompt ──────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a senior academic author with extensive experience writing for top-tier \
peer-reviewed venues (NeurIPS, ICML, Nature, Science, leading finance and AI journals). \
Your prose is publication-ready: precise, rigorous, analytically substantive, and \
compelling to expert reviewers.

You will either write a new LaTeX section from scratch, or update an existing section \
with new context — whichever the task specifies. In both cases, the output must meet \
the bar for peer-reviewed publication.

## Writing standards

### Argument and structure
- Open each section with a clear statement of its purpose; close with a brief forward link
- Every paragraph has a topic sentence; logical flow between paragraphs is explicit
- Signpost: tell the reader what you will do, do it, confirm what was shown
- Every technical term and abbreviation defined on first use

### Analytical rigour
- Every claim grounded in evidence: a citation, empirical result, or flagged as the author's argument
- Synthesise rather than catalogue: after presenting prior work, follow with analytical voice — \
  "This suggests…", "A key limitation of this approach is…", "Taken together, these results indicate…"
- Never over-claim beyond what the evidence supports
- The author's own contribution and perspective must be visible — do not hide behind citation chains

### Literature review (when applicable)
- Critical not descriptive: identify gaps, contradictions, underexplored questions
- Each citation earns its place; no decorative citations
- The research question should emerge as the inevitable response to an identified gap

### Methodology (when applicable)
- Justify every design choice against alternatives
- Explicit about operationalisation, baselines, evaluation protocol, and failure modes
- Quantitative metrics (precision, recall, F1, AUC) defined and reported with statistical context

### Results and discussion (when applicable)
- Discussion interprets and contextualises findings against prior work; does not restate results
- Limitations specific, honest, and not boilerplate

### LaTeX conventions
- Use \\section{}, \\subsection{} etc. as appropriate
- Use \\cite{key} for references known from the provided context; \\cite{TODO} where a \
  citation is clearly needed but no key is available
- Use \\emph{} for emphasis in running prose; avoid \\textbf{}
- Tables: \\begin{table}[t] with \\caption{} and \\label{}; use booktabs (\\toprule, \\midrule, \\bottomrule)
- Return only valid LaTeX in tex_content — no markdown, no prose outside the tex block
- If updating an existing section, preserve all \\label{} and \\ref{} keys unless clearly wrong

## Output
Call submit_output with your structured result. In tex_content, write complete, \
self-contained LaTeX ready to \\input{} into the main document.
"""


# ── Context loading ────────────────────────────────────────────────────────────


def _read_file_safe(path: Path, budget: list[int]) -> str | None:
    """Read a file respecting per-file and total budget limits."""
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if len(raw) > _MAX_FILE_BYTES:
        raw = raw[:_MAX_FILE_BYTES]
        truncated = True
    else:
        truncated = False
    text = raw.decode("utf-8", errors="replace")
    if budget[0] + len(text) > _MAX_TOTAL_BYTES:
        remaining = _MAX_TOTAL_BYTES - budget[0]
        if remaining <= 0:
            return None
        text = text[:remaining] + "\n... [truncated: total context limit reached]"
    budget[0] += len(text)
    if truncated:
        text += "\n... [truncated: file size limit]"
    return text


def _load_code_dir(directory: Path, budget: list[int]) -> list[tuple[str, str]]:
    files = []
    for path in sorted(directory.rglob("*")):
        if path.is_file() and path.suffix.lower() in _CODE_EXTENSIONS:
            if any(
                part.startswith(".") or part in ("__pycache__", "node_modules", ".venv")
                for part in path.parts
            ):
                continue
            text = _read_file_safe(path, budget)
            if text is not None:
                files.append((str(path.relative_to(directory.parent)), text))
    return files


def _load_context_file(path: Path, budget: list[int]) -> tuple[str, str] | None:
    text = _read_file_safe(path, budget)
    if text is None:
        return None
    return str(path), text


# ── Prompt construction ────────────────────────────────────────────────────────


def _infer_section_type(section_name: str) -> SectionType:
    lower = section_name.lower()
    for st in SectionType:
        if st.value.replace("_", " ") in lower or lower in st.value.replace("_", " "):
            return st
    return SectionType.CUSTOM


def _build_user_message(
    section_name: str,
    section_type: SectionType,
    mode: WriteMode,
    existing_tex: str | None,
    context_files: list[tuple[str, str]],
    instructions: str | None,
) -> str:
    parts = []

    # Mode and section header
    action = (
        "Update the following existing section"
        if mode == WriteMode.UPDATE
        else "Write a new section"
    )
    parts.append(f"## Task\n{action}: **{section_name}** ({section_type.value})")

    # Extra instructions
    if instructions:
        parts.append(f"## Author instructions\n{instructions}")

    # Existing section (update mode)
    if existing_tex:
        parts.append(f"## Existing section to update\n\n```latex\n{existing_tex}\n```")

    # Context files
    for filename, content in context_files:
        ext = Path(filename).suffix.lower()
        lang = {
            ".py": "python",
            ".ipynb": "python",
            ".r": "r",
            ".R": "r",
            ".json": "json",
            ".csv": "csv",
            ".md": "markdown",
            ".ts": "typescript",
            ".js": "javascript",
            ".sh": "bash",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".toml": "toml",
        }.get(ext, "")
        parts.append(f"## Context: {filename}\n\n```{lang}\n{content}\n```")

    parts.append(
        f"Call submit_output with the {'updated' if mode == WriteMode.UPDATE else 'new'} "
        f"LaTeX section and all required metadata fields."
    )
    return "\n\n".join(parts)


# ── API call ───────────────────────────────────────────────────────────────────


def _call_api(user_message: str, section_type: SectionType, mode: WriteMode) -> AuthorOutput:
    tool_schema = AuthorOutput.model_json_schema()

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key_academic_author)
    response = client.messages.create(
        model=_MODEL,
        max_tokens=16_000,
        thinking={"type": "enabled", "budget_tokens": _THINKING_BUDGET},
        system=_SYSTEM_PROMPT,
        tools=[
            {
                "name": "submit_output",
                "description": "Submit the structured section output.",
                "input_schema": tool_schema,
            }
        ],
        tool_choice={"type": "tool", "name": "submit_output"},
        messages=[{"role": "user", "content": user_message}],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_output":
            return AuthorOutput.model_validate(block.input)

    raise RuntimeError("API response contained no tool_use block.")


# ── Output ─────────────────────────────────────────────────────────────────────


def _save(result: AuthorOutput) -> tuple[Path, Path]:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    slug = result.section_type.value

    json_path = _LOG_DIR / f"{ts}_{slug}.json"
    json_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")

    tex_path = _LOG_DIR / f"{ts}_{slug}.tex"
    tex_path.write_text(result.tex_content, encoding="utf-8")

    return json_path, tex_path


def _print_result(result: AuthorOutput) -> None:
    print(result.tex_content)

    if result.bib_entries_needed:
        print("\n% --- Bibliography entries needed ---", file=sys.stderr)
        for entry in result.bib_entries_needed:
            print(f"%   {entry}", file=sys.stderr)

    if result.figures_needed:
        print("\n% --- Figures/tables to create ---", file=sys.stderr)
        for fig in result.figures_needed:
            print(f"%   {fig}", file=sys.stderr)

    if result.assumptions_made:
        print("\n% --- Assumptions made ---", file=sys.stderr)
        for note in result.assumptions_made:
            print(f"%   {note}", file=sys.stderr)


def _run_citation_validator() -> None:
    print("\nLiterature review section detected — running citation validator …", file=sys.stderr)
    subprocess.run(
        [
            "uv",
            "run",
            "python",
            ".claude/skills/citation-validator/scripts/validate_citations.py",
            "--all",
        ],
        check=False,
    )


# ── Main ───────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Write or update a LaTeX academic section to publication quality."
    )
    parser.add_argument(
        "--section",
        required=True,
        metavar="NAME",
        help="Section name, e.g. 'Literature Review', 'Methodology', 'Results'",
    )
    parser.add_argument(
        "--existing",
        type=Path,
        metavar="FILE",
        help=".tex file containing the existing section to update",
    )
    parser.add_argument(
        "--context",
        nargs="+",
        type=Path,
        metavar="FILE",
        help="Context files: results CSVs/JSONs, notes, papers, prior sections",
    )
    parser.add_argument(
        "--code-dir",
        nargs="+",
        type=Path,
        metavar="DIR",
        help="Code directories to include as context",
    )
    parser.add_argument(
        "--instructions",
        metavar="TEXT",
        help="Extra instructions or bullet points specifying what to include",
    )
    args = parser.parse_args()

    mode = WriteMode.UPDATE if args.existing else WriteMode.WRITE
    section_type = _infer_section_type(args.section)

    # Load existing section
    existing_tex: str | None = None
    if args.existing:
        if not args.existing.exists():
            print(f"Error: existing file not found: {args.existing}", file=sys.stderr)
            sys.exit(1)
        existing_tex = args.existing.read_text(encoding="utf-8")

    # Load all context with a shared budget counter
    budget: list[int] = [0]
    context_files: list[tuple[str, str]] = []

    for code_dir in args.code_dir or []:
        if not code_dir.is_dir():
            print(f"Warning: code directory not found: {code_dir}", file=sys.stderr)
            continue
        context_files.extend(_load_code_dir(code_dir, budget))

    for ctx_file in args.context or []:
        if not ctx_file.exists():
            print(f"Warning: context file not found: {ctx_file}", file=sys.stderr)
            continue
        loaded = _load_context_file(ctx_file, budget)
        if loaded:
            context_files.append(loaded)

    print(
        f"{'Updating' if mode == WriteMode.UPDATE else 'Writing'} section: {args.section} "
        f"({section_type.value}) | context: {len(context_files)} files "
        f"({budget[0] // 1024}KB) | model: {_MODEL}",
        file=sys.stderr,
    )

    user_message = _build_user_message(
        args.section, section_type, mode, existing_tex, context_files, args.instructions
    )
    result = _call_api(user_message, section_type, mode)

    _print_result(result)

    json_path, tex_path = _save(result)
    print(f"\nSaved → {tex_path}", file=sys.stderr)
    print(f"        {json_path}", file=sys.stderr)

    # Auto-invoke citation validator for literature review sections
    if args.section.lower() in _LIT_REVIEW_NAMES or section_type == SectionType.LITERATURE_REVIEW:
        _run_citation_validator()


if __name__ == "__main__":
    main()
