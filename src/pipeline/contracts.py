import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EditPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    removable_objects: list[str] = Field(default_factory=list)
    structural_keep: list[str] = Field(min_length=1)
    rationale: str


class EditedImage(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: Path
    sha256: str
    phase_id: int
    attempt: int
    prompt_used: str

    @field_validator("sha256")
    @classmethod
    def _validate_sha256(cls, v: str) -> str:
        if not re.fullmatch(r"[a-f0-9]{64}", v):
            raise ValueError("sha256 must be 64 lowercase hex chars")
        return v


class RubricScores(BaseModel):
    model_config = ConfigDict(frozen=True)

    scores: dict[str, float]

    @field_validator("scores")
    @classmethod
    def _validate_scores(cls, v: dict[str, float]) -> dict[str, float]:
        for k, val in v.items():
            if not (0.0 <= val <= 10.0):
                raise ValueError(f"rubric score '{k}' must be between 0.0 and 10.0")
        return v


class Verdict(BaseModel):
    model_config = ConfigDict(frozen=True)

    accepted: bool
    score: float = Field(ge=0.0, le=10.0, description="Weighted composite")
    rubric: RubricScores
    issues: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class PlanNextDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    action: Literal["done", "add_phase"]
    next_phase_id: str | None = None
    rationale: str
