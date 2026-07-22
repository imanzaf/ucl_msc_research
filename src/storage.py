"""Atomic schema-validated JSON and JSONL persistence helpers."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from fcntl import LOCK_EX, LOCK_UN, flock
from pathlib import Path
from typing import Callable, Generator, Iterable, List, Type, TypeVar

from pydantic import BaseModel

ModelT = TypeVar("ModelT", bound=BaseModel)


@contextmanager
def _exclusive_path_lock(path: Path) -> Generator[None, None, None]:
    """Hold an interprocess sibling-file lock for a complete read/validate/replace transaction."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")
    with lock_path.open("a+b") as lock_handle:
        flock(lock_handle.fileno(), LOCK_EX)
        try:
            yield
        finally:
            flock(lock_handle.fileno(), LOCK_UN)


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    """Replace a file atomically using a temporary sibling and fsync."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def write_model_json_atomic(path: Path, model: BaseModel) -> None:
    """Validate and atomically persist one Pydantic model as formatted JSON."""
    validated = type(model).model_validate(model.model_dump(mode="json", by_alias=True))
    payload = validated.model_dump_json(indent=2, by_alias=True).encode("utf-8") + b"\n"
    atomic_write_bytes(path, payload)


def append_model_jsonl_atomic(path: Path, model: BaseModel) -> None:
    """Validate and atomically append one Pydantic record to JSONL."""
    append_model_jsonl_validated(path, model, lambda _existing, _new: None)


def append_model_jsonl_validated(
    path: Path,
    model: ModelT,
    validate_append: Callable[[List[ModelT], ModelT], None],
) -> None:
    """Lock, validate, and append one record as a single atomic transaction."""
    model_type = type(model)
    validated = model_type.model_validate(model.model_dump(mode="json", by_alias=True))
    with _exclusive_path_lock(path):
        existing = read_model_jsonl(path, model_type)
        validate_append(existing, validated)
        write_models_jsonl_atomic(path, [*existing, validated])


def read_model_json(path: Path, model_type: Type[ModelT]) -> ModelT:
    """Read and schema-validate one JSON artifact."""
    return model_type.model_validate_json(path.read_text(encoding="utf-8"))


def read_model_jsonl(path: Path, model_type: Type[ModelT]) -> List[ModelT]:
    """Read and schema-validate every nonblank JSONL record."""
    if not path.exists():
        return []
    records: List[ModelT] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(model_type.model_validate(json.loads(line)))
        except ValueError as error:
            raise ValueError(f"invalid JSONL record at {path}:{line_number}: {error}") from error
    return records


def write_models_jsonl_atomic(path: Path, models: Iterable[BaseModel]) -> None:
    """Validate and atomically replace a JSONL file with supplied records."""
    lines = []
    for model in models:
        validated = type(model).model_validate(model.model_dump(mode="json", by_alias=True))
        lines.append(validated.model_dump_json(by_alias=True))
    payload = ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
    atomic_write_bytes(path, payload)
