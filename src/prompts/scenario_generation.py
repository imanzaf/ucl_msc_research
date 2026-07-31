"""Load and render paired Jinja2 prompts for scenario generation workflows."""

from __future__ import annotations

from typing import Any, Dict

from src.prompts.template_utils import RenderedPrompt, load_prompt_template, render_prompt_template

SCENARIO_GENERATION_TEMPLATE = "scenario_generation.jinja2"
SCENARIO_REVIEW_TEMPLATE = "scenario_review.jinja2"
SCENARIO_REVISION_TEMPLATE = "scenario_revision.jinja2"


def render_scenario_generation_prompt(payload: Dict[str, Any]) -> RenderedPrompt:
    """Render the initial scenario-generation system and user messages."""
    return render_prompt_template(SCENARIO_GENERATION_TEMPLATE, payload)


def render_scenario_review_prompt(candidate: Dict[str, Any], fixed_c1_anchor: Dict[str, Any] | None) -> RenderedPrompt:
    """Render one single-candidate review with its optional fixed C1 comparison anchor."""
    return render_prompt_template(
        SCENARIO_REVIEW_TEMPLATE,
        {
            "candidate": candidate,
            "fixed_c1_anchor": fixed_c1_anchor,
        },
    )


def render_scenario_revision_prompt(payload: Dict[str, Any]) -> RenderedPrompt:
    """Render one bounded scenario-revision system and user message pair."""
    return render_prompt_template(SCENARIO_REVISION_TEMPLATE, payload)


_GENERATION_PROMPT_TEMPLATE = load_prompt_template(SCENARIO_GENERATION_TEMPLATE)
_REVIEW_PROMPT_TEMPLATE = load_prompt_template(SCENARIO_REVIEW_TEMPLATE)
_REVISION_PROMPT_TEMPLATE = load_prompt_template(SCENARIO_REVISION_TEMPLATE)

SCENARIO_GENERATION_SYSTEM_PROMPT = _GENERATION_PROMPT_TEMPLATE.system
SCENARIO_REVIEW_SYSTEM_PROMPT = _REVIEW_PROMPT_TEMPLATE.system
SCENARIO_REVISION_SYSTEM_PROMPT = _REVISION_PROMPT_TEMPLATE.system
SCENARIO_GENERATION_PROMPT_SHA256 = _GENERATION_PROMPT_TEMPLATE.template_sha256
SCENARIO_REVIEW_PROMPT_SHA256 = _REVIEW_PROMPT_TEMPLATE.template_sha256
SCENARIO_REVISION_PROMPT_SHA256 = _REVISION_PROMPT_TEMPLATE.template_sha256
