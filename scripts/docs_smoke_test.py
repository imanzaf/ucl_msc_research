"""Offline documentation smoke checks for V9 commands and navigable source paths."""

from __future__ import annotations

import re
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parents[1]
ACTIVE_DOCS = [REPO_ROOT / "README.md", *sorted((REPO_ROOT / "docs/experiments").glob("*.md"))]


def documented_script_paths() -> List[Path]:
    """Extract scripts referenced by active Markdown command examples."""
    paths: List[Path] = []
    pattern = re.compile(r"(?:uv run python|streamlit run)\s+(scripts/[A-Za-z0-9_./-]+\.py)")
    for document in ACTIVE_DOCS:
        for relative_path in pattern.findall(document.read_text(encoding="utf-8")):
            paths.append(REPO_ROOT / relative_path)
    return paths


def main() -> None:
    """Require every active runbook and documented script path to exist."""
    required_documents = [
        REPO_ROOT / "docs/research-plan/RESEARCH_PLAN_V9.md",
        REPO_ROOT / "docs/research-plan/V9_REFERENCE_AUDIT.md",
        REPO_ROOT / "docs/experiments/scenario_generation_v0_5_1.md",
        REPO_ROOT / "docs/experiments/review_and_annotation.md",
        REPO_ROOT / "docs/experiments/scoring_v9.md",
        REPO_ROOT / "docs/experiments/calibration_v9.md",
        REPO_ROOT / "docs/experiments/analysis_v9.md",
        REPO_ROOT / "docs/experiments/risk_comm_v1.md",
    ]
    missing = [str(path.relative_to(REPO_ROOT)) for path in required_documents if not path.exists()]
    missing.extend(str(path.relative_to(REPO_ROOT)) for path in documented_script_paths() if not path.exists())
    if missing:
        raise ValueError("documentation references missing paths: " + ", ".join(sorted(set(missing))))
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    if "e6b83d2" not in readme or "1,920" not in readme or "3,840" not in readme:
        raise ValueError("README must identify the legacy commit and exact V9 target counts")
    print(f"Documentation smoke test passed for {len(required_documents)} active documents.")


if __name__ == "__main__":
    main()
