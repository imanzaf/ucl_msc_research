#!/usr/bin/env python3
"""audit_research.py — Agentic research integrity auditor.

Orchestrates a multi-agent loop that extracts claims from a research paper,
then autonomously navigates the repository and result files to verify each
claim is grounded in actual code and experimental output.

All file access is read-only. The agent never writes to the repository.

Usage:
    uv run python .claude/skills/research-auditor/scripts/audit_research.py [options]
"""

from __future__ import annotations

import ast
import json
import re
import sys
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

from openai import OpenAI
from pydantic import BaseModel, Field

from src.settings import get_api_settings

settings = get_api_settings()

_MODEL = "gpt-5.5-pro-2026-04-23"
_MAX_VERIFICATION_TURNS = 20
_MAX_FILE_BYTES = 60_000
_LOG_DIR = Path("logs/research_audits")

_RESULT_EXTENSIONS = {".json", ".jsonl", ".csv", ".log", ".txt", ".npy", ".npz", ".pkl"}
_RESULT_DIR_NAMES = {
    "outputs",
    "logs",
    "results",
    "checkpoints",
    "metrics",
    "eval",
    "runs",
    "experiments",
}
_SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules", ".mypy_cache", ".ruff_cache"}


# ── Enums ──────────────────────────────────────────────────────────────────────


class ClaimType(str, Enum):
    METRIC = "metric"  # quantitative result (e.g. 94.2% accuracy)
    METHODOLOGY = "methodology"  # process or design claim
    DATASET = "dataset"  # data source or size claim
    FINDING = "finding"  # qualitative research finding
    COMPARISON = "comparison"  # comparison to baseline or prior work


class ClaimStatus(str, Enum):
    CONFIRMED = "confirmed"  # evidence found, claim verified
    CONTRADICTED = "contradicted"  # evidence found, claim is wrong
    UNVERIFIABLE = "unverifiable"  # relevant code/logs exist but claim cannot be confirmed
    NOT_FOUND = "not_found"  # no relevant code or logs located


# ── Data models ─────────────────────────────────────────────────────────────────


class Claim(BaseModel):
    """A single verifiable claim extracted from the paper."""

    id: int
    text: str = Field(description="The exact claim as stated in the paper")
    claim_type: ClaimType
    expected_value: Optional[str] = Field(
        default=None,
        description="The quantitative value if this is a metric claim (e.g. '94.2%')",
    )
    search_hints: List[str] = Field(
        description="Keywords, function names, or variable names likely to appear in code/logs for this claim",
    )


class ClaimList(BaseModel):
    """Structured list of claims extracted from a paper."""

    schema_version: str = "1.0"
    claims: List[Claim]


class ClaimVerification(BaseModel):
    """Verification result for a single claim."""

    schema_version: str = "1.0"
    claim_id: int
    claim_text: str
    claim_type: ClaimType
    status: ClaimStatus
    evidence: List[str] = Field(
        description="File paths and line numbers where evidence was found (e.g. 'src/eval.py:42')",
    )
    found_value: Optional[str] = Field(
        default=None,
        description="The actual value found in code or logs, if applicable",
    )
    reasoning: str = Field(description="Step-by-step explanation of how the verdict was reached")


class AuditReport(BaseModel):
    """Full research integrity audit report."""

    schema_version: str = "1.0"
    paper_file: str
    repo_path: str
    timestamp: str
    model: str
    total_claims: int
    confirmed: int
    contradicted: int
    unverifiable: int
    not_found: int
    integrity_score: float = Field(description="confirmed / total_claims, 0.0–1.0")
    verifications: List[ClaimVerification]
    summary: str


# ── Read-only file system tools ────────────────────────────────────────────────


def list_directory(path: str) -> str:
    """List files and subdirectories at the given path.

    Args:
        path: Directory path to list.
    """
    p = Path(path)
    if not p.exists():
        return f"Error: path not found: {path}"
    if not p.is_dir():
        return f"Error: not a directory: {path}"
    entries = []
    for entry in sorted(p.iterdir()):
        tag = "/" if entry.is_dir() else ""
        entries.append(f"  {entry.name}{tag}")
    return f"{path}:\n" + "\n".join(entries) if entries else f"{path}: (empty)"


