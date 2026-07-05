"""Pydantic models and prompt rendering for V4 user-simulator interactions."""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.data_models.scenarios import UserAction, UserBelief
from src.data_models.user_personas import UserPersona
from src.prompts.user_simulator.next_turn import NEXT_TURN_TEMPLATE
from src.prompts.user_simulator.outcome import OUTCOME_TEMPLATE

MAX_USER_SIMULATOR_FOLLOWUP_TURNS = 3


class ConversationSpeaker(str, Enum):
    """Classify the speaker for a typed conversation transcript turn."""

    USER = "user"
    AGENT = "agent"


class ConversationTurn(BaseModel):
    """Represent one user or agent utterance in a transcript."""

    model_config = ConfigDict(extra="forbid")

    speaker: ConversationSpeaker = Field(
        description="Speaker that produced this transcript turn.",
    )
    turn_index: int = Field(
        ge=1,
        description="One-based turn index within the conversation transcript.",
    )
    content: str = Field(
        min_length=1,
        description="Natural-language content of the transcript turn.",
    )


def validate_conversation_turns(turns: List[ConversationTurn]) -> None:
    """Ensure transcript turns are sequential and alternate between user and agent."""
    turn_indexes = [turn.turn_index for turn in turns]
    expected_indexes = list(range(1, len(turns) + 1))
    if turn_indexes != expected_indexes:
        raise ValueError("conversation turn_index values must be sequential from 1")

    if turns and turns[0].speaker != ConversationSpeaker.USER:
        raise ValueError("conversation must start with a user turn")

    for previous_turn, current_turn in zip(turns, turns[1:]):
        if previous_turn.speaker == current_turn.speaker:
            raise ValueError("conversation speakers must alternate between user and agent")


class VisibleUserAction(BaseModel):
    """Expose a user action option without hidden harmfulness labels."""

    model_config = ConfigDict(extra="forbid")

    action_id: str = Field(
        min_length=1,
        description="Stable identifier for this possible user action.",
    )
    label: str = Field(
        min_length=1,
        description="Short action label visible to the user simulator.",
    )
    description: str = Field(
        min_length=1,
        description="Plain-language action description visible to the user simulator.",
    )

    @classmethod
    def from_user_action(cls, action: UserAction) -> "VisibleUserAction":
        """Create a simulator-visible action option from a labelled scenario action."""
        return cls(
            action_id=action.action_id,
            label=action.label,
            description=action.description,
        )


class VisibleUserBelief(BaseModel):
    """Expose a user belief option without hidden fact-pool support labels."""

    model_config = ConfigDict(extra="forbid")

    belief_id: str = Field(
        min_length=1,
        description="Stable identifier for this possible user belief.",
    )
    belief: str = Field(
        min_length=1,
        description="Belief text visible to the user simulator.",
    )

    @classmethod
    def from_user_belief(cls, belief: UserBelief) -> "VisibleUserBelief":
        """Create a simulator-visible belief option from a labelled scenario belief."""
        return cls(
            belief_id=belief.belief_id,
            belief=belief.belief,
        )


def visible_actions_from_user_actions(actions: List[UserAction]) -> List[VisibleUserAction]:
    """Create simulator-visible action options from labelled scenario actions."""
    return [VisibleUserAction.from_user_action(action) for action in actions]


def visible_beliefs_from_user_beliefs(beliefs: List[UserBelief]) -> List[VisibleUserBelief]:
    """Create simulator-visible belief options from labelled scenario beliefs."""
    return [VisibleUserBelief.from_user_belief(belief) for belief in beliefs]


class UserSimulatorTurnInput(BaseModel):
    """Describe one request for the user simulator to produce a follow-up user turn."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default="user_simulator_turn_input.v1",
        description="Schema version for user-simulator turn inputs.",
    )
    user_role: str = Field(
        min_length=1,
        description="Role assigned to the user-side simulator.",
    )
    user_goal: str = Field(
        min_length=1,
        description="Scenario-specific goal pursued by the simulated user.",
    )
    agent_role: str = Field(
        min_length=1,
        description="Role assigned to the agent model.",
    )
    persona: UserPersona = Field(
        description="Reusable persona condition for the simulated user.",
    )
    user_facing_context: List[str] = Field(
        min_length=1,
        description="Context visible to the user simulator but not directly to the agent.",
    )
    conversation_so_far: List[ConversationTurn] = Field(
        min_length=2,
        description="Transcript ending with the latest agent response.",
    )
    followup_turn_index: int = Field(
        ge=1,
        le=MAX_USER_SIMULATOR_FOLLOWUP_TURNS,
        description="One-based generated user follow-up index for this simulator call.",
    )
    max_followup_turns: int = Field(
        default=MAX_USER_SIMULATOR_FOLLOWUP_TURNS,
        ge=1,
        le=MAX_USER_SIMULATOR_FOLLOWUP_TURNS,
        description="Hard cap on generated user follow-up turns for this conversation.",
    )

    @model_validator(mode="after")
    def validate_turn_input(self) -> "UserSimulatorTurnInput":
        """Ensure the simulator turn request follows the V4 multi-turn protocol."""
        validate_conversation_turns(self.conversation_so_far)
        if self.conversation_so_far[-1].speaker != ConversationSpeaker.AGENT:
            raise ValueError("user-simulator turn input must follow an agent response")
        if self.followup_turn_index > self.max_followup_turns:
            raise ValueError("followup_turn_index cannot exceed max_followup_turns")
        return self


class UserSimulatorTurnOutput(BaseModel):
    """Describe the structured output for one generated follow-up user turn."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default="user_simulator_turn_output.v1",
        description="Schema version for user-simulator turn outputs.",
    )
    should_continue: bool = Field(
        description="Whether the simulated user would reasonably ask another follow-up.",
    )
    utterance: Optional[str] = Field(
        default=None,
        description="Next user utterance when should_continue is true; omitted when false.",
    )
    rationale: str = Field(
        min_length=1,
        description="Brief rationale for the continue/stop decision.",
    )

    @model_validator(mode="after")
    def validate_turn_output(self) -> "UserSimulatorTurnOutput":
        """Ensure continuation decisions and utterance content are internally consistent."""
        if self.should_continue and not (self.utterance and self.utterance.strip()):
            raise ValueError("utterance is required when should_continue is true")
        if not self.should_continue and self.utterance is not None:
            raise ValueError("utterance must be omitted when should_continue is false")
        return self


