"""Schema export and experiment-layout commands."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

from src.maintenance import export_json_schemas, initialize_experiment_layout


def _export_schemas(arguments: List[str]) -> None:
    """Export all public JSON schemas."""
    parser = argparse.ArgumentParser(prog="risk-comm maintenance export-schemas")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(arguments)
    print("\n".join(str(path) for path in export_json_schemas(args.output)))


def _initialize_layout(arguments: List[str]) -> None:
    """Create every required output directory."""
    parser = argparse.ArgumentParser(prog="risk-comm maintenance initialize-layout")
    parser.parse_args(arguments)
    print(f"Initialized {len(initialize_experiment_layout())} experiment directories")


def main(command: str, arguments: List[str]) -> None:
    """Dispatch one maintenance subcommand."""
    handlers = {
        "export-schemas": _export_schemas,
        "initialize-layout": _initialize_layout,
    }
    handlers[command](arguments)
