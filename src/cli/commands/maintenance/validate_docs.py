"""Offline documentation smoke checks for current commands and stable workflows."""

from __future__ import annotations

import argparse
import re
from typing import List, Optional, Tuple

from src.cli.registry import COMMAND_GROUPS
from src.paths import REPO_ROOT

ACTIVE_DOCS = [REPO_ROOT / "README.md", *sorted((REPO_ROOT / "docs/experiments").glob("*.md"))]


def documented_cli_commands() -> List[Tuple[str, str]]:
    """Extract unified CLI commands referenced by active Markdown examples."""
    commands: List[Tuple[str, str]] = []
    pattern = re.compile(r"uv run risk-comm\s+([a-z0-9-]+)\s+([a-z0-9-]+)")
    for document in ACTIVE_DOCS:
        commands.extend(pattern.findall(document.read_text(encoding="utf-8")))
    return commands


def main(argv: Optional[List[str]] = None) -> None:
    """Require active workflow guides and every documented unified CLI command to exist."""
    argparse.ArgumentParser().parse_args(argv)
    required_documents = [
        REPO_ROOT / "CHANGELOG.md",
        REPO_ROOT / "docs/research-plan/RESEARCH_PLAN.md",
        REPO_ROOT / "docs/archive/REFERENCE_AUDIT.md",
        REPO_ROOT / "docs/experiments/scenario_workflow.md",
        REPO_ROOT / "docs/experiments/scenario_research.md",
        REPO_ROOT / "docs/experiments/experiment_execution.md",
        REPO_ROOT / "docs/experiments/scoring_and_validation.md",
        REPO_ROOT / "docs/experiments/analysis.md",
    ]
    missing = [str(path.relative_to(REPO_ROOT)) for path in required_documents if not path.exists()]
    unknown_commands = [
        f"risk-comm {group} {command}" for group, command in documented_cli_commands() if command not in COMMAND_GROUPS.get(group, {})
    ]
    missing.extend(unknown_commands)
    if missing:
        raise ValueError("documentation references missing paths or commands: " + ", ".join(sorted(set(missing))))
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    if any(value not in readme for value in ["240", "120", "60", "V0.11.0", "4.1.0"]):
        raise ValueError("README must identify the active seed/schema and exact experiment counts")
    print(f"Documentation smoke test passed for {len(required_documents)} active documents.")


if __name__ == "__main__":
    main()
