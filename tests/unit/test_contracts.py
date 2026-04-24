import pytest
from pydantic import ValidationError

from pipeline.contracts import EditedImage, EditPlan, RubricScores, Verdict


def test_rubric_scores_bounds():
    r = RubricScores(scores={"realism": 5.0, "completeness": 5.0, "artifacts": 5.0})
    assert r.scores["realism"] == 5.0

    with pytest.raises(ValidationError):
        RubricScores(scores={"realism": 11.0, "completeness": 5.0, "artifacts": 5.0})
    with pytest.raises(ValidationError):
        RubricScores(scores={"realism": -1.0, "completeness": 5.0, "artifacts": 5.0})


def test_rubric_scores_arbitrary_axes():
    r = RubricScores(
        scores={"staging_authenticity": 9.0, "style_coherence": 8.5, "technical_quality": 7.0}
    )
    assert r.scores["staging_authenticity"] == 9.0


def test_verdict_immutable():
    v = Verdict(
        accepted=True,
        score=8.0,
        rubric=RubricScores(scores={"realism": 8.0, "completeness": 8.0, "artifacts": 8.0}),
    )
    with pytest.raises(ValidationError):
        v.accepted = False  # type: ignore[misc]


def test_edit_plan_structural_keep_required():
    with pytest.raises(ValidationError):
        EditPlan(structural_keep=[], rationale="test")


def test_edit_plan_valid():
    plan = EditPlan(
        removable_objects=["bottle on table"],
        structural_keep=["sofa", "rug"],
        rationale="Clean for MLS listing",
    )
    assert len(plan.removable_objects) == 1


def test_edit_plan_empty_removable_objects():
    plan = EditPlan(structural_keep=["all existing elements"], rationale="staging run")
    assert plan.removable_objects == []


def test_edit_plan_ignores_legacy_phase_fields():
    import json

    legacy_json = json.dumps(
        {
            "removable_objects": ["bottle"],
            "structural_keep": ["sofa"],
            "rationale": "test",
            "phase1_instructions": "old field",
            "phase2_instructions": "old field",
        }
    )
    plan = EditPlan.model_validate_json(legacy_json)
    assert plan.removable_objects == ["bottle"]
    assert not hasattr(plan, "phase1_instructions")


def test_edited_image_sha256_validation():
    from pathlib import Path

    valid_sha = "a" * 64
    img = EditedImage(
        path=Path("/tmp/out.jpg"), sha256=valid_sha, phase_id=1, attempt=1, prompt_used="test"
    )
    assert img.sha256 == valid_sha

    with pytest.raises(ValidationError):
        EditedImage(
            path=Path("/tmp/out.jpg"), sha256="tooshort", phase_id=1, attempt=1, prompt_used="test"
        )

    with pytest.raises(ValidationError):
        EditedImage(
            path=Path("/tmp/out.jpg"), sha256="G" * 64, phase_id=1, attempt=1, prompt_used="test"
        )


def test_verdict_json_roundtrip():
    v = Verdict(
        accepted=False,
        score=6.2,
        rubric=RubricScores(scores={"realism": 6.0, "completeness": 6.0, "artifacts": 7.0}),
        issues=["shadow remains"],
        suggestions=["blend shadow"],
    )
    restored = Verdict.model_validate_json(v.model_dump_json())
    assert restored == v
