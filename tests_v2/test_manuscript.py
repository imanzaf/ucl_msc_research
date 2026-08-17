"""Surgical manuscript-update acceptance gates."""

from __future__ import annotations

import bisect
import difflib
import json
import re
from typing import Any, Dict, List, Tuple

from srcv2.maintenance import validate_manuscript_language
from srcv2.paths import PROJECT_ROOT

SOURCE_MANUSCRIPT = PROJECT_ROOT / "tex_src" / "v0.1.1" / "main.tex"
FINAL_MANUSCRIPT_ROOT = PROJECT_ROOT / "tex_src" / "v0.2.0"
FINAL_MANUSCRIPT = FINAL_MANUSCRIPT_ROOT / "main.tex"
CHANGE_MAP = PROJECT_ROOT / "docs" / "research-plan" / "MANUSCRIPT_CHANGE_MAP.json"
HEADING_PATTERN = re.compile(r"^\\(?:chapter|section|subsection|subsubsection)\{(.+)\}$")


def _headings(lines: List[str]) -> List[Tuple[int, str]]:
    """Return manuscript line indexes paired with their structural headings."""
    headings: List[Tuple[int, str]] = []
    for index, line in enumerate(lines):
        match = HEADING_PATTERN.match(line)
        if match:
            headings.append((index, match.group(1)))
    return headings


def _changed_hunk_headings(source_lines: List[str], final_lines: List[str]) -> List[str]:
    """Map every changed diff opcode to the nearest preceding final heading."""
    headings = _headings(final_lines)
    indexes = [index for index, _ in headings]
    changed: List[str] = []
    for tag, _, _, final_start, _ in difflib.SequenceMatcher(a=source_lines, b=final_lines).get_opcodes():
        if tag == "equal":
            continue
        heading_position = bisect.bisect_right(indexes, max(final_start - 1, 0)) - 1
        changed.append(headings[heading_position][1] if heading_position >= 0 else "preamble")
    return changed


def test_manuscript_directory_omits_stale_build_artifacts() -> None:
    """Keep only editable manuscript sources in the final-protocol directory."""
    names = {path.name for path in FINAL_MANUSCRIPT_ROOT.iterdir() if path.is_file()}
    assert names == {"main.tex", "selective_communication_references.bib"}


def test_manuscript_uses_only_final_protocol_language() -> None:
    """Reject comparison language, internal versions, and obsolete study concepts."""
    assert validate_manuscript_language(FINAL_MANUSCRIPT_ROOT) == []
    manuscript = FINAL_MANUSCRIPT.read_text(encoding="utf-8").lower()
    obsolete = (
        "selective-communication score",
        "presentation-style score",
        "universal follow-up",
        "concerned condition",
        "18 scenarios",
        "three evaluated models",
    )
    assert not any(term in manuscript for term in obsolete)


def test_manuscript_states_final_protocol_and_placeholders() -> None:
    """Require the core final design and explicit result placeholders."""
    manuscript = FINAL_MANUSCRIPT.read_text(encoding="utf-8")
    required = (
        "30 scenario",
        "six financial-services use cases",
        "3,822",
        "five open-weight and two closed models",
        "stratified sample of 191 responses",
        "GPT-5.4 Mini applies three independent contracts",
        "manual-override ledger",
        "Results are not yet available",
    )
    assert all(term in manuscript for term in required)


def test_every_changed_hunk_maps_to_a_protocol_requirement() -> None:
    """Ensure every surgical manuscript diff hunk belongs to a documented affected section."""
    source_lines = SOURCE_MANUSCRIPT.read_text(encoding="utf-8").splitlines()
    final_lines = FINAL_MANUSCRIPT.read_text(encoding="utf-8").splitlines()
    change_map: Dict[str, Any] = json.loads(CHANGE_MAP.read_text(encoding="utf-8"))
    mapped_sections = set(change_map["sections"])
    changed_sections = _changed_hunk_headings(source_lines, final_lines)
    assert changed_sections
    assert set(changed_sections) <= mapped_sections


def test_every_citation_key_resolves_in_final_bibliography() -> None:
    """Require all final-manuscript citation keys to exist in its copied bibliography."""
    manuscript = FINAL_MANUSCRIPT.read_text(encoding="utf-8")
    bibliography = (FINAL_MANUSCRIPT_ROOT / "selective_communication_references.bib").read_text(encoding="utf-8")
    cited_keys = {key.strip() for group in re.findall(r"\\cite(?:\[[^]]*\])?\{([^}]+)\}", manuscript) for key in group.split(",")}
    bibliography_keys = set(re.findall(r"@[A-Za-z]+\{([^,]+),", bibliography))
    assert cited_keys <= bibliography_keys
