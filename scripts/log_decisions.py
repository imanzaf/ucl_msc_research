#!/usr/bin/env python3
"""log_decisions.py — Extracts and persists research/methodology decisions.

Called by Claude Code or Codex hooks on UserPromptSubmit and Stop events.
Reads the hook event JSON from stdin, extracts lines matching
"Research decision: ..." or "Methodology decision: ...", deduplicates
by content hash, and saves new entries to logs/decisions/.

Should be called with --author to specify the author.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from enum import Enum
from pathlib import Path


class DecisionType(str, Enum):
    RESEARCH = "research"
    METHODOLOGY = "methodology"


class AuthorType(str, Enum):
    USER = "user"
    CLAUDE = "claude"
    CODEX = "codex"


_PATTERNS: dict[str, DecisionType] = {
    "Research decision:": DecisionType.RESEARCH,
    "Methodology decision:": DecisionType.METHODOLOGY,
}

_LOG_DIR = Path("logs/decisions")


def _existing_hashes() -> set[str]:
    if not _LOG_DIR.exists():
        return set()
    hashes: set[str] = set()
    for f in _LOG_DIR.glob("*_decision.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if h := data.get("content_hash"):
                hashes.add(h)
        except Exception:
            pass
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


def _extract_decisions(text: str, source: str, author: AuthorType) -> list[dict]:
    entries = []
    for line in text.splitlines():
        for prefix, dtype in _PATTERNS.items():
            if prefix in line:
                content = line[line.index(prefix) + len(prefix) :].strip()
                if not content:
                    continue
                content_hash = hashlib.sha256(content.encode()).hexdigest()
                entries.append(
                    {
                        "schema_version": "1.0",
                        "timestamp": datetime.now().isoformat(timespec="seconds"),
                        "decision_type": dtype.value,
                        "author": author.value,
                        "content": content,
                        "source": source,
                        "content_hash": content_hash,
                    }
                )
    return entries


def _save(entry: dict) -> None:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    slug = entry["content_hash"][:8]
    path = _LOG_DIR / f"{ts}_{entry['decision_type']}_{slug}_decision.json"
    path.write_text(json.dumps(entry, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--author",
        choices=[a.value for a in AuthorType],
        default=None,
        help="Override inferred author (user | claude | codex)",
    )
    args, _ = parser.parse_known_args()

    try:
        event = json.loads(sys.stdin.read())
    except Exception:
        sys.exit(0)

    existing = _existing_hashes()
    candidates: list[dict] = []
    event_name = event.get("hook_event_name", "")

    if event_name == "UserPromptSubmit":
        author = AuthorType(args.author) if args.author else AuthorType.USER
        prompt = event.get("prompt", "")
        candidates = _extract_decisions(prompt, source="user_prompt", author=author)

    elif event_name == "Stop":
        transcript_path = event.get("transcript_path", "")
        if transcript_path and Path(transcript_path).exists():
            try:
                lines = Path(transcript_path).read_text(encoding="utf-8").splitlines()
                author = AuthorType(args.author) if args.author else AuthorType.CLAUDE

                if author == AuthorType.CLAUDE:
                    # Only scan the most recent assistant message to avoid
                    # re-processing the full conversation history on every turn
                    for line in reversed(lines):
                        try:
                            msg = json.loads(line)
                            if msg.get("type") == "assistant":
                                candidates = _extract_decisions(
                                    _extract_text(msg), source="transcript", author=author
                                )
                                break
                        except Exception:
                            continue
                else:
                    for line in lines:
                        try:
                            msg = json.loads(line)
                        except Exception:
                            continue
                        role = msg.get("type", "")
                        msg_author = (
                            author
                            if args.author
                            else (AuthorType.CLAUDE if role == "assistant" else AuthorType.USER)
                        )
                        candidates.extend(
                            _extract_decisions(
                                _extract_text(msg), source="transcript", author=msg_author
                            )
                        )
            except Exception:
                pass

    for entry in candidates:
        if entry["content_hash"] not in existing:
            _save(entry)
            existing.add(entry["content_hash"])


if __name__ == "__main__":
    main()
