"""Schema, layout, isolation, and manuscript validation commands."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

from srcv2.maintenance import (
    export_json_schemas,
    initialize_experiment_layout,
    validate_launchers,
    validate_manuscript_language,
    validate_source_isolation,
)
from srcv2.paths import MANUSCRIPT_ROOT


def _export_schemas(arguments: List[str]) -> None:
    """Export all public final-protocol JSON schemas."""
    parser = argparse.ArgumentParser(prog="risk-comm-v2 maintenance export-schemas")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(arguments)
    print("\n".join(str(path) for path in export_json_schemas(args.output)))


def _initialize_layout(arguments: List[str]) -> None:
    """Create every required output directory."""
    parser = argparse.ArgumentParser(prog="risk-comm-v2 maintenance initialize-layout")
    parser.parse_args(arguments)
    print(f"Initialized {len(initialize_experiment_layout())} experiment directories")


def _validate_isolation(arguments: List[str]) -> None:
    """Fail when source imports or launcher bindings cross the isolation boundary."""
    parser = argparse.ArgumentParser(prog="risk-comm-v2 maintenance validate-isolation")
    parser.parse_args(arguments)
    violations = validate_source_isolation() + validate_launchers()
    if violations:
        print("\n".join(violations))
        raise SystemExit(1)
    print("srcv2 and CLI launcher isolation passed")


def _validate_manuscript(arguments: List[str]) -> None:
    """Fail when the final manuscript contains explicit historical-method comparisons."""
    parser = argparse.ArgumentParser(prog="risk-comm-v2 maintenance validate-manuscript")
    parser.add_argument("--manuscript", type=Path, default=MANUSCRIPT_ROOT)
    args = parser.parse_args(arguments)
    violations = validate_manuscript_language(args.manuscript)
    if violations:
        print("\n".join(violations))
        raise SystemExit(1)
    print("final-manuscript comparison-language gate passed")


def main(command: str, arguments: List[str]) -> None:
    """Dispatch one maintenance subcommand."""
    handlers = {
        "export-schemas": _export_schemas,
        "initialize-layout": _initialize_layout,
        "validate-isolation": _validate_isolation,
        "validate-manuscript": _validate_manuscript,
    }
    handlers[command](arguments)
