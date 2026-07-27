"""Regression tests for the decision logging hook."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from scripts.hooks import log_decisions


def test_extract_decisions_ignores_inline_markers_and_code_fenced_templates() -> None:
    """Only exact, substantive decision lines outside code fences should be extracted."""
    text = """The hook scans `Research decision:` and `Methodology decision:` markers.
```
Research decision: <decision and brief rationale>
Methodology decision: <decision and brief rationale>
```
Methodology decision: Use materiality scoring as the annotation rubric because it defines the paper's evaluation protocol.
"""

    entries = log_decisions._extract_decisions(
        text,
        source="transcript",
        author=log_decisions.AuthorType.CODEX,
        scope=log_decisions.DecisionScope.HIGH_LEVEL,
    )

    assert len(entries) == 1
    assert entries[0]["decision_type"] == "methodology"
    assert "materiality scoring" in str(entries[0]["content"])


def test_high_level_scope_rejects_low_level_implementation_decisions() -> None:
    """High-level scope should skip local file/script decisions."""
    text = "Methodology decision: Add scripts/foo.py because the hook needs a helper file."

    entries = log_decisions._extract_decisions(
        text,
        source="transcript",
        author=log_decisions.AuthorType.CODEX,
        scope=log_decisions.DecisionScope.HIGH_LEVEL,
    )

    assert entries == []


def test_high_level_scope_keeps_core_research_decisions() -> None:
    """High-level scope should keep durable benchmark and evaluation choices."""
    text = (
        "Research decision: Use FinanceBench-style company disclosures as a benchmark-selection source because they support "
        "realistic finance evidence and materiality evaluation."
    )

    entries = log_decisions._extract_decisions(
        text,
        source="transcript",
        author=log_decisions.AuthorType.CODEX,
        scope=log_decisions.DecisionScope.HIGH_LEVEL,
    )

    assert len(entries) == 1
    assert entries[0]["decision_type"] == "research"


def test_high_level_scope_keeps_scenario_treatment_decisions() -> None:
    """Keep scenario wording decisions that define an experimental condition."""
    text = (
        "Methodology decision: Seed v1.0.0 uses separately authored, non-leading neutral and concerned queries for every scenario; "
        "the concerned condition consistently says “really worried,” and both conditions share a generic follow-up."
    )

    entries = log_decisions._extract_decisions(
        text,
        source="transcript",
        author=log_decisions.AuthorType.CODEX,
        scope=log_decisions.DecisionScope.HIGH_LEVEL,
    )

    assert len(entries) == 1
    assert entries[0]["decision_type"] == "methodology"


def test_stop_processing_scans_only_latest_assistant_message() -> None:
    """Stop processing should not rescan user prompts or older assistant messages."""
    lines = [
        json.dumps(
            {
                "type": "user",
                "content": "Research decision: <decision and brief rationale>",
            }
        ),
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": ("Research decision: Use an older benchmark source because it shaped a previous study design."),
                        }
                    ],
                },
            }
        ),
        json.dumps(
            {
                "type": "user",
                "content": "Methodology decision: Add one scenario file because it is missing.",
            }
        ),
        json.dumps(
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "phase": "final_answer",
                    "content": [
                        {
                            "type": "output_text",
                            "text": (
                                "Methodology decision: Use materiality scoring as the annotation rubric because it defines "
                                "the paper's evaluation protocol."
                            ),
                        }
                    ],
                },
            }
        ),
    ]

    entries = log_decisions._extract_latest_assistant_decisions(
        lines,
        author=log_decisions.AuthorType.CODEX,
        scope=log_decisions.DecisionScope.HIGH_LEVEL,
    )

    assert len(entries) == 1
    assert entries[0]["decision_type"] == "methodology"
    assert "materiality scoring" in str(entries[0]["content"])


def test_stop_event_persists_a_current_codex_response_item(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Persist a marked decision from the current Codex desktop transcript envelope."""
    transcript_path = tmp_path / "transcript.jsonl"
    transcript_path.write_text(
        json.dumps(
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "phase": "final_answer",
                    "content": [
                        {
                            "type": "output_text",
                            "text": (
                                "Methodology decision: Use materiality scoring as the annotation rubric because it defines "
                                "the paper's evaluation protocol."
                            ),
                        }
                    ],
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    log_root = tmp_path / "decisions"
    monkeypatch.setattr(log_decisions, "_LOG_DIR", log_root)
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {
                    "hook_event_name": "Stop",
                    "transcript_path": str(transcript_path),
                }
            )
        ),
    )
    monkeypatch.setattr(sys, "argv", ["log_decisions.py", "--author", "codex", "--scope", "high-level"])

    log_decisions.main()

    decision_paths = list(log_root.glob("*_decision.json"))
    assert len(decision_paths) == 1
    decision = json.loads(decision_paths[0].read_text(encoding="utf-8"))
    assert decision["decision_type"] == "methodology"
    assert decision["author"] == "codex"
    assert "materiality scoring" in decision["content"]
