"""Render condition-blind paired templates for three scoring contracts."""

from src.data_models.common import artifact_sha256
from src.data_models.scoring import BlindFactReference, ConditionBlindScoringInput
from src.prompts.template_utils import RenderedPrompt, load_prompt_template, render_prompt_template

CONTENT_ASSESSMENT_TEMPLATE = "scoring_content.jinja2"
PRESENTATION_ASSESSMENT_TEMPLATE = "scoring_presentation.jinja2"
ACCURACY_ASSESSMENT_TEMPLATE = "scoring_accuracy.jinja2"

OUTPUT_NORMALISATION_POLICY = (
    "Derive content-evidence offsets from exact isolated-response sentences; require presentation and accuracy evidence to be exact response "
    "substrings; attach the requested fact ID to presentation shifts; and run presentation scoring only for facts the independent content call marks "
    "present."
)

_CONTENT_TEMPLATE = load_prompt_template(CONTENT_ASSESSMENT_TEMPLATE)
_PRESENTATION_TEMPLATE = load_prompt_template(PRESENTATION_ASSESSMENT_TEMPLATE)
_ACCURACY_TEMPLATE = load_prompt_template(ACCURACY_ASSESSMENT_TEMPLATE)

CONTENT_ASSESSMENT_SYSTEM_PROMPT = _CONTENT_TEMPLATE.system
PRESENTATION_ASSESSMENT_SYSTEM_PROMPT = _PRESENTATION_TEMPLATE.system
ACCURACY_ASSESSMENT_SYSTEM_PROMPT = _ACCURACY_TEMPLATE.system
CONTENT_ASSESSMENT_PROMPT_SHA256 = _CONTENT_TEMPLATE.template_sha256
PRESENTATION_ASSESSMENT_PROMPT_SHA256 = _PRESENTATION_TEMPLATE.template_sha256
ACCURACY_ASSESSMENT_PROMPT_SHA256 = _ACCURACY_TEMPLATE.template_sha256


def _render_scoring_prompt(
    template_name: str,
    scoring_input: ConditionBlindScoringInput,
    fact: BlindFactReference | None = None,
) -> RenderedPrompt:
    """Render one condition-blind scoring prompt from its typed input."""
    context = scoring_input.model_dump(mode="json")
    if fact is not None:
        context["fact"] = fact.model_dump(mode="json")
    return render_prompt_template(template_name, context)


def render_content_assessment_prompt(scoring_input: ConditionBlindScoringInput, fact: BlindFactReference) -> RenderedPrompt:
    """Render one fact-level material-content scoring prompt."""
    return _render_scoring_prompt(CONTENT_ASSESSMENT_TEMPLATE, scoring_input, fact)


def render_presentation_assessment_prompt(scoring_input: ConditionBlindScoringInput, fact: BlindFactReference) -> RenderedPrompt:
    """Render one fact-level presentation-shift scoring prompt."""
    return _render_scoring_prompt(PRESENTATION_ASSESSMENT_TEMPLATE, scoring_input, fact)


def render_accuracy_assessment_prompt(scoring_input: ConditionBlindScoringInput) -> RenderedPrompt:
    """Render the factual-accuracy scoring prompt."""
    return _render_scoring_prompt(ACCURACY_ASSESSMENT_TEMPLATE, scoring_input)


def scoring_contract_sha256() -> str:
    """Hash the complete three paired scoring templates and normalisation policy."""
    return artifact_sha256(
        {
            "content_assessment_template_sha256": CONTENT_ASSESSMENT_PROMPT_SHA256,
            "presentation_assessment_template_sha256": PRESENTATION_ASSESSMENT_PROMPT_SHA256,
            "accuracy_assessment_template_sha256": ACCURACY_ASSESSMENT_PROMPT_SHA256,
            "output_normalisation_policy": OUTPUT_NORMALISATION_POLICY,
        }
    )
