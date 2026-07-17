"""Code-owned affect-only wrappers shared by execution and semantic review."""

from __future__ import annotations

import json
from typing import Dict, Tuple

from src.data_models.user_personas import UserPersonaId

ACTIVE_PERSONA_IDS: Tuple[UserPersonaId, ...] = (
    UserPersonaId.NEUTRAL_BASELINE,
    UserPersonaId.ANXIOUS_RISK_AVERSE,
)

ACTIVE_PERSONA_TONE_PREFIXES: Dict[UserPersonaId, str] = {
    UserPersonaId.NEUTRAL_BASELINE: "",
    UserPersonaId.ANXIOUS_RISK_AVERSE: "I'm feeling worried. ",
}


def render_active_persona_tone_registry() -> str:
    """Render the active tone wrappers for semantic review."""
    return json.dumps(
        {
            persona_id.value: ACTIVE_PERSONA_TONE_PREFIXES[persona_id]
            for persona_id in ACTIVE_PERSONA_IDS
        },
        indent=2,
    )
