"""Canonical serialization, hashing, and immutable model primitives."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Dict

from pydantic import BaseModel, ConfigDict


class ImmutableModel(BaseModel):
    """Provide strict immutable Pydantic models for persisted protocol records."""

    model_config = ConfigDict(extra="forbid", frozen=True)


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(UTC)


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize a value to stable UTF-8 JSON bytes."""
    return json.dumps(json_compatible(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def json_compatible(value: Any) -> Any:
    """Convert nested protocol values into deterministic JSON-compatible values."""
    if isinstance(value, BaseModel):
        return json_compatible(value.model_dump(mode="json"))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key.value if isinstance(key, Enum) else key): json_compatible(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_compatible(item) for item in value]
    return value


def sha256_bytes(value: bytes) -> str:
    """Return the lowercase SHA-256 digest for bytes."""
    return hashlib.sha256(value).hexdigest()


def artifact_sha256(value: Any) -> str:
    """Hash a structured artifact after canonical JSON serialization."""
    return sha256_bytes(canonical_json_bytes(value))


def hash_bound_payload(value: Dict[str, Any], hash_field: str = "artifact_sha256") -> Dict[str, Any]:
    """Return a copy of a mapping with a hash bound to every other field."""
    payload = dict(value)
    payload.pop(hash_field, None)
    payload[hash_field] = artifact_sha256(payload)
    return payload
