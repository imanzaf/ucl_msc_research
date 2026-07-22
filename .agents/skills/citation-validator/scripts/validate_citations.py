#!/usr/bin/env python3
"""validate_citations.py — Citation validator for LaTeX/BibTeX projects.

Usage:
    uv run python .claude/skills/citation-validator/scripts/validate_citations.py
        [tex-dir] [--bib all|key [key ...]] [--no-semantic]

Arguments:
    tex-dir          Directory containing .bib and .tex files (default: .)

Options:
    --bib all        Validate every entry found in tex-dir
    --bib KEY ...    Validate one or more specific citation keys
                     (omit --bib to validate only git-diff modified entries)
    --no-semantic    Skip the OpenAI semantic check (metadata-only, faster)
"""

from __future__ import annotations

import argparse
import asyncio
import re
import subprocess
import sys
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

import bibtexparser
import httpx
from openai import OpenAI
from pydantic import BaseModel, Field

from src.settings import get_api_settings

settings = get_api_settings()

# ── Enums ──────────────────────────────────────────────────────────────────────


class ValidationStatus(str, Enum):
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"


class SemanticVerdict(str, Enum):
    CORRECT = "correct"
    INCORRECT = "incorrect"
    UNCERTAIN = "uncertain"


# ── Data models ────────────────────────────────────────────────────────────────


class MetadataMismatch(BaseModel):
    field: str
    bib_value: str
    crossref_value: str


class CitationContext(BaseModel):
    tex_file: str
    line_number: int
    context: str


class SemanticAssessment(BaseModel):
    reference_summary: str
    paragraph_context: str
    reasoning: str
    verdict: SemanticVerdict
    justification: str


class ValidationResult(BaseModel):
    bib_key: str
    doi: Optional[str] = None
    title: Optional[str] = None
    doi_resolves: bool = True
    metadata_mismatches: list[MetadataMismatch] = Field(default_factory=list)
    citation_contexts: list[CitationContext] = Field(default_factory=list)
    semantic_assessment: Optional[SemanticAssessment] = None
    status: ValidationStatus = ValidationStatus.OK


class Report(BaseModel):
    schema_version: str = "1.0"
    results: list[ValidationResult] = Field(default_factory=list)
    summary: dict[str, int] = Field(default_factory=dict)


# ── BibTeX helpers ─────────────────────────────────────────────────────────────


def _strip_braces(val: str) -> str:
    return val.strip("{}").strip()


def get_modified_bib_keys(root: Path) -> set[str]:
    """Return citation keys that appear in the current git diff of .bib files."""
    keys: set[str] = set()
    for cmd in (
        ["git", "diff", "HEAD", "--", "*.bib", "**/*.bib"],
        ["git", "diff", "--cached", "--", "*.bib", "**/*.bib"],
    ):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=root)
            for line in result.stdout.splitlines():
                if line.startswith("+") and not line.startswith("+++"):
                    m = re.search(r"@\w+\{\s*([^,\s]+)\s*,", line)
                    if m:
                        keys.add(m.group(1).strip())
        except FileNotFoundError:
            pass
    return keys


def parse_bib_files(tex_dir: Path) -> dict[str, dict]:
    entries: dict[str, dict] = {}
    for bib_file in sorted(tex_dir.rglob("*.bib")):
        try:
            with open(bib_file, encoding="utf-8") as fh:
                db = bibtexparser.load(fh)
            for entry in db.entries:
                key = entry["ID"]
                entries[key] = {
                    "key": key,
                    "type": entry.get("ENTRYTYPE", ""),
                    "fields": {k: v for k, v in entry.items() if k not in ("ID", "ENTRYTYPE")},
                }
        except Exception as exc:
            print(f"Warning: could not parse {bib_file}: {exc}", file=sys.stderr)
    return entries


# ── CrossRef metadata ──────────────────────────────────────────────────────────


async def fetch_crossref(doi: str) -> dict:
    url = f"https://api.crossref.org/works/{doi}"
    headers = {"User-Agent": "citation-validator/1.0 (mailto:research@ucl.ac.uk)"}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers=headers, follow_redirects=True)
            if resp.status_code == 200:
                return resp.json().get("message", {})
    except Exception:
        pass
    return {}


