"""Dispatch project workflows through one discoverable command-line interface."""

from __future__ import annotations

import importlib
import sys
from types import ModuleType
from typing import List, NoReturn, Optional

from src.cli.registry import COMMAND_GROUPS, Command


def _print_top_level_help() -> None:
    """Print the available command groups."""
    print("usage: risk-comm <group> <command> [options]\n")
    print("Project workflows:")
    for group in COMMAND_GROUPS:
        print(f"  {group}")
    print("\nRun 'risk-comm <group> --help' to list a group's commands.")


def _print_group_help(group: str) -> None:
    """Print the commands registered under one group."""
    print(f"usage: risk-comm {group} <command> [options]\n")
    print("Commands:")
    for name, command in COMMAND_GROUPS[group].items():
        print(f"  {name:<24} {command.help}")


def _fail(message: str) -> NoReturn:
    """Print a CLI error and terminate with argparse's conventional status."""
    print(f"risk-comm: error: {message}", file=sys.stderr)
    raise SystemExit(2)


def _load_command(command: Command) -> ModuleType:
    """Import a registered command module only when it is invoked."""
    return importlib.import_module(command.module)


def main(argv: Optional[List[str]] = None) -> None:
    """Resolve a command group and delegate remaining arguments to its parser."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] in {"-h", "--help"}:
        _print_top_level_help()
        return

    group = arguments[0]
    if group not in COMMAND_GROUPS:
        _fail(f"unknown group '{group}'")
    if len(arguments) == 1 or arguments[1] in {"-h", "--help"}:
        _print_group_help(group)
        return

    command_name = arguments[1]
    command = COMMAND_GROUPS[group].get(command_name)
    if command is None:
        _fail(f"unknown command '{group} {command_name}'")

    module = _load_command(command)
    command_main = getattr(module, "main", None)
    if not callable(command_main):
        _fail(f"command module '{command.module}' has no callable main()")

    original_argv = sys.argv
    sys.argv = [f"risk-comm {group} {command_name}", *arguments[2:]]
    try:
        command_main()
    finally:
        sys.argv = original_argv


if __name__ == "__main__":
    main()
