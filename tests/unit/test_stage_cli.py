"""Unit tests for the stage CLI."""

import hashlib
import io
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from pipeline.contracts import RubricScores, Verdict


def _fake_image_bytes() -> bytes:
    img = Image.new("RGB", (100, 100))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _make_edited(tmp_path: Path, phase_id: int, attempt: int) -> MagicMock:
    img_bytes = _fake_image_bytes()
    out = tmp_path / f"phase{phase_id}_attempt{attempt}.jpg"
    out.write_bytes(img_bytes)
    m = MagicMock()
    m.sha256 = hashlib.sha256(img_bytes).hexdigest()
    m.path = out
    m.phase_id = phase_id
    m.attempt = attempt
    m.prompt_used = "test"
    return m


def _make_verdict(score: float = 9.0, accepted: bool = True) -> Verdict:
    return Verdict(
        accepted=accepted,
        score=score,
        rubric=RubricScores(
            scores={
                "staging_authenticity": score,
                "style_coherence": score,
                "technical_quality": score,
            }
        ),
        issues=[],
        suggestions=[],
    )


def _write_skill_prompts(skill_dir: Path) -> None:
    prompts = skill_dir / "prompts"
    prompts.mkdir(parents=True)
    (prompts / "phase1_generate.md").write_text("Phase 1 staging prompt.", encoding="utf-8")
    (prompts / "phase2_refine.md").write_text("Phase 2 refine prompt.", encoding="utf-8")
    (prompts / "review_rubric.md").write_text("Review rubric.", encoding="utf-8")
    (skill_dir / "phases.json").write_text(
        json.dumps(
            {
                "skill_id": "virtual-staging",
                "default_entry_phase": "generate_staging",
                "phases": [
                    {
                        "phase_id": "generate_staging",
                        "name": "generate_staging",
                        "prompt_file": "prompts/phase1_generate.md",
                        "rubric_file": "prompts/review_rubric.md",
                        "threshold": 7.0,
                        "max_attempts": 3,
                        "description": "Add furniture.",
                        "when_to_add": "Always run first.",
                        "dependencies": [],
                    },
                    {
                        "phase_id": "refine_staging",
                        "name": "refine_staging",
                        "prompt_file": "prompts/phase2_refine.md",
                        "rubric_file": "prompts/review_rubric.md",
                        "threshold": 8.5,
                        "max_attempts": 2,
                        "description": "Fix artifacts.",
                        "when_to_add": "Add if score < 8.5.",
                        "dependencies": ["generate_staging"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture(autouse=True)
def fake_api_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-tests")


class TestStageCli:
    @patch("pipeline.capabilities.verify.genai")
    @patch("pipeline.capabilities.execute.genai")
    @patch("pipeline.capabilities.plan_next.genai")
    def test_happy_path(
        self, mock_plan_next_genai, mock_exec_genai, mock_verify_genai, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)

        # Input image
        img = Image.new("RGB", (200, 150), color=(10, 20, 30))
        input_path = tmp_path / "room.jpg"
        img.save(input_path)

        # Skill prompts
        skill_dir = tmp_path / ".claude" / "skills" / "virtual-staging"
        _write_skill_prompts(skill_dir)

        # Mock execute response
        img_bytes = _fake_image_bytes()
        part = MagicMock()
        part.inline_data = MagicMock()
        part.inline_data.data = img_bytes
        exec_response = MagicMock()
        exec_response.parts = [part]
        exec_response.usage_metadata = None
        exec_client = MagicMock()
        exec_client.models.generate_content.return_value = exec_response
        mock_exec_genai.Client.return_value = exec_client

        # Mock verify response
        verdict_data = {
            "accepted": True,
            "score": 9.0,
            "rubric": {
                "staging_authenticity": 9.0,
                "style_coherence": 9.0,
                "technical_quality": 9.0,
            },
            "issues": [],
            "suggestions": [],
        }
        verify_response = MagicMock()
        verify_response.text = json.dumps(verdict_data)
        verify_response.usage_metadata = None
        verify_client = MagicMock()
        verify_client.models.generate_content.return_value = verify_response
        mock_verify_genai.Client.return_value = verify_client

        # Mock plan_next: always add refine_staging after generate_staging
        plan_next_data = {
            "action": "add_phase",
            "next_phase_id": "refine_staging",
            "rationale": "test",
        }
        plan_next_response = MagicMock()
        plan_next_response.text = json.dumps(plan_next_data)
        plan_next_response.usage_metadata = None
        plan_next_client = MagicMock()
        plan_next_client.models.generate_content.return_value = plan_next_response
        mock_plan_next_genai.Client.return_value = plan_next_client

        from typer.testing import CliRunner

        from pipeline.cli.stage import app

        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                str(input_path),
                "--skill-dir",
                str(skill_dir),
                "--run-id",
                "2026-04-24T10-00-00Z_stage_room",
            ],
        )

        assert result.exit_code == 0, result.output
        run_dir = tmp_path / "runs" / "2026-04-24T10-00-00Z_stage_room"
        assert (run_dir / "final.jpg").exists()
        manifest = json.loads((run_dir / "manifest.json").read_text())
        assert manifest["outcome"] == "accepted"
        assert manifest["phases"][0]["name"] == "generate_staging"
        assert manifest["phases"][1]["name"] == "refine_staging"

    def test_missing_skill_dir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        img = Image.new("RGB", (100, 100))
        input_path = tmp_path / "room.jpg"
        img.save(input_path)

        from typer.testing import CliRunner

        from pipeline.cli.stage import app

        runner = CliRunner()
        result = runner.invoke(
            app,
            [str(input_path), "--skill-dir", str(tmp_path / "nonexistent")],
        )

        assert result.exit_code == 2
        assert "phases.json not found" in result.output

    def test_missing_input(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        from typer.testing import CliRunner

        from pipeline.cli.stage import app

        runner = CliRunner()
        result = runner.invoke(app, [str(tmp_path / "does_not_exist.jpg")])

        assert result.exit_code == 1
        assert "input not found" in result.output
