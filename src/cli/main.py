"""Dispatch project workflows through the command registry."""

from __future__ import annotations

import importlib
import sys
from types import ModuleType
from typing import List, NoReturn, Optional

from src.cli.registry import COMMAND_GROUPS, Command


def _print_top_level_help() -> None:
    """Print the available command groups."""
    print("usage: risk-comm <group> <command> [options]\n")
    print("Workflows:")
    for group in COMMAND_GROUPS:
        print(f"  {group}")
    print("\nRun 'risk-comm <group> --help' to list a group's commands.")


def _print_group_help(group: str) -> None:
    """Print the commands registered under one group."""
    print(f"usage: risk-comm {group} <command> [options]\n")
    print("Commands:")
    for name, command in COMMAND_GROUPS[group].items():
        print(f"  {name:<28} {command.help}")


def _fail(message: str) -> NoReturn:
    """Print a CLI error and terminate with argparse's conventional status."""
    print(f"risk-comm: error: {message}", file=sys.stderr)
    raise SystemExit(2)


def _load_command(command: Command) -> ModuleType:
    """Import a command module only when invoked."""
    return importlib.import_module(command.module)


def main(argv: Optional[List[str]] = None) -> None:
    """Resolve a command group and delegate its remaining arguments."""
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
    command_main(command_name, arguments[2:])


if __name__ == "__main__":
    main()
