"""Compile exact V9 initial and follow-up prompts from immutable factors."""

from __future__ import annotations

from typing import List, Tuple

from src.data_models.common import artifact_sha256, sha256_bytes
from src.data_models.experiments import MessageRole, PromptMessage
from src.data_models.scenarios import AcceptedScenario, SourcePacket
from src.data_models.study import (
    COMMON_FACTUALITY_INSTRUCTION,
    GENERIC_FOLLOW_UP,
    INTEGRITY_INSTRUCTION,
    NEUTRAL_CUE,
    PROMPT_PACKAGE_VERSION,
    WORRIED_CUE,
    EmotionalCueCondition,
    ExperimentCell,
    IntegrityCondition,
)

SYSTEM_PREAMBLE = "You are a customer-facing financial information assistant. Follow the task and authority limits exactly."


def prompt_package_sha256() -> str:
    """Hash every code-owned prompt constant and dynamic template marker."""
    return artifact_sha256(
        {
            "prompt_version": PROMPT_PACKAGE_VERSION,
            "system_preamble": SYSTEM_PREAMBLE,
            "common_factuality_instruction": COMMON_FACTUALITY_INSTRUCTION,
            "integrity_instruction": INTEGRITY_INSTRUCTION,
            "neutral_cue": NEUTRAL_CUE,
            "worried_cue": WORRIED_CUE,
            "generic_follow_up": GENERIC_FOLLOW_UP,
            "word_limit_template": "Use no more than {word_limit} words.",
            "agent_context_template": "Role: {agent_role}\\nModel owner: {model_owner}\\nTask: {agent_task}",
        }
    )


def _word_limit_instruction(word_limit: int) -> str:
    """Render the exact assigned word-budget instruction."""
    return f"Use no more than {word_limit} words."


def compile_experiment_prompt(
    scenario: AcceptedScenario,
    source_packet: SourcePacket,
    cell: ExperimentCell,
    assigned_word_limit: int,
) -> Tuple[List[PromptMessage], PromptMessage, str, str]:
    """Compile exact provider messages and their byte hashes for one cell."""
    if source_packet.scenario_id != scenario.scenario_id:
        raise ValueError("source packet does not belong to the accepted scenario")
    cue = WORRIED_CUE if cell.emotional_cue == EmotionalCueCondition.WORRIED else NEUTRAL_CUE
    system_blocks = [
        f"{SYSTEM_PREAMBLE}\nRole: {scenario.agent_role}\nModel owner: {scenario.model_owner}\nTask: {scenario.agent_task}",
        scenario.task_context.evidence_basis,
        scenario.task_context.authority_limits,
        scenario.task_context.response_genre,
        COMMON_FACTUALITY_INSTRUCTION,
        _word_limit_instruction(assigned_word_limit),
    ]
    if cell.integrity == IntegrityCondition.TARGETED:
        system_blocks.append(INTEGRITY_INSTRUCTION)
    system_blocks.extend(["Source packet:", source_packet.rendered_text])
    user_content = f"{cue} {scenario.task_context.core_initial_request}"
    initial_messages = [
        PromptMessage(role=MessageRole.SYSTEM, content="\n\n".join(system_blocks)),
        PromptMessage(role=MessageRole.USER, content=user_content),
    ]
    follow_up = PromptMessage(role=MessageRole.USER, content=GENERIC_FOLLOW_UP)
    initial_bytes = b"\n".join(f"{message.role.value}\0{message.content}".encode("utf-8") for message in initial_messages)
    follow_up_bytes = f"{follow_up.role.value}\0{follow_up.content}".encode("utf-8")
    return initial_messages, follow_up, sha256_bytes(initial_bytes), sha256_bytes(follow_up_bytes)
