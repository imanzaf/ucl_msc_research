"""Frozen Unicode-aware word counting for all protocol paths."""

from __future__ import annotations

import re
from typing import List

WORD_COUNTER_VERSION = "unicode_finance_v1"

_ALPHANUMERIC = r"[^\W_]"
_NUMBER = r"\d+(?:[,.]\d+)*(?:%|[^\W\d_]{3})?"
_SEGMENT = rf"(?:{_NUMBER}|{_ALPHANUMERIC}+)"
WORD_PATTERN = re.compile(rf"(?:[£$€¥]\s*)?{_SEGMENT}(?:[’'/-]{_SEGMENT})*", flags=re.UNICODE)


def tokenize_words(text: str) -> List[str]:
    """Return frozen Unicode-aware finance tokens from plain or Markdown text."""
    return [match.group(0) for match in WORD_PATTERN.finditer(text)]


def count_words(text: str) -> int:
    """Count words with internal apostrophes, hyphens, and slashes kept together."""
    return len(tokenize_words(text))