def read_file(path: str, start_line: int = 1, end_line: int = 150) -> str:
    """Read lines from a file within a specified range.

    Args:
        path: File path.
        start_line: First line to read (1-indexed).
        end_line: Last line to read (inclusive).
    """
    p = Path(path)
    if not p.exists():
        return f"Error: file not found: {path}"
    if not p.is_file():
        return f"Error: not a file: {path}"
    try:
        raw = p.read_bytes()[:_MAX_FILE_BYTES]
        lines = raw.decode("utf-8", errors="replace").splitlines()
        selected = lines[max(0, start_line - 1) : end_line]
        numbered = [f"{start_line + i:>6}: {line}" for i, line in enumerate(selected)]
        header = f"[{path} lines {start_line}–{min(end_line, len(lines))} of {len(lines)}]\n"
        return header + "\n".join(numbered)
    except OSError as e:
        return f"Error reading {path}: {e}"


def search_repo(pattern: str, extensions: List[str], directory: str = ".") -> str:
    """Search for a regex pattern across files in the repository.

    Args:
        pattern: Regex pattern to search for.
        extensions: List of file extensions to search (e.g. ['.py', '.json']).
        directory: Root directory to search from.
    """
    root = Path(directory)
    if not root.exists():
        return f"Error: directory not found: {directory}"
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return f"Error: invalid regex '{pattern}': {e}"

    matches = []
    for ext in extensions:
        for filepath in sorted(root.rglob(f"*{ext}")):
            if any(skip in filepath.parts for skip in _SKIP_DIRS):
                continue
            try:
                content = filepath.read_bytes()[:_MAX_FILE_BYTES].decode("utf-8", errors="replace")
                for lineno, line in enumerate(content.splitlines(), 1):
                    if regex.search(line):
                        matches.append(f"  {filepath}:{lineno}: {line.strip()}")
                        if len(matches) >= 50:
                            return "\n".join(matches) + "\n... (truncated at 50 matches)"
            except OSError:
                continue

    return (
        "\n".join(matches)
        if matches
        else f"No matches for '{pattern}' in {extensions} under {directory}"
    )


def parse_python_ast(file_path: str) -> str:
    """Parse a Python file and return its function and class structure.

    Args:
        file_path: Path to the Python file.
    """
    p = Path(file_path)
    if not p.exists():
        return f"Error: file not found: {file_path}"
    try:
        source = p.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
    except (OSError, SyntaxError) as e:
        return f"Error parsing {file_path}: {e}"

    items = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = [a.arg for a in node.args.args]
            items.append(f"  def {node.name}({', '.join(args)})  [line {node.lineno}]")
        elif isinstance(node, ast.ClassDef):
            items.append(f"  class {node.name}  [line {node.lineno}]")

    return (
        f"[{file_path}]\n" + "\n".join(items)
        if items
        else f"[{file_path}] No functions or classes found"
    )


def find_result_files(directory: str = ".") -> str:
    """Find result and log files in the repository (outputs, logs, CSVs, JSONs).

    Args:
        directory: Root directory to search from.
    """
    root = Path(directory)
    found = []
    for path in sorted(root.rglob("*")):
        if any(skip in path.parts for skip in _SKIP_DIRS):
            continue
        if not path.is_file():
            continue
        in_result_dir = any(part.lower() in _RESULT_DIR_NAMES for part in path.parts)
        has_result_ext = path.suffix.lower() in _RESULT_EXTENSIONS
        if in_result_dir or has_result_ext:
            size_kb = path.stat().st_size // 1024
            found.append(f"  {path}  ({size_kb}KB)")
    return "\n".join(found) if found else f"No result files found under {directory}"


def read_json_result(file_path: str) -> str:
    """Read and pretty-print the contents of a JSON or JSONL result file.

    Args:
        file_path: Path to the result file.
    """
    p = Path(file_path)
    if not p.exists():
        return f"Error: file not found: {file_path}"
    try:
        raw = p.read_bytes()[:_MAX_FILE_BYTES].decode("utf-8", errors="replace")
        if p.suffix == ".jsonl":
            lines = [json.loads(ln) for ln in raw.splitlines() if ln.strip()]
            return json.dumps(lines[:50], indent=2) + (
                "\n... (truncated)" if len(lines) > 50 else ""
            )
        data = json.loads(raw)
        return json.dumps(data, indent=2)[:8_000]
    except (OSError, json.JSONDecodeError) as e:
        return f"Error reading {file_path}: {e}"


# ── Tool registry ──────────────────────────────────────────────────────────────

