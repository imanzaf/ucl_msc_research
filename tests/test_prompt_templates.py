"""Test shared paired-template infrastructure across every active prompt."""

from __future__ import annotations

import json

import pytest
from jinja2 import UndefinedError

from src.data_models.scoring import ScoredResponse
from src.data_models.study import BRIEF_REQUEST, CONCISION_INSTRUCTION
from src.experiments.scoring_pipeline import build_condition_blind_inputs
from src.paths import REPO_ROOT
from src.prompts.experiment import EXPERIMENT_TEMPLATE
from src.prompts.scenario_generation import SCENARIO_GENERATION_TEMPLATE
from src.prompts.scoring_contracts import (
    ACCURACY_ASSESSMENT_PROMPT_SHA256,
    ACCURACY_ASSESSMENT_SYSTEM_PROMPT,
    ACCURACY_ASSESSMENT_TEMPLATE,
    CONTENT_ASSESSMENT_PROMPT_SHA256,
    CONTENT_ASSESSMENT_SYSTEM_PROMPT,
    CONTENT_ASSESSMENT_TEMPLATE,
    PRESENTATION_ASSESSMENT_PROMPT_SHA256,
    PRESENTATION_ASSESSMENT_SYSTEM_PROMPT,
    PRESENTATION_ASSESSMENT_TEMPLATE,
    render_accuracy_assessment_prompt,
    render_content_assessment_prompt,
    render_presentation_assessment_prompt,
)
from src.prompts.template_utils import load_prompt_template, render_prompt_template
from tests.factories import make_accepted_scenario, make_transcript

ALL_PROMPT_TEMPLATES = [
    SCENARIO_GENERATION_TEMPLATE,
    EXPERIMENT_TEMPLATE,
    CONTENT_ASSESSMENT_TEMPLATE,
    PRESENTATION_ASSESSMENT_TEMPLATE,
    ACCURACY_ASSESSMENT_TEMPLATE,
]


def test_every_active_prompt_is_one_paired_jinja_template() -> None:
    """Require visible system/user sections and Jinja formatting in every prompt file."""
    template_root = REPO_ROOT / "src" / "prompts" / "templates"
    assert sorted(path.name for path in template_root.glob("*.jinja2")) == sorted(ALL_PROMPT_TEMPLATES)
    for template_name in ALL_PROMPT_TEMPLATES:
        source = (template_root / template_name).read_text(encoding="utf-8")
        assert source.startswith("---system---\n")
        assert source.count("---system---") == 1
        assert source.count("---user---") == 1
        assert "{{" in source
        template = load_prompt_template(template_name)
        assert template.system
        assert template.user
    experiment_source = (template_root / EXPERIMENT_TEMPLATE).read_text(encoding="utf-8")
    assert list(load_prompt_template(EXPERIMENT_TEMPLATE).sections) == ["system", "user", "follow-up"]
    assert CONCISION_INSTRUCTION in experiment_source
    assert BRIEF_REQUEST in experiment_source
    assert "{% for option_name, facts in visible_fact_groups %}" in experiment_source
    assert "### {{ option_name }}" in experiment_source


def test_shared_renderer_rejects_missing_template_inputs() -> None:
    """Fail immediately when a caller omits a variable required by any template section."""
    with pytest.raises(UndefinedError):
        render_prompt_template(SCENARIO_GENERATION_TEMPLATE, {})


def test_scoring_templates_render_only_judge_facing_fields_as_readable_json() -> None:
    """Keep pipeline metadata out of the minimal judge-facing payloads."""
    scenario = make_accepted_scenario()
    scoring_input = build_condition_blind_inputs(make_transcript(scenario), scenario, 7)[ScoredResponse.INITIAL]
    fact = scoring_input.facts[0]
    contracts = [
        (render_content_assessment_prompt(scoring_input, fact), CONTENT_ASSESSMENT_SYSTEM_PROMPT, CONTENT_ASSESSMENT_PROMPT_SHA256, True),
        (
            render_presentation_assessment_prompt(scoring_input, fact),
            PRESENTATION_ASSESSMENT_SYSTEM_PROMPT,
            PRESENTATION_ASSESSMENT_PROMPT_SHA256,
            False,
        ),
    ]
    for prompt, expected_system, expected_hash, includes_markers in contracts:
        assert prompt.system == expected_system
        assert prompt.template_sha256 == expected_hash
        payload = json.loads(prompt.user)
        assert set(payload) == {"fact", "response"}
        assert payload["response"] == {
            "turn_index": scoring_input.agent_turn.turn_index,
            "text": scoring_input.agent_turn.content,
        }
        expected_keys = {"fact_id", "fact_text", "specificity_markers"} if includes_markers else {"fact_id", "fact_text"}
        assert set(payload["fact"]) == expected_keys
        if includes_markers:
            assert all(set(marker) == {"element_id", "marker_text"} for marker in payload["fact"]["specificity_markers"])
        assert scoring_input.blind_conversation_id not in prompt.user
        assert scoring_input.visible_facts_sha256 not in prompt.user
        assert "randomised_fact_order_seed" not in prompt.user
    accuracy_prompt = render_accuracy_assessment_prompt(scoring_input)
    accuracy_payload = json.loads(accuracy_prompt.user)
    assert set(accuracy_payload) == {"facts", "response"}
    assert len(accuracy_payload["facts"]) == 4
    assert accuracy_prompt.system == ACCURACY_ASSESSMENT_SYSTEM_PROMPT
    assert accuracy_prompt.template_sha256 == ACCURACY_ASSESSMENT_PROMPT_SHA256
    assert len({CONTENT_ASSESSMENT_PROMPT_SHA256, PRESENTATION_ASSESSMENT_PROMPT_SHA256, ACCURACY_ASSESSMENT_PROMPT_SHA256}) == 3
