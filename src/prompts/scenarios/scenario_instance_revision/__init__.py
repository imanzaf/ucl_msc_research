"""Expose the scenario-instance revision prompt."""

from src.prompts.scenarios.scenario_instance_revision.template import (
    SCENARIO_REVISION_INSTRUCTIONS,
    SCENARIO_REVISION_PROMPT_VERSION,
    render_scenario_revision_prompt,
)

__all__ = [
    "SCENARIO_REVISION_INSTRUCTIONS",
    "SCENARIO_REVISION_PROMPT_VERSION",
    "render_scenario_revision_prompt",
]
