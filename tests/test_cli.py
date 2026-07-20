"""Smoke tests for the unified project command-line interface."""

from __future__ import annotations

import importlib

import pytest
from pytest import CaptureFixture

from src.cli.main import main
from src.cli.registry import COMMAND_GROUPS


def test_top_level_help_lists_workflow_groups(capsys: CaptureFixture[str]) -> None:
    """Expose every workflow group from the top-level help command."""
    main(["--help"])
    output = capsys.readouterr().out
    assert all(group in output for group in COMMAND_GROUPS)


def test_registered_commands_resolve_to_main_functions() -> None:
    """Require every public command to reference an importable main function."""
    for commands in COMMAND_GROUPS.values():
        for command in commands.values():
            module = importlib.import_module(command.module)
            assert callable(getattr(module, "main", None))


def test_registered_commands_expose_argument_help() -> None:
    """Require every delegated argument parser to render help without executing work."""
    for group, commands in COMMAND_GROUPS.items():
        for command_name in commands:
            with pytest.raises(SystemExit) as exit_info:
                main([group, command_name, "--help"])
            assert exit_info.value.code == 0
