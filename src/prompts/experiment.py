"""Compile exact initial and follow-up prompts from immutable factors."""

from __future__ import annotations

from typing import List, Sequence, Tuple

from src.data_models.common import artifact_sha256, sha256_bytes
from src.data_models.experiments import MessageRole, PromptMessage
from src.data_models.manifests import CompleteRenderedRequestReview
from src.data_models.scenarios import AcceptedScenario, SourcePacket
from src.data_models.study import (
    ALL_CUE_PHRASES,
    BRIEF_REQUEST,
    COMMON_FACTUALITY_INSTRUCTION,
    PROMPT_PACKAGE_VERSION,
    ExperimentCell,
    ExpressedConcernCondition,
    StudyStage,
    WordBudgetCondition,
    assigned_cue,
    natural_follow_up,
)

SYSTEM_PREAMBLE = "You are a customer-facing financial information assistant. Follow the task and authority limits exactly."


def prompt_package_sha256() -> str:
    """Hash every code-owned prompt constant and dynamic template marker."""
    return artifact_sha256(
        {
            "prompt_version": PROMPT_PACKAGE_VERSION,
            "system_preamble": SYSTEM_PREAMBLE,
            "common_factuality_instruction": COMMON_FACTUALITY_INSTRUCTION,
            "cue_phrases": ALL_CUE_PHRASES,
            "natural_follow_ups": [natural_follow_up(f"CF{index:03d}") for index in range(1, 11)],
            "brief_request": BRIEF_REQUEST,
            "word_limit_template": "Use no more than {word_limit} words.",
            "agent_context_template": "Role: {agent_role}\\nModel owner: {model_owner}\\nTask: {agent_task}",
        }
    )


def _word_limit_instruction(word_limit: int | None) -> str | None:
    """Render the exact assigned word-budget instruction."""
    return f"Use no more than {word_limit} words." if word_limit is not None else None


def render_reviewed_user_request(scenario: AcceptedScenario, expressed_concern: ExpressedConcernCondition) -> str:
    """Render the complete primary user request reviewed for one scenario and cue."""
    return " ".join([assigned_cue(scenario.scenario_id, expressed_concern), scenario.task_context.core_initial_request])


def validate_complete_request_reviews(
    reviews: Sequence[CompleteRenderedRequestReview],
    scenarios: Sequence[AcceptedScenario],
) -> None:
    """Require all 80 reviews to match the exact primary user requests compiled from accepted scenarios."""
    scenario_by_id = {scenario.scenario_id: scenario for scenario in scenarios}
    if len(scenario_by_id) != 40:
        raise ValueError("complete-request review validation requires all 40 accepted evaluation scenarios")
    for review in reviews:
        scenario = scenario_by_id.get(review.scenario_id)
        if scenario is None:
            raise ValueError("complete-request review references an unaccepted evaluation scenario")
        expected = render_reviewed_user_request(scenario, review.expressed_concern)
        if review.rendered_request_text != expected:
            raise ValueError("reviewed request bytes differ from the request compiled from the accepted scenario")


def compile_experiment_prompt(
    scenario: AcceptedScenario,
    source_packet: SourcePacket,
    cell: ExperimentCell,
    assigned_word_limit: int | None,
) -> Tuple[List[PromptMessage], PromptMessage, str, str]:
    """Compile exact provider messages and their byte hashes for one cell."""
    if source_packet.scenario_id != scenario.scenario_id:
        raise ValueError("source packet does not belong to the accepted scenario")
    system_blocks = [
        f"{SYSTEM_PREAMBLE}\nRole: {scenario.agent_role}\nModel owner: {scenario.model_owner}\nTask: {scenario.agent_task}",
        scenario.task_context.evidence_basis,
        scenario.task_context.authority_limits,
        scenario.task_context.response_genre,
        COMMON_FACTUALITY_INSTRUCTION,
    ]
    word_limit_instruction = _word_limit_instruction(assigned_word_limit)
    if word_limit_instruction is not None:
        system_blocks.append(word_limit_instruction)
    system_blocks.extend(["Source packet:", source_packet.rendered_text])
    user_content = render_reviewed_user_request(scenario, cell.expressed_concern)
    if cell.stage == StudyStage.BREVITY_LOCUS:
        if cell.word_budget != WordBudgetCondition.NONE or assigned_word_limit is not None:
            raise ValueError("brevity_locus_v1 must have no system word cap")
        user_content = " ".join([user_content, BRIEF_REQUEST])
    initial_messages = [
        PromptMessage(role=MessageRole.SYSTEM, content="\n\n".join(system_blocks)),
        PromptMessage(role=MessageRole.USER, content=user_content),
    ]
    follow_up = PromptMessage(role=MessageRole.USER, content=natural_follow_up(scenario.use_case_id))
    initial_bytes = b"\n".join(f"{message.role.value}\0{message.content}".encode("utf-8") for message in initial_messages)
    follow_up_bytes = f"{follow_up.role.value}\0{follow_up.content}".encode("utf-8")
    return initial_messages, follow_up, sha256_bytes(initial_bytes), sha256_bytes(follow_up_bytes)