def compare_metadata(bib_entry: dict, crossref: dict) -> list[MetadataMismatch]:
    mismatches: list[MetadataMismatch] = []
    fields = bib_entry.get("fields", {})

    cr_titles = crossref.get("title", [])
    if cr_titles:
        cr_title = cr_titles[0].strip()
        bib_title = _strip_braces(fields.get("title", ""))
        if bib_title and cr_title.lower() != bib_title.lower():
            mismatches.append(
                MetadataMismatch(field="title", bib_value=bib_title, crossref_value=cr_title)
            )

    published = (
        crossref.get("published", {}).get("date-parts")
        or crossref.get("published-print", {}).get("date-parts")
        or []
    )
    if published and published[0]:
        cr_year = str(published[0][0])
        bib_year = _strip_braces(fields.get("year", ""))
        if bib_year and cr_year != bib_year:
            mismatches.append(
                MetadataMismatch(field="year", bib_value=bib_year, crossref_value=cr_year)
            )

    cr_journal = (crossref.get("container-title") or [""])[0].strip()
    bib_journal = _strip_braces(fields.get("journal") or fields.get("booktitle") or "")
    if cr_journal and bib_journal and cr_journal.lower() != bib_journal.lower():
        mismatches.append(
            MetadataMismatch(field="journal", bib_value=bib_journal, crossref_value=cr_journal)
        )

    return mismatches


# ── .tex citation context extraction ──────────────────────────────────────────

_CITE_PATTERN_TMPL = r"\\cite[tp*]?\{{[^}}]*\b{key}\b[^}}]*\}}"


def extract_citation_contexts(bib_key: str, tex_dir: Path) -> list[CitationContext]:
    pattern = re.compile(_CITE_PATTERN_TMPL.format(key=re.escape(bib_key)))
    contexts: list[CitationContext] = []
    for tex_file in sorted(tex_dir.rglob("*.tex")):
        try:
            lines = tex_file.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines):
            if pattern.search(line):
                window_start = max(0, i - 2)
                window_end = min(len(lines), i + 3)
                context_text = " ".join(
                    ln.strip() for ln in lines[window_start:window_end] if ln.strip()
                )
                contexts.append(
                    CitationContext(
                        tex_file=str(tex_file),
                        line_number=i + 1,
                        context=context_text,
                    )
                )
    return contexts


# ── OpenAI semantic check ──────────────────────────────────────────────────────

_DEVELOPER_PROMPT = """\
Given a provided .bib reference and a paragraph that cites or uses that reference,
use external web search tools to retrieve relevant, up-to-date information about the reference.
Carefully analyze the details gathered about the source and evaluate whether the reference in the paragraph is accurate,
appropriate, and semantically correct with respect to its content, argument, or context.

Persist through all necessary web searches until you are confident you have a comprehensive understanding of the referenced work.
Think step-by-step: first, interpret the .bib reference and its metadata, then search for sources to understand the reference's content,
followed by a contextual analysis of the paragraph's usage.
Only after reasoning through these steps, provide your final evaluation as to whether the citation has been used correctly.

## Step-by-Step Instructions

1. **Extract and Summarize Reference:**
   Parse the .bib reference into its components (e.g., author, year, title, journal, etc.).
   Summarize what kind of source it is and what its claims or findings are based on search results.

2. **Contextual Analysis (Reasoning):**
   Read the paragraph. Analyze how the reference is being used or cited.
   Compare the content/context of the cited paragraph to what you learned about the reference.
   Reflect internally on any mismatches, misrepresentations, or appropriate usages.

3. **Final Assessment (Conclusion):**
   State whether the use of the reference in the paragraph is semantically accurate, misleading, or incorrect, with succinct justification.

## Output Format

Output your response as a JSON object with exactly these fields:
- "reference_summary" (your synthesis of the referenced source's core topic/findings)
- "paragraph_context" (briefly describe how the paragraph is using the reference)
- "reasoning" (step-by-step analysis showing your thought process as you compare the reference's true content with its usage)
- "verdict" (exactly one of: "correct", "incorrect", or "uncertain" — no other values)
- "justification" (one sentence explaining the verdict)
"""


def _format_bib_entry(entry: dict) -> str:
    fields = entry.get("fields", {})
    field_lines = "\n".join(f"  {k} = {{{v}}}," for k, v in fields.items())
    return f"@{entry.get('type', 'article')}{{{entry['key']},\n{field_lines}\n}}"


