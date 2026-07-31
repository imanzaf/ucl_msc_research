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
from src.prompts.scenario_generation import SCENARIO_GENERATION_TEMPLATE, SCENARIO_REVIEW_TEMPLATE, SCENARIO_REVISION_TEMPLATE
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
    SCENARIO_REVIEW_TEMPLATE,
    SCENARIO_REVISION_TEMPLATE,
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


def test_scoring_templates_render_complete_typed_inputs_as_readable_json() -> None:
    """Keep every condition-blind scoring field explicit and lossless in each user template."""
    scenario = make_accepted_scenario()
    scoring_input = build_condition_blind_inputs(make_transcript(scenario), scenario, 7)[ScoredResponse.INITIAL]
    contracts = [
        (render_content_assessment_prompt, CONTENT_ASSESSMENT_SYSTEM_PROMPT, CONTENT_ASSESSMENT_PROMPT_SHA256),
        (render_presentation_assessment_prompt, PRESENTATION_ASSESSMENT_SYSTEM_PROMPT, PRESENTATION_ASSESSMENT_PROMPT_SHA256),
        (render_accuracy_assessment_prompt, ACCURACY_ASSESSMENT_SYSTEM_PROMPT, ACCURACY_ASSESSMENT_PROMPT_SHA256),
    ]
    for renderer, expected_system, expected_hash in contracts:
        prompt = renderer(scoring_input)
        assert prompt.system == expected_system
        assert prompt.template_sha256 == expected_hash
        assert json.loads(prompt.user) == scoring_input.model_dump(mode="json")
    assert len({contract[2] for contract in contracts}) == 3
