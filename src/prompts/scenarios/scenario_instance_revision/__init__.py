"""Expose the V6 scenario-instance revision prompt."""

from src.prompts.scenarios.scenario_instance_revision.template import (
    SCENARIO_REVISION_INSTRUCTIONS,
    render_scenario_revision_prompt,
)

__all__ = ["SCENARIO_REVISION_INSTRUCTIONS", "render_scenario_revision_prompt"]
