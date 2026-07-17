"""Expose the controlled V6 scenario-instance generation prompt."""

from src.prompts.scenarios.scenario_instance_generation_v6.template import (
    V6_GENERATOR_INSTRUCTIONS,
    render_v6_scenario_generation_prompt,
)

__all__ = ["V6_GENERATOR_INSTRUCTIONS", "render_v6_scenario_generation_prompt"]
