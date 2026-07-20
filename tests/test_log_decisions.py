"""Regression tests for the decision logging hook."""

from __future__ import annotations

import json

from scripts import log_decisions


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
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
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
