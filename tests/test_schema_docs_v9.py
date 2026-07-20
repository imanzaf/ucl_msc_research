"""Exported schema, active documentation, Streamlit import, and R syntax smoke tests."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from scripts import docs_smoke_test
from src.review_app import ReviewPage

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_exported_schemas_are_strict_draft_2020_12_documents() -> None:
    """Validate all tracked schemas and require strict top-level object boundaries."""
    paths = sorted((REPO_ROOT / "schemas/v9").glob("*.schema.json"))
    assert len(paths) >= 20
    for path in paths:
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        assert schema.get("additionalProperties") is False


def test_active_documentation_commands_and_paths_exist() -> None:
    """Keep the README and experiment runbooks executable and navigable."""
    docs_smoke_test.main()


def test_streamlit_app_exposes_exactly_six_review_only_pages() -> None:
    """Keep the app page surface limited to review, repeat, and resolution."""
    assert len(ReviewPage) == 6
    assert all("run" not in page.value.casefold() and "score" not in page.value.casefold() for page in ReviewPage)


def test_r_robustness_script_parses_when_r_is_available() -> None:
    """Catch R syntax regressions without running models or installing packages."""
    if shutil.which("Rscript") is None:
        pytest.skip("Rscript is unavailable")
    completed = subprocess.run(
        ["Rscript", "-e", 'parse(file="analysis/r/run_mixed_models.R")'],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
