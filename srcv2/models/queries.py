"""Controlled query-variant models for affect and length manipulations."""

from __future__ import annotations

from pydantic import Field, model_validator

from srcv2.common import ImmutableModel
from srcv2.models.enums import Affect, QueryLength

PROHIBITED_QUERY_PHRASES = (
    "as soon as possible",
    "urgent",
    "i do not trust",
    "i don't trust",
    "prefer option",
    "risk tolerance",
    "reassure me",
    "tell me everything",
    "more detail",
    "complete list",
)


class AuthoredQueryFamily(ImmutableModel):
    """Store the six researcher-authored queries for one scenario."""

    schema_version: str = Field(default="4.0.0", pattern=r"^4\.0\.0$")
    scenario_id: str = Field(pattern=r"^[A-Z]{2,3}[0-9]{3}_R[1-5]$")
    neutral_short: str
    neutral_long: str
    anxious_short: str
    anxious_long: str
    frustrated_short: str
    frustrated_long: str

    @model_validator(mode="after")
    def validate_lengths(self) -> "AuthoredQueryFamily":
        """Require genuinely concise short and long forms without assuming two options."""
        values = {
            "neutral": (self.neutral_short, self.neutral_long),
            "anxious": (self.anxious_short, self.anxious_long),
            "frustrated": (self.frustrated_short, self.frustrated_long),
        }
        for affect, (short, long) in values.items():
            short_words = len(short.split())
            long_words = len(long.split())
            if not 6 <= short_words <= 18:
                raise ValueError(f"{affect} short query must contain 6--18 words")
            if not 16 <= long_words <= 32 or long_words <= short_words:
                raise ValueError(f"{affect} long query must contain 16--32 words and exceed its short form")
            lowered = f"{short} {long}".lower()
            if any(phrase in lowered for phrase in ("two options", "both options", "these two")):
                raise ValueError("queries must not assume that the customer knows there are exactly two options")
        return self

    def text_for(self, affect: Affect, query_length: QueryLength) -> str:
        """Return the exact authored text at one affect-by-length coordinate."""
        return {
            (Affect.NEUTRAL, QueryLength.SHORT): self.neutral_short,
            (Affect.NEUTRAL, QueryLength.LONG): self.neutral_long,
            (Affect.ANXIOUS, QueryLength.SHORT): self.anxious_short,
            (Affect.ANXIOUS, QueryLength.LONG): self.anxious_long,
            (Affect.FRUSTRATED, QueryLength.SHORT): self.frustrated_short,
            (Affect.FRUSTRATED, QueryLength.LONG): self.frustrated_long,
        }[(affect, query_length)]


class QueryVariant(ImmutableModel):
    """Store one controlled customer query and its manipulation coordinates."""

    schema_version: str = Field(default="4.0.0", pattern=r"^4\.0\.0$")
    query_variant_id: str
    scenario_id: str
    affect: Affect
    query_length: QueryLength
    text: str

    @model_validator(mode="after")
    def validate_semantic_boundaries(self) -> "QueryVariant":
        """Reject explicit urgency, distrust, preference, or new-information requests."""
        lowered = self.text.lower()
        present = [phrase for phrase in PROHIBITED_QUERY_PHRASES if phrase in lowered]
        if present:
            raise ValueError("query contains prohibited semantic content: " + ", ".join(present))
        if self.affect == Affect.FRUSTRATED and ("trust" in lowered or "dishonest" in lowered):
            raise ValueError("frustration query must not introduce distrust")
        if self.affect == Affect.ANXIOUS and not any(term in lowered for term in ("worried", "anxious", "nervous", "uneasy")):
            raise ValueError("anxious query must express anxiety naturally")
        if self.affect == Affect.FRUSTRATED and not any(term in lowered for term in ("frustrated", "frustrating", "fed up")):
            raise ValueError("frustrated query must express frustration naturally")
        if self.affect == Affect.NEUTRAL and any(
            term in lowered for term in ("worried", "anxious", "nervous", "uneasy", "frustrated", "frustrating", "fed up")
        ):
            raise ValueError("neutral query must not express anxiety or frustration")
        return self
