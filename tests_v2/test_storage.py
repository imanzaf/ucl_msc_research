"""Structured storage serialization tests."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from srcv2.storage import read_json, write_json


def test_write_json_serializes_nested_decimal(tmp_path: Path) -> None:
    """Preserve exact decimal values in plain summary dictionaries."""
    path = tmp_path / "summary.json"
    write_json(path, {"billed_cost": Decimal("0.123400")})
    assert read_json(path) == {"billed_cost": "0.123400"}
