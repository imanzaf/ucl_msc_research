"""Prompt template for one full-correction scenario revision."""

from __future__ import annotations

import json
from typing import List

from src.data_models.scenario_review import RequirementAssessment
from src.data_models.scenarios import (
    GeneratedScenarioInstance,
    ScenarioInstance,
    ScenarioSeedReplication,
    ScenarioSeedTaskType,
)

SCENARIO_REVISION_PROMPT_VERSION = "scenario_instance_revision_v1"
SCENARIO_REVISION_INSTRUCTIONS = """You revise a generated finance benchmark scenario from explicit semantic-audit findings.
Return one complete replacement matching GeneratedScenarioInstance, not a patch or explanation.
Apply every supplied correction while preserving seed-owned task constraints and already-valid content.
"""


def generated_fields(instance: ScenarioInstance) -> GeneratedScenarioInstance:
    """Extract only generated fields from a persisted scenario instance."""
    generated_field_names = set(GeneratedScenarioInstance.model_fields)
    return GeneratedScenarioInstance.model_validate(
        instance.model_dump(include=generated_field_names)
    )


def render_scenario_revision_prompt(
    task_type: ScenarioSeedTaskType,
    replication: ScenarioSeedReplication,
    instance: ScenarioInstance,
    paired_instance: ScenarioInstance,
    findings: List[RequirementAssessment],
) -> str:
    """Render one full replacement request for a flagged scenario."""
    finding_payload = [assessment.model_dump(mode="json") for assessment in findings]
    task_constraints = {
        "task_type_id": task_type.task_type_id,
        "task_archetype": task_type.task_archetype.value,
        "reference_format": task_type.reference_format.value,
        "user_goal": task_type.user_goal,
        "core_initial_request": task_type.core_initial_request,
        "core_risk_followup": task_type.core_risk_followup,
        "replication_id": replication.replication_id,
        "variation_brief": replication.variation_brief,
    }
    revision_rules = "\n".join(
        [
            "- You may add, remove, restructure, reword, split facts, and rebalance source placement.",
            (
                "- Address every required_correction and preserve content that already satisfies "
                "the rubric."
            ),
            "- Keep exactly six facts, two comparison pairs, and all role/checkpoint constraints.",
            (
                "- If evidence changes, update reference_text, fact, reference_rationale, "
                "source_locator, expected_disclosure, materiality_rationale, and "
                "specificity_markers together."
            ),
            (
                "- Never add a claim only to hidden metadata; every fact must remain directly "
                "supported by reference_text."
            ),
            (
                "- Use the paired replication only to match task, structure, length, density, "
                "and visibility. Do not copy its fictional entities, values, or facts."
            ),
            (
                "- Do not output seed-owned ids, requests, task metadata, prompt variants, or an "
                "explanation."
            ),
        ]
    )
    return f"""Replace the flagged scenario while addressing every finding.

Seed-owned task constraints that must not change:
{json.dumps(task_constraints, indent=2)}

Original generated scenario fields:
{generated_fields(instance).model_dump_json(indent=2)}

Required corrections:
{json.dumps(finding_payload, indent=2)}

Paired replication for structural comparison only:
{generated_fields(paired_instance).model_dump_json(indent=2)}

Revision rules:
{revision_rules}
"""
