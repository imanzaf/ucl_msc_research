"""Prompt template for independent semantic review of one V6 scenario family."""

from __future__ import annotations

import json

from src.data_models.scenario_review import semantic_requirement_registry_rows
from src.data_models.scenarios_v6 import ScenarioFamilyV6, ScenarioSeedV6
from src.prompts.scenarios.persona_tone import render_v6_persona_tone_registry

SEMANTIC_REVIEWER_INSTRUCTIONS = """You are an independent semantic auditor for a controlled finance risk-disclosure benchmark.
Audit only the supplied seed and family. Do not retrieve outside information and do not rewrite scenarios.
Return the complete structured requirement matrix matching ScenarioSemanticReview.
Fail requirements only for substantive methodological defects, not stylistic preferences.
"""


def render_requirement_registry() -> str:
    """Render the enum-backed semantic requirement registry for the reviewer."""
    return json.dumps(semantic_requirement_registry_rows(), indent=2)


def render_semantic_review_prompt(
    seed: ScenarioSeedV6,
    family: ScenarioFamilyV6,
) -> str:
    """Render one complete family-level semantic audit request."""
    return f"""Audit this complete four-scenario V6 family against every requirement.

Requirement registry:
{render_requirement_registry()}

Code-owned persona tone wrappers:
{render_v6_persona_tone_registry()}

Coverage rules:
- Return one scenario-scope assessment for every scenario and every scenario-scope requirement.
- Return one task_type-scope assessment for each task type and every task_type-scope requirement.
- Return one family-scope assessment for the family requirement.
- subject_id is the scenario_id, task_type_id, or scenario_family_id required by subject_scope.
- For pass: finding_id, problem, and required_correction are empty; finding_type is none; affected lists are empty.
- For a scenario failure: affected_scenario_ids contains only that scenario.
- For a task-type failure: affected_scenario_ids contains both replications of that task type.
- For a family failure: identify every scenario that requires correction.
- Every failure must cite exact evidence or a source locator, name concrete affected field paths, and specify an actionable correction.
- Check hidden fact metadata against reference_text, and compare paired replications directly.
- Do not assume that an automated revision will resolve a finding; this output is an audit and correction request only.

Seed-owned constraints:
{seed.model_dump_json(indent=2)}

Initial family draft:
{family.model_dump_json(indent=2)}
"""
