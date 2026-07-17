"""Synchronize the scenario-review requirement table from its canonical registry."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.data_models.scenario_review import (  # noqa: E402
    render_semantic_requirement_registry_markdown,
)

SCENARIO_GENERATION_DOC = REPO_ROOT / "docs" / "experiments" / "scenario_generation.md"
START_MARKER = "<!-- semantic-requirements:start -->"
END_MARKER = "<!-- semantic-requirements:end -->"


def synchronize_requirement_table(path: Path = SCENARIO_GENERATION_DOC) -> None:
    """Replace the marked documentation section with the canonical registry table."""
    content = path.read_text(encoding="utf-8")
    if content.count(START_MARKER) != 1 or content.count(END_MARKER) != 1:
        raise ValueError(
            "scenario-generation documentation must contain one requirement marker pair"
        )
    prefix, remainder = content.split(START_MARKER, maxsplit=1)
    _, suffix = remainder.split(END_MARKER, maxsplit=1)
    generated = render_semantic_requirement_registry_markdown()
    path.write_text(
        f"{prefix}{START_MARKER}\n\n{generated}\n\n{END_MARKER}{suffix}",
        encoding="utf-8",
    )


def main() -> int:
    """Synchronize the canonical requirement table and return success."""
    synchronize_requirement_table()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
