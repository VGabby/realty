import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from pipeline.config import RunConfig
from pipeline.contracts import EditPlan, Verdict
from pipeline.images import open_normalized_image


class ManifestValidationError(Exception):
    pass


class ImageRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    sha256: str
    width: int
    height: int

    @field_validator("sha256")
    @classmethod
    def _validate_sha256(cls, v: str) -> str:
        if not re.fullmatch(r"[a-f0-9]{64}", v):
            raise ValueError("sha256 must be 64 lowercase hex chars")
        return v

    @classmethod
    def from_file(cls, path: Path, base: Path | None = None) -> "ImageRef":
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        with open_normalized_image(path) as img:
            w, h = img.size
        rel = str(path.relative_to(base)) if base else str(path)
        return cls(path=rel, sha256=digest, width=w, height=h)


class AttemptRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    attempt: int
    started_at: datetime
    completed_at: datetime
    hint: str | None
    edit_output: ImageRef
    review: Verdict
    accepted: bool
    retry_reason: str | None


class PhaseRecord(BaseModel):
    model_config = ConfigDict(frozen=False)

    phase_id: int
    name: str
    prompt_file: str
    attempts: list[AttemptRecord] = Field(default_factory=list)
    final_output: ImageRef | None = None
    accepted: bool = False


class InputRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    sha256: str
    width: int
    height: int

    @field_validator("sha256")
    @classmethod
    def _validate_sha256(cls, v: str) -> str:
        if not re.fullmatch(r"[a-f0-9]{64}", v):
            raise ValueError("sha256 must be 64 lowercase hex chars")
        return v

    @classmethod
    def from_file(cls, path: Path, base: Path | None = None) -> "InputRef":
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        with open_normalized_image(path) as img:
            w, h = img.size
        rel = str(path.relative_to(base)) if base else str(path)
        return cls(path=rel, sha256=digest, width=w, height=h)


class ErrorRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    phase: str
    message: str
    stderr_tail: str


class Manifest(BaseModel):
    model_config = ConfigDict(frozen=False)

    schema_version: int = 1
    run_id: str
    created_at: datetime
    completed_at: datetime | None = None
    input: InputRef
    config: RunConfig
    skill_id: str | None = None
    plan: EditPlan | None = None
    phases: list[PhaseRecord] = Field(default_factory=list)
    final_output: ImageRef | None = None
    outcome: Literal["accepted", "escalated", "error"] | None = None
    error: ErrorRecord | None = None
    narration_path: str = "narration.md"

    @field_validator("run_id")
    @classmethod
    def _validate_run_id(cls, v: str) -> str:
        pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z_[A-Za-z0-9._-]+$"
        if not re.fullmatch(pattern, v):
            raise ValueError(f"run_id must match pattern {pattern!r}, got {v!r}")
        return v

    @classmethod
    def make_run_id(cls, stem: str) -> str:
        now = datetime.now(UTC)
        ts = now.strftime("%Y-%m-%dT%H-%M-%SZ")
        return f"{ts}_{stem}"


def write_manifest(path: Path, manifest: Manifest) -> None:
    path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")


def read_manifest(path: Path) -> Manifest:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Manifest.model_validate(data)
    except Exception as exc:
        raise ManifestValidationError(f"Invalid manifest at {path}: {exc}") from exc