class UserSimulatorOutcomeInput(BaseModel):
    """Describe the post-conversation action and belief selection request."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default="user_simulator_outcome_input.v1",
        description="Schema version for user-simulator outcome inputs.",
    )
    user_role: str = Field(
        min_length=1,
        description="Role assigned to the user-side simulator.",
    )
    user_goal: str = Field(
        min_length=1,
        description="Scenario-specific goal pursued by the simulated user.",
    )
    agent_role: str = Field(
        min_length=1,
        description="Role assigned to the agent model.",
    )
    persona: UserPersona = Field(
        description="Reusable persona condition for the simulated user.",
    )
    user_facing_context: List[str] = Field(
        min_length=1,
        description="Context visible to the user simulator but not directly to the agent.",
    )
    conversation: List[ConversationTurn] = Field(
        min_length=2,
        description="Completed conversation transcript used to estimate user action and beliefs.",
    )
    available_actions: List[VisibleUserAction] = Field(
        min_length=1,
        description="Simulator-visible user action options without hidden harmfulness labels.",
    )
    available_beliefs: List[VisibleUserBelief] = Field(
        min_length=1,
        description="Simulator-visible belief options without hidden fact-pool support labels.",
    )

    @model_validator(mode="after")
    def validate_outcome_input(self) -> "UserSimulatorOutcomeInput":
        """Ensure the completed transcript and visible option spaces are valid."""
        validate_conversation_turns(self.conversation)
        if self.conversation[-1].speaker != ConversationSpeaker.AGENT:
            raise ValueError("user-simulator outcome input must end with an agent response")

        action_ids = [action.action_id for action in self.available_actions]
        if len(set(action_ids)) != len(action_ids):
            raise ValueError("available action_id values must be unique")

        belief_ids = [belief.belief_id for belief in self.available_beliefs]
        if len(set(belief_ids)) != len(belief_ids):
            raise ValueError("available belief_id values must be unique")
        return self


class UserSimulatorOutcome(BaseModel):
    """Describe the simulated user's post-conversation action and beliefs."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default="user_simulator_outcome.v1",
        description="Schema version for user-simulator outcomes.",
    )
    selected_action_id: str = Field(
        min_length=1,
        description="Exactly one selected user action identifier.",
    )
    selected_belief_ids: List[str] = Field(
        default_factory=list,
        description="Belief identifiers the simulated user would reasonably hold after the conversation.",
    )
    rationale: str = Field(
        min_length=1,
        description="Brief rationale for the selected action and beliefs.",
    )

    @model_validator(mode="after")
    def validate_unique_belief_ids(self) -> "UserSimulatorOutcome":
        """Ensure selected belief identifiers are unique."""
        if len(set(self.selected_belief_ids)) != len(self.selected_belief_ids):
            raise ValueError("selected_belief_ids must be unique")
        return self

    def validate_against_options(self, outcome_input: UserSimulatorOutcomeInput) -> None:
        """Reject selected action or belief ids that are absent from the visible option spaces."""
        action_ids = {action.action_id for action in outcome_input.available_actions}
        if self.selected_action_id not in action_ids:
            raise ValueError(f"unknown selected_action_id: {self.selected_action_id}")

        belief_ids = {belief.belief_id for belief in outcome_input.available_beliefs}
        unknown_belief_ids = [
            belief_id for belief_id in self.selected_belief_ids if belief_id not in belief_ids
        ]
        if unknown_belief_ids:
            raise ValueError("unknown selected_belief_ids: " + ", ".join(unknown_belief_ids))


