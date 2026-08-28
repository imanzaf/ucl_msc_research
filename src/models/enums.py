"""Closed vocabularies used throughout the final protocol."""

from enum import Enum, IntEnum


class FactDirection(str, Enum):
    """Classify whether a fact supports the owner or is countervailing."""

    OWNER_SUPPORTING = "owner_supporting"
    COUNTERVAILING = "countervailing"


class CustomerValence(str, Enum):
    """Classify whether a fact is favourable or adverse for the customer."""

    FAVOURABLE = "customer_favourable"
    ADVERSE = "customer_adverse"


class OwnershipEligibility(str, Enum):
    """Record whether employer ownership can vary without changing the options."""

    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"


class OwnershipRole(str, Enum):
    """Define the employer's relationship to the fixed option-A coordinate."""

    EMPLOYER_OWNS_A = "employer_owns_option_a"
    EMPLOYER_OWNS_B = "employer_owns_option_b"
    INDEPENDENT = "independent_adviser"


class ModelAccess(str, Enum):
    """Classify model access without treating it as a causal attribute."""

    OPEN_WEIGHT = "open_weight"
    CLOSED = "closed"


class LicenceCategory(str, Enum):
    """Freeze the model-weight licence category reported in metadata."""

    COMMUNITY = "community_licence"
    APACHE_2 = "apache_2_0"
    MIT = "mit"
    PROPRIETARY = "proprietary"


class ExperimentKind(str, Enum):
    """Identify one experiment included in the dissertation."""

    USER_STATE = "user_state_adaptation_v2"
    INFORMATION_BUDGET = "information_budget_v1"
    WORD_BUDGET = "word_budget_external_validity_v1"
    SINGLE_FACT = "single_fact_priority_v1"
    OWNERSHIP = "ownership_role_control_v1"
    OPTION_FIRST = "option_first_v1"
    COMMERCIAL_INTEREST = "commercial_interest_instruction_v1"


class AnalysisInterpretation(str, Enum):
    """Label the inferential status of an analysis output."""

    CONFIRMATORY = "confirmatory"


class MultiplicityFamily(str, Enum):
    """Identify the research-question family used for p-value adjustment."""

    RQ1 = "rq1_institutional_objective"
    RQ2 = "rq2_customer_state"
    RQ3 = "rq3_information_budget"


class ExecutionStatus(str, Enum):
    """Declare that an experiment assignment belongs to the evaluated run."""

    ACTIVE = "active"


class Affect(str, Enum):
    """Represent the allowed customer affect manipulation."""

    NEUTRAL = "neutral"
    ANXIOUS = "anxious"
    FRUSTRATED = "frustrated"


class QueryLength(str, Enum):
    """Represent semantically equivalent short and long query forms."""

    SHORT = "short"
    LONG = "long"


class ExactFactBudget(IntEnum):
    """Represent the exact structured fact-selection budgets."""

    FACTS_2 = 2
    FACTS_4 = 4
    FACTS_6 = 6


class NaturalWordBudget(IntEnum):
    """Represent the natural-language external-validity response caps."""

    WORDS_40 = 40
    WORDS_80 = 80
    WORDS_160 = 160


class CommercialInterestInstruction(str, Enum):
    """Distinguish omission or inclusion of the commercial-interest sentence."""

    CONTROL = "control"
    PROTECT_COMMERCIAL_INTERESTS = "protect_commercial_interests"


class CommercialInterestTask(str, Enum):
    """Identify the task crossed with the commercial-interest instruction."""

    STANDARD = "standard_comparison"
    SINGLE_FACT = "single_most_important_fact"
    EXACT_BUDGET = "exact_fact_budget"
    OWNERSHIP_FLIP = "ownership_flip"


class ReviewState(str, Enum):
    """Track the single researcher accept-or-revise scenario review."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    REVISE = "revise"


class JudgeContract(str, Enum):
    """Identify one of the three independent scoring judgments."""

    CONTENT = "content"
    PRESENTATION = "presentation"
    ACCURACY = "accuracy"


class JudgeStage(str, Enum):
    """Distinguish prompt-development calls from the frozen full run."""

    PILOT = "pilot"
    FULL = "full"


class FramingDirection(str, Enum):
    """Record which visible option is favoured by the response's framing."""

    OPTION_A = "option_a_favouring"
    BALANCED = "balanced"
    OPTION_B = "option_b_favouring"
    NOT_ASSESSABLE = "not_assessable"


class RecommendationDirection(str, Enum):
    """Record the visible option selected or recommended by the response."""

    OPTION_A = "option_a"
    OPTION_B = "option_b"
    BALANCED_OR_NONE = "balanced_or_none"


class OptionPresentationOrder(str, Enum):
    """Record which visible option receives the first substantive presentation."""

    OPTION_A = "option_a"
    OPTION_B = "option_b"
    SIMULTANEOUS_OR_NONE = "simultaneous_or_none"


class AccuracyIssueKind(str, Enum):
    """Distinguish unsupported additions from contradictions of supplied facts."""

    UNSUPPORTED = "unsupported"
    CONTRADICTORY = "contradictory"
