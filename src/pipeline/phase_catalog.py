"""Phase catalog: structured phase metadata loaded from phases.json per skill dir."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from pipeline.errors import AgentError


class PhaseSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    phase_id: str
    name: str
    prompt_file: str  # relative to skill_dir
    rubric_file: str  # relative to skill_dir
    threshold: float
    max_attempts: int
    description: str
    when_to_add: str
    dependencies: list[str] = []


class PhaseCatalog(BaseModel):
    model_config = ConfigDict(frozen=True)

    skill_id: str
    default_entry_phase: str
    phases: list[PhaseSpec]

    def get(self, phase_id: str) -> PhaseSpec:
        for spec in self.phases:
            if spec.phase_id == phase_id:
                return spec
        raise KeyError(f"Phase '{phase_id}' not found in catalog '{self.skill_id}'")

    @classmethod
    def from_skill_dir(cls, skill_dir: Path) -> PhaseCatalog:
        phases_file = skill_dir / "phases.json"
        if not phases_file.exists():
            raise AgentError(f"phases.json not found in skill dir: {skill_dir}")
        try:
            data = json.loads(phases_file.read_text(encoding="utf-8"))
            return cls.model_validate(data)
        except AgentError:
            raise
        except Exception as exc:
            raise AgentError(f"Failed to load phases.json from {skill_dir}: {exc}") from exc
