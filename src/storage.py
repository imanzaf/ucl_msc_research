"""Atomic storage helpers for immutable experiment artifacts."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable

from src.common import json_compatible


def atomic_write_bytes(path: Path, content: bytes) -> None:
    """Replace one artifact atomically after writing it in the target directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def write_json(path: Path, value: Any) -> None:
    """Write one structured artifact as stable, indented UTF-8 JSON."""
    content = json.dumps(json_compatible(value), indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8") + b"\n"
    atomic_write_bytes(path, content)


def write_jsonl(path: Path, records: Iterable[Any]) -> None:
    """Write structured records as stable UTF-8 JSON Lines."""
    lines = [json.dumps(json_compatible(record), sort_keys=True, ensure_ascii=False, separators=(",", ":")) for record in records]
    atomic_write_bytes(path, ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8"))


def read_json(path: Path) -> Any:
    """Read one UTF-8 JSON artifact."""
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def read_jsonl(path: Path) -> list[Any]:
    """Read nonblank UTF-8 JSON Lines records."""
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]