_TOOL_FN_MAP: Dict[str, object] = {
    "list_directory": list_directory,
    "read_file": read_file,
    "search_repo": search_repo,
    "parse_python_ast": parse_python_ast,
    "find_result_files": find_result_files,
    "read_json_result": read_json_result,
}

_FILE_TOOLS = [
    {
        "type": "function",
        "name": "list_directory",
        "description": "List files and subdirectories at a path",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "type": "function",
        "name": "read_file",
        "description": "Read lines from a file",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start_line": {"type": "integer", "default": 1},
                "end_line": {"type": "integer", "default": 150},
            },
            "required": ["path"],
        },
    },
    {
        "type": "function",
        "name": "search_repo",
        "description": "Search for a regex pattern across files with given extensions",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "extensions": {"type": "array", "items": {"type": "string"}},
                "directory": {"type": "string", "default": "."},
            },
            "required": ["pattern", "extensions"],
        },
    },
    {
        "type": "function",
        "name": "parse_python_ast",
        "description": "Return the function and class structure of a Python file",
        "parameters": {
            "type": "object",
            "properties": {"file_path": {"type": "string"}},
            "required": ["file_path"],
        },
    },
    {
        "type": "function",
        "name": "find_result_files",
        "description": "Find result, log, and output files in the repository",
        "parameters": {
            "type": "object",
            "properties": {"directory": {"type": "string", "default": "."}},
            "required": [],
        },
    },
    {
        "type": "function",
        "name": "read_json_result",
        "description": "Read and return the contents of a JSON or JSONL result file",
        "parameters": {
            "type": "object",
            "properties": {"file_path": {"type": "string"}},
            "required": ["file_path"],
        },
    },
]


def _dispatch_tool(name: str, arguments: dict) -> str:
    """Execute a tool call by name and return its string result."""
    fn = _TOOL_FN_MAP.get(name)
    if fn is None:
        return f"Error: unknown tool '{name}'"
    try:
        return str(fn(**arguments))  # type: ignore[operator]
    except TypeError as e:
        return f"Error calling {name}: {e}"


def _run_tool_loop(
    client: OpenAI,
    system: str,
    initial_message: str,
    tools: List[dict],
    terminal_tool: Optional[str] = None,
    max_turns: int = _MAX_VERIFICATION_TURNS,
) -> dict:
    """Run an agentic tool-use loop until the agent calls the terminal tool or runs out of turns.

    Args:
        client: OpenAI client.
        system: System/instructions prompt.
        initial_message: First user message.
        tools: Tool definitions available to the agent.
        terminal_tool: If set, stop the loop when this tool is called and return its arguments.
        max_turns: Maximum tool-call rounds before giving up.
    """
    input_messages: List[dict] = [{"role": "user", "content": initial_message}]

    for turn in range(max_turns):
        response = client.responses.create(  # type: ignore[call-overload]
            model=_MODEL,
            instructions=system,
            reasoning={"effort": "high"},
            tools=tools,  # type: ignore[arg-type]
            input=input_messages,  # type: ignore[arg-type]
        )

        # Accumulate response output into the conversation
        input_messages += response.output  # type: ignore[operator]

        tool_calls = [
            item for item in response.output if getattr(item, "type", None) == "function_call"
        ]

        if not tool_calls:
            # Agent produced text output only — return it
            return {"text": response.output_text or ""}

        for call in tool_calls:
            name: str = getattr(call, "name", "")
            raw_args: str = getattr(call, "arguments", "") or ""
            call_id: str = getattr(call, "call_id", "")
            args = json.loads(raw_args) if raw_args else {}

            if terminal_tool and name == terminal_tool:
                return args

            result = _dispatch_tool(name, args)
            input_messages.append(
                {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": result,
                }
            )

    return {"text": "Max turns reached without conclusion."}


# ── Phase 1: Claim extraction ──────────────────────────────────────────────────

_SUPERVISOR_EXTRACT_SYSTEM = """\
You are a research integrity supervisor. Your task is to read a research paper and extract \
every specific, verifiable claim it makes. Focus on:
- Quantitative metrics (accuracy, F1, loss, latency, etc.)
- Methodological choices that could be traced to code
- Dataset sizes, sources, and processing steps
- Comparisons to baselines or prior work
- Key qualitative findings that could be supported by logs

For each claim, provide concrete search_hints: variable names, function names, or keywords \
that are likely to appear in the codebase or result files when implementing that claim. \
Call submit_claims with the complete structured list.
"""


