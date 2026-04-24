import struct
from datetime import UTC, datetime

import pytest
from PIL import Image

from pipeline.config import RunConfig
from pipeline.contracts import RubricScores, Verdict
from pipeline.manifest import (
    AttemptRecord,
    ImageRef,
    InputRef,
    Manifest,
    ManifestValidationError,
    PhaseRecord,
    read_manifest,
    write_manifest,
)

_SHA = "a" * 64


def _exif_with_orientation(value: int) -> bytes:
    payload = bytearray()
    payload.extend(b"Exif\x00\x00")
    payload.extend(b"MM")
    payload.extend(struct.pack(">H", 42))
    payload.extend(struct.pack(">I", 8))
    payload.extend(struct.pack(">H", 1))
    payload.extend(struct.pack(">H", 0x0112))
    payload.extend(struct.pack(">H", 3))
    payload.extend(struct.pack(">I", 1))
    payload.extend(struct.pack(">H", value))
    payload.extend(b"\x00\x00")
    payload.extend(struct.pack(">I", 0))
    return bytes(payload)


def _make_manifest(run_id: str = "2026-04-22T10-00-00Z_test") -> Manifest:
    return Manifest(
        run_id=run_id,
        created_at=datetime(2026, 4, 22, 10, 0, 0, tzinfo=UTC),
        input=InputRef(path="input.jpg", sha256=_SHA, width=1920, height=1080),
        config=RunConfig(),
    )


def test_manifest_roundtrip(tmp_path):
    m = _make_manifest()
    path = tmp_path / "manifest.json"
    write_manifest(path, m)
    restored = read_manifest(path)
    assert restored.run_id == m.run_id
    assert restored.schema_version == 1
    assert restored.input.sha256 == _SHA


def test_manifest_run_id_pattern():
    with pytest.raises(Exception):
        _make_manifest(run_id="bad-id")

    valid = _make_manifest(run_id="2026-04-22T10-00-00Z_livingroom-01")
    assert valid.run_id.startswith("2026")


def test_manifest_invalid_raises(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"schema_version": 1, "run_id": "invalid"}', encoding="utf-8")
    with pytest.raises(ManifestValidationError):
        read_manifest(path)


def test_image_ref_sha_validation():
    with pytest.raises(Exception):
        ImageRef(path="x.jpg", sha256="nothex", width=100, height=100)

    ref = ImageRef(path="x.jpg", sha256=_SHA, width=100, height=100)
    assert ref.sha256 == _SHA


def test_manifest_default_fields():
    m = _make_manifest()
    assert m.phases == []
    assert m.error is None
    assert m.outcome is None
    assert m.completed_at is None


def test_write_then_read_preserves_phases(tmp_path):
    m = _make_manifest()
    verdict = Verdict(
        accepted=True,
        score=8.0,
        rubric=RubricScores(scores={"realism": 8.0, "completeness": 8.0, "artifacts": 8.0}),
    )
    attempt = AttemptRecord(
        attempt=1,
        started_at=datetime(2026, 4, 22, 10, 0, 0, tzinfo=UTC),
        completed_at=datetime(2026, 4, 22, 10, 1, 0, tzinfo=UTC),
        hint=None,
        edit_output=ImageRef(path="phase1_attempt1.jpg", sha256=_SHA, width=100, height=100),
        review=verdict,
        accepted=True,
        retry_reason=None,
    )
    phase = PhaseRecord(phase_id=1, name="broad_removal", prompt_file="prompts/phase1_broad.md")
    phase.attempts.append(attempt)
    phase.final_output = attempt.edit_output
    phase.accepted = True
    m.phases.append(phase)

    path = tmp_path / "manifest.json"
    write_manifest(path, m)
    r = read_manifest(path)
    assert len(r.phases) == 1
    assert r.phases[0].accepted is True
    assert r.phases[0].attempts[0].review.score == 8.0


def test_input_ref_uses_normalized_orientation(tmp_path):
    path = tmp_path / "input.jpg"
    Image.new("RGB", (40, 20), color=(128, 64, 32)).save(path, exif=_exif_with_orientation(6))

    ref = InputRef.from_file(path)
    assert ref.width == 20
    assert ref.height == 40


def test_image_ref_uses_normalized_orientation(tmp_path):
    path = tmp_path / "output.jpg"
    Image.new("RGB", (40, 20), color=(128, 64, 32)).save(path, exif=_exif_with_orientation(6))

    ref = ImageRef.from_file(path)
    assert ref.width == 20
    assert ref.height == 40
