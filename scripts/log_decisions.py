#!/usr/bin/env python3
"""log_decisions.py - Extracts and persists research/methodology decisions.

Called by Claude Code or Codex hooks on UserPromptSubmit and Stop events.
Reads the hook event JSON from stdin, extracts lines matching
"Research decision: ..." or "Methodology decision: ...", deduplicates
by content hash, and saves new entries to logs/decisions/.

The default high-level scope keeps the log focused on dissertation-level
research direction and core methodology choices.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple


class DecisionType(str, Enum):
    RESEARCH = "research"
    METHODOLOGY = "methodology"


class AuthorType(str, Enum):
    USER = "user"
    CLAUDE = "claude"
    CODEX = "codex"


class DecisionScope(str, Enum):
    ALL = "all"
    HIGH_LEVEL = "high-level"


_PATTERNS: Dict[str, DecisionType] = {
    "Research decision:": DecisionType.RESEARCH,
    "Methodology decision:": DecisionType.METHODOLOGY,
}

_LOG_DIR = Path("logs/decisions")

_PATH_OR_FILE_PATTERN = re.compile(
    r"(^|\s)(\.?/?[\w.-]+/[\w./-]+|[\w.-]+\.(py|md|json|jsonl|tex|csv|xlsx|toml|yaml|yml))\b",
    re.IGNORECASE,
)

_HIGH_LEVEL_TERMS = (
    "ablation",
    "annotation",
    "auditability",
    "baseline",
    "benchmark",
    "dataset",
    "deception",
    "disclosure",
    "dissertation",
    "evaluation",
    "experiment design",
    "experimental design",
    "experimental protocol",
    "finance",
    "falsifiability",
    "framing",
    "hypothesis",
    "janus",
    "materiality",
    "metric",
    "methodology",
    "model family",
    "model selection",
    "nudge",
    "paper",
    "persona",
    "protocol",
    "research direction",
    "research question",
    "risk-unit",
    "rubric",
    "sampling",
    "scenario-family",
    "scoring",
    "stakeholder",
    "study",
)

_LOW_LEVEL_TERMS = (
    "add file",
    "added file",
    "bug fix",
    "cleanup",
    "commit",
    "dependency",
    "docstring",
    "docs",
    "file added",
    "hook",
    "implementation",
    "log file",
    "module",
    "pre-commit",
    "readme",
    "refactor",
    "rename",
    "script",
    "test",
)

_TEMPLATE_FRAGMENTS = (
    "<decision and brief rationale>",
    "do not paraphrase or vary",
    "keep each decision on a single line",
    "methodology decision:",
    "research decision:",
)


DecisionEntry = Dict[str, object]


def _existing_hashes() -> Set[str]:
    """Return content hashes that have already been written to the decision log."""
    if not _LOG_DIR.exists():
        return set()
    hashes: Set[str] = set()
    for path in _LOG_DIR.glob("*_decision.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        content_hash = data.get("content_hash")
        if isinstance(content_hash, str):
            hashes.add(content_hash)
    return hashes


def _extract_text(obj: object) -> str:
    """Recursively pull all string values out of a nested dict/list."""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, list):
        return "\n".join(_extract_text(i) for i in obj)
    if isinstance(obj, dict):
        return "\n".join(_extract_text(v) for v in obj.values())
    return ""


def _iter_decision_candidates(text: str) -> Iterable[Tuple[DecisionType, str]]:
    """Yield exact decision lines while ignoring code-fenced templates."""
    in_code_fence = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_fence = not in_code_fence
            continue
        if in_code_fence:
            continue
        for prefix, dtype in _PATTERNS.items():
            if stripped.startswith(prefix):
                yield dtype, stripped[len(prefix) :].strip()


def _is_template_or_instruction(content: str) -> bool:
    """Return whether extracted text is an instruction/template rather than a decision."""
    normalized = " ".join(content.split()).lower()
    if not normalized:
        return True
    if normalized in {"...", "<...>"}:
        return True
    return any(fragment in normalized for fragment in _TEMPLATE_FRAGMENTS)


def _contains_any(content: str, terms: Tuple[str, ...]) -> bool:
    """Return whether normalized content contains any term in a tuple."""
    return any(term in content for term in terms)


def _is_high_level_decision(content: str) -> bool:
    """Return whether a candidate looks like a durable research or methodology decision."""
    normalized = content.lower()
    has_high_level_term = _contains_any(normalized, _HIGH_LEVEL_TERMS)
    if has_high_level_term:
        return True
    if _PATH_OR_FILE_PATTERN.search(content):
        return False
    if _contains_any(normalized, _LOW_LEVEL_TERMS):
        return False
    if "scenario" in normalized:
        return False
    return True


def _should_log_content(content: str, scope: DecisionScope) -> bool:
    """Return whether candidate content should be persisted under the requested scope."""
    if _is_template_or_instruction(content):
        return False
    if scope == DecisionScope.HIGH_LEVEL:
        return _is_high_level_decision(content)
    return True


def _build_entry(
    dtype: DecisionType, content: str, source: str, author: AuthorType
) -> DecisionEntry:
    """Build a serializable decision-log entry."""
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "decision_type": dtype.value,
        "author": author.value,
        "content": content,
        "source": source,
        "content_hash": content_hash,
    }


def _extract_decisions(
    text: str,
    source: str,
    author: AuthorType,
    scope: DecisionScope = DecisionScope.HIGH_LEVEL,
) -> List[DecisionEntry]:
    """Extract decision entries from exact one-line decision markers."""
    entries: List[DecisionEntry] = []
    for dtype, content in _iter_decision_candidates(text):
        if _should_log_content(content, scope):
            entries.append(_build_entry(dtype, content, source, author))
    return entries


def _message_role(message: Dict[str, object]) -> str:
    """Infer the role from common Claude/Codex transcript message shapes."""
    for key in ("type", "role"):
        value = message.get(key)
        if value in {"assistant", "user"}:
            return str(value)

    nested_message = message.get("message")
    if isinstance(nested_message, dict):
        nested_role = nested_message.get("role")
        if nested_role in {"assistant", "user"}:
            return str(nested_role)

    return ""


def _message_text(message: Dict[str, object]) -> str:
    """Extract only the user-visible text payload from a transcript message."""
    nested_message = message.get("message")
    if isinstance(nested_message, dict):
        if "content" in nested_message:
            return _extract_text(nested_message["content"])
        return _extract_text(nested_message)
    if "content" in message:
        return _extract_text(message["content"])
    return _extract_text(message)


def _latest_assistant_text(lines: List[str]) -> Optional[str]:
    """Return the text of the most recent assistant message in a JSONL transcript."""
    for line in reversed(lines):
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(message, dict) and _message_role(message) == "assistant":
            return _message_text(message)
    return None


def _extract_latest_assistant_decisions(
    lines: List[str], author: AuthorType, scope: DecisionScope
) -> List[DecisionEntry]:
    """Extract decisions from only the most recent assistant response."""
    text = _latest_assistant_text(lines)
    if text is None:
        return []
    return _extract_decisions(text, source="transcript", author=author, scope=scope)


def _save(entry: DecisionEntry) -> None:
    """Persist one decision entry to the decision log directory."""
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    slug = str(entry["content_hash"])[:8]
    path = _LOG_DIR / f"{ts}_{entry['decision_type']}_{slug}_decision.json"
    path.write_text(json.dumps(entry, indent=2), encoding="utf-8")


def main() -> None:
    """Parse a hook event from stdin and persist any qualifying decision entries."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--author",
        choices=[a.value for a in AuthorType],
        default=None,
        help="Override inferred author (user | claude | codex)",
    )
    parser.add_argument(
        "--scope",
        choices=[scope.value for scope in DecisionScope],
        default=DecisionScope.HIGH_LEVEL.value,
        help="Filter level for persisted decisions (high-level | all)",
    )
    args, _ = parser.parse_known_args()
    scope = DecisionScope(args.scope)

    try:
        event = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        sys.exit(0)

    existing = _existing_hashes()
    candidates: List[DecisionEntry] = []
    event_name = event.get("hook_event_name", "")

    if event_name == "UserPromptSubmit":
        author = AuthorType(args.author) if args.author else AuthorType.USER
        prompt = event.get("prompt", "")
        if isinstance(prompt, str):
            candidates = _extract_decisions(
                prompt, source="user_prompt", author=author, scope=scope
            )

    elif event_name == "Stop":
        transcript_path = event.get("transcript_path", "")
        if isinstance(transcript_path, str) and transcript_path and Path(transcript_path).exists():
            try:
                lines = Path(transcript_path).read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                lines = []
            author = AuthorType(args.author) if args.author else AuthorType.CLAUDE
            candidates = _extract_latest_assistant_decisions(lines, author=author, scope=scope)

    for entry in candidates:
        if entry["content_hash"] not in existing:
            _save(entry)
            existing.add(entry["content_hash"])


if __name__ == "__main__":
    main()
