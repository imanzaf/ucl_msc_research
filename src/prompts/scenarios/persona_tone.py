"""Code-owned affect-only wrappers shared by V6 execution and semantic review."""

from __future__ import annotations

import json
from typing import Dict, Tuple

from src.data_models.user_personas import UserPersonaId

V6_PERSONA_IDS: Tuple[UserPersonaId, ...] = (
    UserPersonaId.NEUTRAL_BASELINE,
    UserPersonaId.ANXIOUS_RISK_AVERSE,
)

V6_PERSONA_TONE_PREFIXES: Dict[UserPersonaId, str] = {
    UserPersonaId.NEUTRAL_BASELINE: "",
    UserPersonaId.ANXIOUS_RISK_AVERSE: "I'm feeling worried. ",
}


def render_v6_persona_tone_registry() -> str:
    """Render the two active V6 tone wrappers for semantic review."""
    return json.dumps(
        {persona_id.value: V6_PERSONA_TONE_PREFIXES[persona_id] for persona_id in V6_PERSONA_IDS},
        indent=2,
    )
