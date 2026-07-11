"""Filesystem cache helpers for OpenRouter LLM calls."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Optional

from src.data_models.experiments import LLMCallRecord


def stable_json_dumps(payload: Dict[str, Any]) -> str:
    """Serialize a JSON-compatible dictionary deterministically."""
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def build_cache_key(payload: Dict[str, Any]) -> str:
    """Return a SHA-256 hash for a normalized cache payload."""
    return hashlib.sha256(stable_json_dumps(payload).encode("utf-8")).hexdigest()


class LLMCallCache:
    """Store and retrieve OpenRouter call records in an experiment-local cache."""

    def __init__(self, cache_dir: Path, enabled: bool = True, refresh: bool = False) -> None:
        """Create a cache rooted at the provided directory."""
        self.cache_dir = cache_dir
        self.enabled = enabled
        self.refresh = refresh

    def path_for_key(self, cache_key: str) -> Path:
        """Return the cache file path for one cache key."""
        return self.cache_dir / f"{cache_key}.json"

    def get(self, cache_key: str) -> Optional[LLMCallRecord]:
        """Return a cached call record unless caching is disabled or refreshing."""
        if not self.enabled or self.refresh:
            return None
        cache_path = self.path_for_key(cache_key)
        if not cache_path.exists():
            return None
        return LLMCallRecord.model_validate_json(cache_path.read_text(encoding="utf-8"))

    def set(self, record: LLMCallRecord) -> None:
        """Persist one call record when caching is enabled."""
        if not self.enabled:
            return
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = self.path_for_key(record.cache_key)
        cache_path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
