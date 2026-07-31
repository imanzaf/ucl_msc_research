"""Provide shared loading, validation, rendering, and hashing for prompt templates."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from types import MappingProxyType
from typing import Any, Dict, Mapping

from jinja2 import Environment, PackageLoader, StrictUndefined

from src.data_models.common import sha256_bytes

SYSTEM_SECTION = "system"
USER_SECTION = "user"
SECTION_HEADER_PATTERN = re.compile(r"(?m)^---(?P<name>[a-z][a-z0-9-]*)---\r?$")


def _json_value(value: Any) -> str:
    """Render one JSON value without escaping readable Unicode text."""
    return json.dumps(value, ensure_ascii=False)


_ENVIRONMENT = Environment(
    loader=PackageLoader("src.prompts", "templates"),
    undefined=StrictUndefined,
    autoescape=False,
    keep_trailing_newline=True,
    trim_blocks=True,
    lstrip_blocks=True,
)
_ENVIRONMENT.filters["json_value"] = _json_value


@dataclass(frozen=True)
class RenderedPrompt:
    """Hold all rendered message sections and the source-template digest."""

    sections: Mapping[str, str]
    template_sha256: str

    @property
    def system(self) -> str:
        """Return the rendered system-message section."""
        return self.section(SYSTEM_SECTION)

    @property
    def user(self) -> str:
        """Return the rendered initial user-message section."""
        return self.section(USER_SECTION)

    def section(self, name: str) -> str:
        """Return one required rendered section by name."""
        try:
            return self.sections[name]
        except KeyError as error:
            raise ValueError(f"rendered prompt does not contain a {name!r} section") from error


@dataclass(frozen=True)
class PromptTemplate:
    """Hold parsed Jinja source sections from one prompt template file."""

    sections: Mapping[str, str]
    template_sha256: str

    @property
    def system(self) -> str:
        """Return the unrendered system-message section."""
        return self.section(SYSTEM_SECTION)

    @property
    def user(self) -> str:
        """Return the unrendered initial user-message section."""
        return self.section(USER_SECTION)

    def section(self, name: str) -> str:
        """Return one required source section by name."""
        try:
            return self.sections[name]
        except KeyError as error:
            raise ValueError(f"prompt template does not contain a {name!r} section") from error

    def render(self, context: Dict[str, Any]) -> RenderedPrompt:
        """Render every section using one strict Jinja context."""
        rendered = {name: _ENVIRONMENT.from_string(source).render(**context).strip() for name, source in self.sections.items()}
        blank_sections = [name for name, value in rendered.items() if not value]
        if blank_sections:
            raise ValueError(f"rendered prompt sections must be nonblank: {', '.join(blank_sections)}")
        return RenderedPrompt(
            sections=MappingProxyType(rendered),
            template_sha256=self.template_sha256,
        )


def _parse_template_sections(source: str, template_name: str) -> Mapping[str, str]:
    """Parse unique named sections while requiring system then user first."""
    matches = list(SECTION_HEADER_PATTERN.finditer(source))
    if not matches or matches[0].start() != 0:
        raise ValueError(f"prompt template {template_name!r} must start with ---system---")
    names = [match.group("name") for match in matches]
    if names[:2] != [SYSTEM_SECTION, USER_SECTION]:
        raise ValueError(f"prompt template {template_name!r} must place ---user--- immediately after ---system---")
    if len(names) != len(set(names)):
        raise ValueError(f"prompt template {template_name!r} contains duplicate section names")
    sections: Dict[str, str] = {}
    for index, match in enumerate(matches):
        content_start = match.end()
        if source[content_start : content_start + 1] == "\n":
            content_start += 1
        content_end = matches[index + 1].start() if index + 1 < len(matches) else len(source)
        content = source[content_start:content_end].strip()
        if not content:
            raise ValueError(f"prompt template {template_name!r} contains a blank {names[index]!r} section")
        sections[names[index]] = content
    return MappingProxyType(sections)


@lru_cache(maxsize=None)
def load_prompt_template(template_name: str) -> PromptTemplate:
    """Load one packaged prompt template and cache its parsed exact source."""
    loader = _ENVIRONMENT.loader
    if loader is None:
        raise RuntimeError("prompt template environment requires a package loader")
    source, _, _ = loader.get_source(_ENVIRONMENT, template_name)
    return PromptTemplate(
        sections=_parse_template_sections(source, template_name),
        template_sha256=sha256_bytes(source.encode("utf-8")),
    )


def render_prompt_template(template_name: str, context: Dict[str, Any]) -> RenderedPrompt:
    """Load and render one packaged prompt template."""
    return load_prompt_template(template_name).render(context)


def prompt_template_sha256(template_name: str) -> str:
    """Return the digest of one complete unrendered prompt template."""
    return load_prompt_template(template_name).template_sha256
