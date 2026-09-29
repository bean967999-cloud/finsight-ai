"""Explicit, validated human review input; this is not source verification."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReviewChoice(StrEnum):
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class ReviewDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    choice: ReviewChoice
    note: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def require_rejection_reason(self) -> "ReviewDecision":
        if self.choice == ReviewChoice.REJECTED and not self.note:
            raise ValueError("rejection requires a reason")
        return self
