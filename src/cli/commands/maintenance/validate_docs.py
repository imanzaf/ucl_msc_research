"""Offline documentation smoke checks for current commands and required runbooks."""

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
    pattern = re.compile(r"uv run risk-comm\s+([a-z-]+)\s+([a-z-]+)")
    for document in ACTIVE_DOCS:
        commands.extend(pattern.findall(document.read_text(encoding="utf-8")))
    return commands


def main(argv: Optional[List[str]] = None) -> None:
    """Require active runbooks and every documented unified CLI command to exist."""
    argparse.ArgumentParser().parse_args(argv)
    required_documents = [
        REPO_ROOT / "CHANGELOG.md",
        REPO_ROOT / "docs/research-plan/RESEARCH_PLAN.md",
        REPO_ROOT / "docs/research-plan/REFERENCE_AUDIT.md",
        REPO_ROOT / "docs/experiments/scenario_generation_v0_5_2.md",
        REPO_ROOT / "docs/experiments/review_and_annotation.md",
        REPO_ROOT / "docs/experiments/scoring.md",
        REPO_ROOT / "docs/experiments/calibration.md",
        REPO_ROOT / "docs/experiments/analysis.md",
        REPO_ROOT / "docs/experiments/risk_comm_v1.md",
        REPO_ROOT / "docs/experiments/material_priority_v1.md",
        REPO_ROOT / "docs/experiments/brevity_locus_v1.md",
    ]
    missing = [str(path.relative_to(REPO_ROOT)) for path in required_documents if not path.exists()]
    unknown_commands = [
        f"risk-comm {group} {command}" for group, command in documented_cli_commands() if command not in COMMAND_GROUPS.get(group, {})
    ]
    missing.extend(unknown_commands)
    if missing:
        raise ValueError("documentation references missing paths or commands: " + ", ".join(sorted(set(missing))))
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    if any(value not in readme for value in ["480", "240", "120", "V0.5.2", "2.0.0"]):
        raise ValueError("README must identify the active seed/schema and exact experiment counts")
    print(f"Documentation smoke test passed for {len(required_documents)} active documents.")


if __name__ == "__main__":
    main()