class UserSimulatorPromptTemplate(BaseModel):
    """Render code-owned prompts for user-simulator turn and outcome calls."""

    model_config = ConfigDict(extra="forbid")

    template_id: str = Field(
        default="user_simulator_prompt_v1",
        description="Stable identifier for the user-simulator prompt rendering template.",
    )
    next_turn_template: str = Field(
        default=NEXT_TURN_TEMPLATE,
        description="Template for next-user-turn simulator calls.",
    )
    outcome_template: str = Field(
        default=OUTCOME_TEMPLATE,
        description="Template for post-conversation action and belief selection calls.",
    )
    conversation_turn_template: str = Field(
        default="Turn {turn_index} - {speaker}: {content}",
        description="Template used to render one typed conversation turn.",
    )
    action_option_template: str = Field(
        default="- {action_id}: {label} - {description}",
        description="Template used to render one visible action option.",
    )
    belief_option_template: str = Field(
        default="- {belief_id}: {belief}",
        description="Template used to render one visible belief option.",
    )

    @model_validator(mode="after")
    def validate_template_placeholders(self) -> "UserSimulatorPromptTemplate":
        """Ensure simulator prompt templates contain all required placeholders."""
        shared_placeholders = [
            "{user_role}",
            "{user_goal}",
            "{agent_role}",
            "{persona}",
            "{user_facing_context}",
            "{conversation}",
        ]
        for placeholder in shared_placeholders:
            if placeholder not in self.next_turn_template:
                raise ValueError(f"next_turn_template must contain {placeholder}")
        for placeholder in shared_placeholders + ["{available_actions}", "{available_beliefs}"]:
            if placeholder not in self.outcome_template:
                raise ValueError(f"outcome_template must contain {placeholder}")
        for placeholder in ["{turn_index}", "{speaker}", "{content}"]:
            if placeholder not in self.conversation_turn_template:
                raise ValueError(f"conversation_turn_template must contain {placeholder}")
        for placeholder in ["{action_id}", "{label}", "{description}"]:
            if placeholder not in self.action_option_template:
                raise ValueError(f"action_option_template must contain {placeholder}")
        for placeholder in ["{belief_id}", "{belief}"]:
            if placeholder not in self.belief_option_template:
                raise ValueError(f"belief_option_template must contain {placeholder}")
        return self

    def render_persona(self, persona: UserPersona) -> str:
        """Render the reusable persona traits for the simulator prompt."""
        return "\n".join(
            [
                f"- persona_id: {persona.persona_id.value}",
                f"- emotion: {persona.emotion.value}",
                f"- emotion_intensity: {persona.emotion_intensity.value}",
                f"- risk_appetite: {persona.risk_appetite.value}",
                f"- communication_style: {persona.communication_style.value}",
            ]
        )

    def render_user_facing_context(self, user_facing_context: List[str]) -> str:
        """Render user-visible context as a compact bulleted list."""
        return "\n".join(f"- {context}" for context in user_facing_context)

    def render_conversation(self, conversation: List[ConversationTurn]) -> str:
        """Render typed conversation turns for simulator prompts."""
        return "\n".join(
            self.conversation_turn_template.format(
                turn_index=turn.turn_index,
                speaker=turn.speaker.value,
                content=turn.content,
            )
            for turn in conversation
        )

    def render_actions(self, actions: List[VisibleUserAction]) -> str:
        """Render simulator-visible action options without hidden labels."""
        return "\n".join(
            self.action_option_template.format(
                action_id=action.action_id,
                label=action.label,
                description=action.description,
            )
            for action in actions
        )

    def render_beliefs(self, beliefs: List[VisibleUserBelief]) -> str:
        """Render simulator-visible belief options without hidden labels."""
        return "\n".join(
            self.belief_option_template.format(
                belief_id=belief.belief_id,
                belief=belief.belief,
            )
            for belief in beliefs
        )

    def render_next_turn_prompt(self, turn_input: UserSimulatorTurnInput) -> str:
        """Render the prompt for a user-simulator follow-up turn call."""
        return self.next_turn_template.format(
            user_role=turn_input.user_role,
            user_goal=turn_input.user_goal,
            agent_role=turn_input.agent_role,
            persona=self.render_persona(turn_input.persona),
            user_facing_context=self.render_user_facing_context(turn_input.user_facing_context),
            conversation=self.render_conversation(turn_input.conversation_so_far),
        )

    def render_outcome_prompt(self, outcome_input: UserSimulatorOutcomeInput) -> str:
        """Render the prompt for post-conversation action and belief selection."""
        return self.outcome_template.format(
            user_role=outcome_input.user_role,
            user_goal=outcome_input.user_goal,
            agent_role=outcome_input.agent_role,
            persona=self.render_persona(outcome_input.persona),
            user_facing_context=self.render_user_facing_context(outcome_input.user_facing_context),
            conversation=self.render_conversation(outcome_input.conversation),
            available_actions=self.render_actions(outcome_input.available_actions),
            available_beliefs=self.render_beliefs(outcome_input.available_beliefs),
        )
