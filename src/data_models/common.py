"""Shared immutable boundary-model primitives for the V9 protocol."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict, Field
from pydantic_core import to_jsonable_python

SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")


class StrictModel(BaseModel):
    """Reject unknown fields on every structured protocol boundary."""

    model_config = ConfigDict(extra="forbid")


class ImmutableModel(StrictModel):
    """Reject unknown fields and prevent mutation after validation."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class VersionedImmutableModel(ImmutableModel):
    """Require a schema version on immutable top-level artifacts."""

    schema_version: str = Field(min_length=1)


def utc_now() -> datetime:
    """Return an aware UTC timestamp for persisted provenance."""
    return datetime.now(timezone.utc)


def _json_compatible(value: Any) -> Any:
    """Recursively convert Pydantic and container values into JSON-compatible data."""
    return to_jsonable_python(value, by_alias=True)


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize a value into stable UTF-8 JSON bytes."""
    return json.dumps(_json_compatible(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    """Return the lowercase SHA-256 digest for bytes."""
    return hashlib.sha256(value).hexdigest()


def artifact_sha256(value: Any) -> str:
    """Hash a structured value using canonical JSON serialization."""
    return sha256_bytes(canonical_json_bytes(value))


def file_sha256(path: Path) -> str:
    """Hash a file without normalising its bytes."""
    return sha256_bytes(path.read_bytes())


def path_bundle_sha256(repository_root: Path, relative_paths: List[str]) -> str:
    """Hash relative filenames and exact bytes for a deterministic file/directory bundle."""
    entries: Dict[str, str] = {}
    for relative_value in relative_paths:
        path = repository_root / relative_value
        candidates = (
            sorted(
                candidate
                for candidate in path.rglob("*")
                if candidate.is_file()
                and "__pycache__" not in candidate.parts
                and "library" not in candidate.relative_to(path).parts
                and candidate.suffix not in {".pyc", ".pyo"}
            )
            if path.is_dir()
            else [path]
        )
        for candidate in candidates:
            if not candidate.exists():
                raise ValueError(f"hash bundle path does not exist: {candidate}")
            relative_name = str(candidate.relative_to(repository_root))
            entries[relative_name] = file_sha256(candidate)
    return artifact_sha256(entries)


def validate_sha256(value: str) -> str:
    """Reject a value that is not a lowercase SHA-256 digest."""
    if SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError("value must be a lowercase SHA-256 digest")
    return value


def validate_model_self_hash(model: BaseModel, hash_field: str) -> None:
    """Recompute and validate a model's canonical digest with its self-hash field excluded."""
    if hash_field not in type(model).model_fields:
        raise ValueError(f"unknown self-hash field: {hash_field}")
    expected = getattr(model, hash_field)
    actual = artifact_sha256(model.model_dump(mode="json", by_alias=True, exclude={hash_field}))
    if actual != expected:
        raise ValueError(f"{hash_field} does not match canonical artifact content")
