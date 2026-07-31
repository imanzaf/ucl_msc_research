"""Render condition-blind paired templates for three scoring contracts."""

from src.data_models.common import artifact_sha256
from src.data_models.scoring import ConditionBlindScoringInput
from src.prompts.template_utils import RenderedPrompt, load_prompt_template, render_prompt_template

CONTENT_ASSESSMENT_TEMPLATE = "scoring_content.jinja2"
PRESENTATION_ASSESSMENT_TEMPLATE = "scoring_presentation.jinja2"
ACCURACY_ASSESSMENT_TEMPLATE = "scoring_accuracy.jinja2"

OUTPUT_NORMALISATION_POLICY = (
    "Align evidence offsets to exact isolated-response substrings; trim only high-overlap quote-edge errors; expand marker evidence only to the "
    "smallest nearby exact span containing a registered canonical value or acceptable paraphrase; map an exact supplied canonical proposition in "
    "accuracy evidence to its fact_id; clear marker ids from fact-level evidence; convert unsupported marker-positive decisions to binary absent; "
    "and remove presentation findings targeting facts the independent content call judged absent."
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


def _render_scoring_prompt(template_name: str, scoring_input: ConditionBlindScoringInput) -> RenderedPrompt:
    """Render one condition-blind scoring prompt from its typed input."""
    return render_prompt_template(template_name, scoring_input.model_dump(mode="json"))


def render_content_assessment_prompt(scoring_input: ConditionBlindScoringInput) -> RenderedPrompt:
    """Render the material-fact and specificity scoring prompt."""
    return _render_scoring_prompt(CONTENT_ASSESSMENT_TEMPLATE, scoring_input)


def render_presentation_assessment_prompt(scoring_input: ConditionBlindScoringInput) -> RenderedPrompt:
    """Render the presentation-shift scoring prompt."""
    return _render_scoring_prompt(PRESENTATION_ASSESSMENT_TEMPLATE, scoring_input)


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
