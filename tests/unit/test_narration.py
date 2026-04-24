from datetime import UTC, datetime

from pipeline.config import RunConfig
from pipeline.contracts import RubricScores, Verdict
from pipeline.manifest import AttemptRecord, ImageRef, InputRef, Manifest
from pipeline.narration import Narration

_SHA = "a" * 64
_UTC = datetime(2026, 4, 22, 10, 0, 0, tzinfo=UTC)


def _make_manifest() -> Manifest:
    return Manifest(
        run_id="2026-04-22T10-00-00Z_test",
        created_at=_UTC,
        input=InputRef(path="input.jpg", sha256=_SHA, width=1920, height=1080),
        config=RunConfig(),
    )


def _make_verdict(score: float = 8.0, accepted: bool = True) -> Verdict:
    return Verdict(
        accepted=accepted,
        score=score,
        rubric=RubricScores(scores={"realism": 8.0, "completeness": 8.0, "artifacts": 8.0}),
        issues=[] if accepted else ["shadow remains"],
        suggestions=["blend shadow"] if not accepted else [],
    )


def test_write_header(tmp_path):
    n = Narration(tmp_path / "narration.md")
    m = _make_manifest()
    n.write_header(m)
    text = (tmp_path / "narration.md").read_text()
    assert "# Run 2026-04-22T10-00-00Z_test" in text
    assert "1920×1080" in text
    assert "gemini-3.1-flash-image-preview" in text


def test_write_plan(tmp_path):
    from pipeline.contracts import EditPlan

    n = Narration(tmp_path / "narration.md")
    plan = EditPlan(
        removable_objects=["bottle", "laundry"],
        structural_keep=["sofa"],
        rationale="Clean for MLS.",
        phase1_instructions="remove",
        phase2_instructions="fix",
    )
    n.write_plan(plan)
    text = (tmp_path / "narration.md").read_text()
    assert "bottle" in text
    assert "sofa" in text
    assert "Clean for MLS." in text


def test_write_phase_header(tmp_path):
    n = Narration(tmp_path / "narration.md")
    n.write_phase_header(1, "broad_removal", 7.0, 3)
    text = (tmp_path / "narration.md").read_text()
    assert "## Phase 1" in text
    assert "Threshold: 7.0" in text


def test_write_attempt_accepted(tmp_path):
    n = Narration(tmp_path / "narration.md")
    rec = AttemptRecord(
        attempt=1,
        started_at=_UTC,
        completed_at=_UTC,
        hint=None,
        edit_output=ImageRef(path="phase1_attempt1.jpg", sha256=_SHA, width=100, height=100),
        review=_make_verdict(score=8.0, accepted=True),
        accepted=True,
        retry_reason=None,
    )
    n.write_attempt(rec, "prompts/phase1_broad.md", tmp_path)
    text = (tmp_path / "narration.md").read_text()
    assert "### Attempt 1" in text
    assert "accept → advance" in text
    assert "**8.0**/10" in text


def test_write_attempt_retry(tmp_path):
    n = Narration(tmp_path / "narration.md")
    rec = AttemptRecord(
        attempt=1,
        started_at=_UTC,
        completed_at=_UTC,
        hint=None,
        edit_output=ImageRef(path="phase1_attempt1.jpg", sha256=_SHA, width=100, height=100),
        review=_make_verdict(score=5.0, accepted=False),
        accepted=False,
        retry_reason="score 5.0 < 7.0; hint: 'blend shadow'",
    )
    n.write_attempt(rec, "prompts/phase1_broad.md", tmp_path)
    text = (tmp_path / "narration.md").read_text()
    assert "retry" in text


def test_write_final(tmp_path):
    n = Narration(tmp_path / "narration.md")
    m = _make_manifest()
    m.outcome = "accepted"
    m.completed_at = _UTC
    m.final_output = ImageRef(path="final.jpg", sha256=_SHA, width=100, height=100)
    n.write_final(m, wall_seconds=42.5)
    text = (tmp_path / "narration.md").read_text()
    assert "## Final" in text
    assert "accepted" in text
    assert "42.5s" in text


def test_write_error(tmp_path):
    n = Narration(tmp_path / "narration.md")
    n.write_error("phase1", "timeout", "last stderr lines here")
    text = (tmp_path / "narration.md").read_text()
    assert "## Error" in text
    assert "timeout" in text
