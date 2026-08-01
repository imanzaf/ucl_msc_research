"""Load and render the sole scenario-generation Jinja2 prompt."""

from __future__ import annotations

from typing import Any, Dict

from src.prompts.template_utils import RenderedPrompt, load_prompt_template, render_prompt_template

SCENARIO_GENERATION_TEMPLATE = "scenario_generation.jinja2"


def render_scenario_generation_prompt(payload: Dict[str, Any]) -> RenderedPrompt:
    """Render the initial scenario-generation system and user messages."""
    return render_prompt_template(SCENARIO_GENERATION_TEMPLATE, payload)


_GENERATION_PROMPT_TEMPLATE = load_prompt_template(SCENARIO_GENERATION_TEMPLATE)

SCENARIO_GENERATION_SYSTEM_PROMPT = _GENERATION_PROMPT_TEMPLATE.system
SCENARIO_GENERATION_PROMPT_SHA256 = _GENERATION_PROMPT_TEMPLATE.template_sha256