def check_semantics(
    entry: dict,
    contexts: list[CitationContext],
) -> Optional[SemanticAssessment]:
    import json as _json

    bib_key = entry["key"]
    bib_text = _format_bib_entry(entry)
    context_text = "\n".join(
        f"  [{Path(c.tex_file).name}:{c.line_number}] {c.context}" for c in contexts
    )

    user_content = (
        f".bib reference:\n{bib_text}\n\n"
        f"Paragraph(s) citing this reference "
        f"(where \\cite{{{bib_key}}} appears in the .tex file):\n{context_text}"
    )

    client = OpenAI(api_key=settings.openai_api_key_citation_validator)
    response = client.responses.create(
        model="gpt-5.4-2026-03-05",
        instructions=_DEVELOPER_PROMPT,
        tools=[{"type": "web_search"}],
        input=[{"role": "user", "content": user_content}],
    )

    raw = response.output_text.strip() if hasattr(response, "output_text") else ""
    if not raw:
        return None

    # Strip markdown code fences if present
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        data = _json.loads(raw)
        return SemanticAssessment(**data)
    except Exception:
        return SemanticAssessment(
            reference_summary="",
            paragraph_context="",
            reasoning=raw,
            verdict=SemanticVerdict.UNCERTAIN,
            justification=raw,
        )


# ── Per-entry validation ───────────────────────────────────────────────────────


async def validate_entry(
    bib_key: str,
    entry: dict,
    tex_dir: Path,
    skip_semantic: bool,
) -> ValidationResult:
    result = ValidationResult(bib_key=bib_key)
    fields = entry.get("fields", {})

    doi = _strip_braces(fields.get("doi") or fields.get("DOI") or "")
    result.doi = doi or None
    result.title = _strip_braces(fields.get("title", "")) or None

    if doi:
        crossref = await fetch_crossref(doi)
        result.doi_resolves = bool(crossref)

        if not crossref:
            result.status = ValidationStatus.WARNING
        else:
            mismatches = compare_metadata(entry, crossref)
            result.metadata_mismatches = mismatches
            if mismatches:
                result.status = ValidationStatus.WARNING

    result.citation_contexts = extract_citation_contexts(bib_key, tex_dir)

    if not skip_semantic and result.citation_contexts:
        assessment = check_semantics(entry, result.citation_contexts)
        result.semantic_assessment = assessment
        if assessment:
            if assessment.verdict == SemanticVerdict.INCORRECT:
                result.status = ValidationStatus.ERROR
            elif (
                assessment.verdict == SemanticVerdict.UNCERTAIN
                and result.status == ValidationStatus.OK
            ):
                result.status = ValidationStatus.WARNING

    return result


# ── Main ───────────────────────────────────────────────────────────────────────


async def run(args: argparse.Namespace) -> int:
    tex_dir = Path(args.tex_dir).resolve()
    all_entries = parse_bib_files(tex_dir)

    bib_values: list[str] = args.bib or []

    if not bib_values:
        target_keys = get_modified_bib_keys(tex_dir)
        if not target_keys:
            print(
                "No modified .bib entries found in git diff. "
                "Use --bib all to validate every entry.",
                file=sys.stderr,
            )
            return 0
    elif bib_values == ["all"]:
        target_keys = set(all_entries.keys())
    else:
        target_keys = set(bib_values)

    for k in sorted(target_keys - set(all_entries.keys())):
        print(f"Warning: key '{k}' not found in any .bib file", file=sys.stderr)

    results: list[ValidationResult] = []
    for key in sorted(target_keys & set(all_entries.keys())):
        print(f"  Validating {key} ...", file=sys.stderr)
        results.append(await validate_entry(key, all_entries[key], tex_dir, args.no_semantic))

    report = Report(
        results=results,
        summary={
            "total": len(results),
            "ok": sum(1 for r in results if r.status == ValidationStatus.OK),
            "warnings": sum(1 for r in results if r.status == ValidationStatus.WARNING),
            "errors": sum(1 for r in results if r.status == ValidationStatus.ERROR),
        },
    )

    output = report.model_dump_json(indent=2)
    print(output)

    log_dir = Path.cwd() / "logs" / "citations"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{datetime.now().strftime('%Y%m%dT%H%M%S')}_citation_report.json"
    log_path.write_text(output, encoding="utf-8")
    print(f"Report saved to {log_path}", file=sys.stderr)

    return 1 if report.summary.get("errors", 0) > 0 else 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate BibTeX citations against CrossRef metadata and paper claims."
    )
    parser.add_argument(
        "tex_dir",
        nargs="?",
        default=".",
        metavar="tex-dir",
        help="Directory containing .bib and .tex files (default: .)",
    )
    parser.add_argument(
        "--bib",
        nargs="+",
        metavar="KEY",
        help="'all' to validate every entry, or one or more citation keys",
    )
    parser.add_argument(
        "--no-semantic",
        action="store_true",
        help="Skip OpenAI semantic checking (metadata-only, faster)",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
