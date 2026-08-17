"""Isolation and launcher acceptance gates."""

from __future__ import annotations

import subprocess

from srcv2.maintenance import SCHEMA_MODELS, validate_launchers, validate_source_isolation
from srcv2.paths import PROJECT_ROOT, SCHEMA_ROOT


def test_final_source_has_no_historical_imports() -> None:
    """Reject every final-protocol import of the historical source package."""
    assert validate_source_isolation() == []


def test_launchers_bind_to_separate_packages() -> None:
    """Keep each command bound to only its intended package."""
    assert validate_launchers() == []


def test_protected_historical_paths_have_no_tracked_diff() -> None:
    """Ensure implementation did not change protected historical code or tests."""
    result = subprocess.run(
        ["git", "diff", "--quiet", "--", "src", "tests", "scripts/risk-comm"],
        cwd=PROJECT_ROOT,
        check=False,
    )
    assert result.returncode == 0


def test_public_schema_directory_contains_only_current_models() -> None:
    """Reject orphaned schemas from superseded final-protocol designs."""
    expected = {f"{name}.schema.json" for name in SCHEMA_MODELS}
    actual = {path.name for path in SCHEMA_ROOT.glob("*.schema.json")}
    assert actual == expected