def extract_claims(client: OpenAI, paper_text: str) -> ClaimList:
    """Phase 1: Extract structured verifiable claims from the paper text.

    Args:
        client: OpenAI client.
        paper_text: Full text of the research paper.
    """
    submit_tool = {
        "type": "function",
        "name": "submit_claims",
        "description": "Submit the structured list of extracted claims",
        "parameters": ClaimList.model_json_schema(),
    }

    result = _run_tool_loop(
        client=client,
        system=_SUPERVISOR_EXTRACT_SYSTEM,
        initial_message=f"Extract all verifiable claims from this paper:\n\n{paper_text[:40_000]}",
        tools=[submit_tool],
        terminal_tool="submit_claims",
        max_turns=3,
    )

    if "claims" in result:
        return ClaimList.model_validate(result)
    raise RuntimeError(f"Claim extraction failed: {result}")


# ── Phase 2: Per-claim verification ───────────────────────────────────────────

_VERIFIER_SYSTEM = """\
You are a research integrity verifier. You have read-only access to a software repository \
and its result files. Your job is to verify a single claim from a research paper by \
autonomously navigating the codebase and logs.

Verification procedure:
1. Use list_directory and find_result_files to understand the repo structure
2. Use search_repo to locate relevant code using the provided search hints
3. Use read_file to inspect the relevant code and understand the logic
4. Use parse_python_ast to navigate large Python files efficiently
5. Use find_result_files and read_json_result to locate and inspect experiment outputs
6. Compare what the code and logs show against the claim

Once you have gathered sufficient evidence, call submit_verdict with your findings. \
Be precise: quote exact file paths and line numbers. If a numeric claim says 94.2% \
and you find 0.9419 in a log, that rounds correctly — confirm it.

You have read-only access. Never attempt to write, execute, or modify any files.
"""

_SUBMIT_VERDICT_TOOL = {
    "type": "function",
    "name": "submit_verdict",
    "description": "Submit the final verification verdict for this claim",
    "parameters": ClaimVerification.model_json_schema(),
}


def verify_claim(client: OpenAI, claim: Claim, repo_path: Path) -> ClaimVerification:
    """Phase 2: Verify a single claim against the repository.

    Args:
        client: OpenAI client.
        claim: The claim to verify.
        repo_path: Root path of the repository.
    """
    message = (
        f"Verify this claim from the research paper:\n\n"
        f"Claim #{claim.id}: {claim.text}\n"
        f"Type: {claim.claim_type.value}\n"
        f"Expected value: {claim.expected_value or 'N/A'}\n"
        f"Search hints: {', '.join(claim.search_hints)}\n"
        f"Repository root: {repo_path}\n\n"
        f"Navigate the repository and result files to verify this claim. "
        f"Call submit_verdict when you have a conclusion."
    )

    result = _run_tool_loop(
        client=client,
        system=_VERIFIER_SYSTEM,
        initial_message=message,
        tools=_FILE_TOOLS + [_SUBMIT_VERDICT_TOOL],
        terminal_tool="submit_verdict",
        max_turns=_MAX_VERIFICATION_TURNS,
    )

    if "claim_id" in result:
        return ClaimVerification.model_validate(result)

    # Agent ran out of turns or returned text — produce a fallback verdict
    return ClaimVerification(
        claim_id=claim.id,
        claim_text=claim.text,
        claim_type=claim.claim_type,
        status=ClaimStatus.UNVERIFIABLE,
        evidence=[],
        found_value=None,
        reasoning=result.get("text", "Verification loop did not produce a verdict."),
    )


# ── Phase 3: Report compilation ────────────────────────────────────────────────


def compile_report(
    verifications: List[ClaimVerification],
    paper_file: str,
    repo_path: str,
) -> AuditReport:
    """Compile all claim verifications into a final audit report.

    Args:
        verifications: List of per-claim verification results.
        paper_file: Path to the paper file.
        repo_path: Path to the repository root.
    """
    total = len(verifications)
    confirmed = sum(1 for v in verifications if v.status == ClaimStatus.CONFIRMED)
    contradicted = sum(1 for v in verifications if v.status == ClaimStatus.CONTRADICTED)
    unverifiable = sum(1 for v in verifications if v.status == ClaimStatus.UNVERIFIABLE)
    not_found = sum(1 for v in verifications if v.status == ClaimStatus.NOT_FOUND)
    score = confirmed / total if total > 0 else 0.0

    issues = [
        v for v in verifications if v.status in (ClaimStatus.CONTRADICTED, ClaimStatus.NOT_FOUND)
    ]
    if not issues:
        summary = f"All {confirmed}/{total} claims verified. Integrity score: {score:.0%}."
    else:
        summary = (
            f"{confirmed}/{total} claims confirmed. "
            f"{contradicted} contradicted, {not_found} not found. "
            f"Integrity score: {score:.0%}. "
            f"Issues: {', '.join(v.claim_text[:60] for v in issues[:3])}."
        )

    return AuditReport(
        schema_version="1.0",
        paper_file=paper_file,
        repo_path=repo_path,
        timestamp=datetime.now().isoformat(timespec="seconds"),
        model=_MODEL,
        total_claims=total,
        confirmed=confirmed,
        contradicted=contradicted,
        unverifiable=unverifiable,
        not_found=not_found,
        integrity_score=round(score, 4),
        verifications=verifications,
        summary=summary,
    )


# ── Save and print ─────────────────────────────────────────────────────────────


def _save(report: AuditReport) -> Path:
    """Save the audit report as JSON to the log directory."""
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    path = _LOG_DIR / f"{ts}_audit_report.json"
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return path


def _print_report(report: AuditReport) -> None:
    """Print a human-readable summary of the audit report."""
    bar = "─" * 60
    print(f"\n{bar}")
    print(f"RESEARCH INTEGRITY AUDIT — {report.timestamp}")
    print(f"Paper:  {report.paper_file}")
    print(f"Repo:   {report.repo_path}")
    print(f"Model:  {report.model}")
    print(bar)
    print(f"Claims audited : {report.total_claims}")
    print(f"  ✓ Confirmed  : {report.confirmed}")
    print(f"  ✗ Contradicted: {report.contradicted}")
    print(f"  ? Unverifiable: {report.unverifiable}")
    print(f"  ○ Not found  : {report.not_found}")
    print(f"Integrity score: {report.integrity_score:.0%}")
    print(bar)

    for v in report.verifications:
        icon = {"confirmed": "✓", "contradicted": "✗", "unverifiable": "?", "not_found": "○"}[
            v.status.value
        ]
        print(f"\n{icon} [{v.claim_type.value}] {v.claim_text[:80]}")
        if v.found_value:
            print(f"   Found: {v.found_value}")
        if v.evidence:
            for e in v.evidence[:3]:
                print(f"   → {e}")
        print(f"   {v.reasoning[:200]}")

    print(f"\n{bar}")
    print(f"Summary: {report.summary}")


# ── Main ───────────────────────────────────────────────────────────────────────


def main() -> None:
    """Entry point: parse args, run the audit, save and print the report."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Agentic research integrity auditor — verifies paper claims against the repo."
    )
    parser.add_argument(
        "--paper",
        required=True,
        type=Path,
        metavar="FILE",
        help=".tex file of the research paper or dissertation",
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path("."),
        metavar="DIR",
        help="Repository root to audit (default: .)",
    )
    parser.add_argument(
        "--max-claims",
        type=int,
        default=20,
        metavar="N",
        help="Maximum number of claims to verify (default: 20)",
    )
    args = parser.parse_args()

    if not args.paper.exists():
        print(f"Error: paper file not found: {args.paper}", file=sys.stderr)
        sys.exit(1)
    if not args.repo.is_dir():
        print(f"Error: repo directory not found: {args.repo}", file=sys.stderr)
        sys.exit(1)

    client = OpenAI(api_key=settings.openai_api_key_research_auditor)
    paper_text = args.paper.read_text(encoding="utf-8", errors="replace")

    print(f"Phase 1: Extracting claims from {args.paper} …", file=sys.stderr)
    claim_list = extract_claims(client, paper_text)
    claims = claim_list.claims[: args.max_claims]
    print(f"  Extracted {len(claims)} claims", file=sys.stderr)

    verifications: List[ClaimVerification] = []
    for i, claim in enumerate(claims, 1):
        print(f"Phase 2: Verifying claim {i}/{len(claims)}: {claim.text[:60]} …", file=sys.stderr)
        verification = verify_claim(client, claim, args.repo.resolve())
        verifications.append(verification)
        print(f"  → {verification.status.value}", file=sys.stderr)

    print("Phase 3: Compiling report …", file=sys.stderr)
    report = compile_report(verifications, str(args.paper), str(args.repo))

    _print_report(report)
    log_path = _save(report)
    print(f"\nFull report saved to {log_path}", file=sys.stderr)

    if report.contradicted > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
