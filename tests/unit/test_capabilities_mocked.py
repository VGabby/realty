"""Unit tests for capabilities with mocked Gemini SDK."""

import hashlib
import json
import struct
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from pipeline.config import RunConfig
from pipeline.contracts import EditPlan
from pipeline.errors import ExecuteError, PlanError, VerifyError


@pytest.fixture(autouse=True)
def fake_api_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-tests")


# --- helpers ---


def _make_image(tmp_path: Path, name: str = "test.jpg") -> Path:
    p = tmp_path / name
    img = Image.new("RGB", (100, 100), color=(128, 64, 32))
    img.save(p)
    return p


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


def _make_oriented_image(
    tmp_path: Path, name: str = "oriented.jpg", size: tuple[int, int] = (40, 20)
) -> Path:
    p = tmp_path / name
    img = Image.new("RGB", size, color=(128, 64, 32))
    img.save(p, exif=_exif_with_orientation(6))
    return p


def _make_plan_json() -> str:
    return json.dumps(
        {
            "removable_objects": ["plastic bottle on coffee table"],
            "structural_keep": ["sofa", "rug"],
            "rationale": "Remove clutter for MLS listing.",
        }
    )


def _make_verdict_json(score: float = 8.5) -> str:
    return json.dumps(
        {
            "accepted": score >= 7.0,
            "score": score,
            "rubric": {"realism": score, "completeness": score, "artifacts": score},
            "issues": [],
            "suggestions": [],
        }
    )


def _mock_client(mock_genai, response):
    """Wire mock_genai.Client(...).models.generate_content to return response."""
    client_instance = MagicMock()
    client_instance.models.generate_content.return_value = response
    mock_genai.Client.return_value = client_instance
    return client_instance


def _mock_client_side_effect(mock_genai, responses):
    client_instance = MagicMock()
    client_instance.models.generate_content.side_effect = responses
    mock_genai.Client.return_value = client_instance
    return client_instance


# --- plan tests ---


class TestPlan:
    @patch("pipeline.capabilities.plan.genai")
    def test_happy_path(self, mock_genai, tmp_path):
        img_path = _make_image(tmp_path)
        response = MagicMock()
        response.text = _make_plan_json()
        response.usage_metadata = None
        _mock_client(mock_genai, response)

        from pipeline.capabilities.plan import plan

        result = plan(img_path, RunConfig())
        assert len(result.removable_objects) == 1
        assert result.removable_objects[0] == "plastic bottle on coffee table"

    @patch("pipeline.capabilities.plan.genai")
    def test_retry_then_success(self, mock_genai, tmp_path):
        img_path = _make_image(tmp_path)
        bad = MagicMock()
        bad.text = "not json at all"
        bad.usage_metadata = None
        good = MagicMock()
        good.text = _make_plan_json()
        good.usage_metadata = None
        _mock_client_side_effect(mock_genai, [bad, good])

        from pipeline.capabilities.plan import plan

        result = plan(img_path, RunConfig())
        assert result.removable_objects[0] == "plastic bottle on coffee table"

    @patch("pipeline.capabilities.plan.genai")
    def test_two_failures_raise(self, mock_genai, tmp_path):
        img_path = _make_image(tmp_path)
        bad = MagicMock()
        bad.text = "invalid json {"
        bad.usage_metadata = None
        _mock_client(mock_genai, bad)

        from pipeline.capabilities.plan import plan

        with pytest.raises(PlanError):
            plan(img_path, RunConfig())

    @patch("pipeline.capabilities.plan.genai")
    def test_normalizes_input_orientation(self, mock_genai, tmp_path):
        img_path = _make_oriented_image(tmp_path)
        response = MagicMock()
        response.text = _make_plan_json()
        response.usage_metadata = None
        client = _mock_client(mock_genai, response)

        from pipeline.capabilities.plan import plan

        plan(img_path, RunConfig())

        sent_image = client.models.generate_content.call_args.kwargs["contents"][1]
        assert sent_image.size == (20, 40)
        assert sent_image.getexif().get(0x0112) is None


# --- execute tests ---


def _make_edit_plan() -> EditPlan:
    return EditPlan(
        removable_objects=["bottle"],
        structural_keep=["sofa"],
        rationale="test",
    )


def _fake_image_bytes() -> bytes:
    import io

    img = Image.new("RGB", (100, 100))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


class TestExecute:
    @patch("pipeline.capabilities.execute.genai")
    def test_happy_path(self, mock_genai, tmp_path):
        out_path = tmp_path / "out.jpg"
        img_bytes = _fake_image_bytes()

        part = MagicMock()
        part.inline_data = MagicMock()
        part.inline_data.data = img_bytes
        response = MagicMock()
        response.parts = [part]
        response.usage_metadata = None
        _mock_client(mock_genai, response)

        from pipeline.capabilities.execute import execute

        result = execute(
            _make_image(tmp_path, "in.jpg"),
            _make_edit_plan(),
            1,
            1,
            None,
            out_path,
            RunConfig(),
            system_prompt="remove clutter",
        )
        assert out_path.exists()
        assert result.sha256 == hashlib.sha256(img_bytes).hexdigest()

    @patch("pipeline.capabilities.execute.genai")
    def test_no_image_raises(self, mock_genai, tmp_path):
        out_path = tmp_path / "out.jpg"
        response = MagicMock()
        response.parts = []
        response.candidates = []
        response.usage_metadata = None
        _mock_client(mock_genai, response)

        from pipeline.capabilities.execute import execute

        with pytest.raises(ExecuteError):
            execute(
                _make_image(tmp_path),
                _make_edit_plan(),
                1,
                1,
                None,
                out_path,
                RunConfig(),
                system_prompt="test",
            )

    @patch("pipeline.capabilities.execute.genai")
    def test_normalizes_input_orientation(self, mock_genai, tmp_path):
        out_path = tmp_path / "out.jpg"
        response = MagicMock()
        part = MagicMock()
        part.inline_data = MagicMock()
        part.inline_data.data = _fake_image_bytes()
        response.parts = [part]
        response.usage_metadata = None
        client = _mock_client(mock_genai, response)

        from pipeline.capabilities.execute import execute

        execute(
            _make_oriented_image(tmp_path, "in.jpg"),
            _make_edit_plan(),
            1,
            1,
            None,
            out_path,
            RunConfig(),
            system_prompt="test",
        )

        sent_image = client.models.generate_content.call_args.kwargs["contents"][1]
        assert sent_image.size == (20, 40)
        assert sent_image.getexif().get(0x0112) is None

    @patch("pipeline.capabilities.execute.genai")
    def test_image_size_passed_to_gemini(self, mock_genai, tmp_path):
        in_path = tmp_path / "large.jpg"
        out_path = tmp_path / "out.jpg"
        Image.new("RGB", (1024, 768), color=(10, 20, 30)).save(in_path)

        part = MagicMock()
        part.inline_data = MagicMock()
        part.inline_data.data = _fake_image_bytes()
        response = MagicMock()
        response.parts = [part]
        response.usage_metadata = None
        client = _mock_client(mock_genai, response)

        from pipeline.capabilities.execute import execute

        execute(
            in_path,
            _make_edit_plan(),
            1,
            1,
            None,
            out_path,
            RunConfig(image_size="512"),
            system_prompt="test",
        )

        call_kwargs = client.models.generate_content.call_args.kwargs
        assert call_kwargs["config"].image_config.image_size == "512"

    @patch("pipeline.capabilities.execute.genai")
    def test_phase3_uses_system_prompt_not_phase2_text(self, mock_genai, tmp_path):
        out_path = tmp_path / "out.jpg"
        part = MagicMock()
        part.inline_data = MagicMock()
        part.inline_data.data = _fake_image_bytes()
        response = MagicMock()
        response.parts = [part]
        response.usage_metadata = None
        client = _mock_client(mock_genai, response)

        from pipeline.capabilities.execute import execute

        execute(
            _make_image(tmp_path, "in.jpg"),
            _make_edit_plan(),
            3,
            1,
            None,
            out_path,
            RunConfig(),
            system_prompt="custom phase 3 prompt",
        )

        sent_prompt = client.models.generate_content.call_args.kwargs["contents"][0]
        assert "custom phase 3 prompt" in sent_prompt
        assert "SPECIFIC INSTRUCTIONS" not in sent_prompt

    def test_no_system_prompt_raises(self, tmp_path):
        from pipeline.capabilities.execute import execute

        with pytest.raises(TypeError):
            execute(
                _make_image(tmp_path, "in.jpg"),
                _make_edit_plan(),
                1,
                1,
                None,
                tmp_path / "out.jpg",
                RunConfig(),
            )

    @patch("pipeline.capabilities.execute.genai")
    def test_empty_removable_objects_omits_objects_block(self, mock_genai, tmp_path):
        out_path = tmp_path / "out.jpg"
        part = MagicMock()
        part.inline_data = MagicMock()
        part.inline_data.data = _fake_image_bytes()
        response = MagicMock()
        response.parts = [part]
        response.usage_metadata = None
        client = _mock_client(mock_genai, response)

        from pipeline.capabilities.execute import execute

        staging_plan = EditPlan(structural_keep=["walls"], rationale="staging")
        execute(
            _make_image(tmp_path, "in.jpg"),
            staging_plan,
            1,
            1,
            None,
            out_path,
            RunConfig(),
            system_prompt="stage this room",
        )

        sent_prompt = client.models.generate_content.call_args.kwargs["contents"][0]
        assert "OBJECTS TO REMOVE" not in sent_prompt

    @patch("pipeline.capabilities.execute.genai")
    def test_no_image_size_uses_no_config(self, mock_genai, tmp_path):
        in_path = tmp_path / "large.jpg"
        out_path = tmp_path / "out.jpg"
        Image.new("RGB", (1024, 768), color=(10, 20, 30)).save(in_path)

        part = MagicMock()
        part.inline_data = MagicMock()
        part.inline_data.data = _fake_image_bytes()
        response = MagicMock()
        response.parts = [part]
        response.usage_metadata = None
        client = _mock_client(mock_genai, response)

        from pipeline.capabilities.execute import execute

        execute(
            in_path,
            _make_edit_plan(),
            1,
            1,
            None,
            out_path,
            RunConfig(image_size=None),
            system_prompt="test",
        )

        call_kwargs = client.models.generate_content.call_args.kwargs
        assert call_kwargs["config"].response_modalities == ["IMAGE"]
        assert call_kwargs["config"].image_config is None


# --- verify tests ---


class TestVerify:
    @patch("pipeline.capabilities.verify.genai")
    def test_happy_path(self, mock_genai, tmp_path):
        img_path = _make_image(tmp_path)
        response = MagicMock()
        response.text = _make_verdict_json(score=8.5)
        response.usage_metadata = None
        _mock_client(mock_genai, response)

        from pipeline.capabilities.verify import verify

        verdict = verify(img_path, 1, RunConfig())
        assert verdict.accepted is True

    @patch("pipeline.capabilities.verify.genai")
    def test_retry_then_success(self, mock_genai, tmp_path):
        img_path = _make_image(tmp_path)
        bad = MagicMock()
        bad.text = "not json"
        bad.usage_metadata = None
        good = MagicMock()
        good.text = _make_verdict_json(score=7.5)
        good.usage_metadata = None
        _mock_client_side_effect(mock_genai, [bad, good])

        from pipeline.capabilities.verify import verify

        result = verify(img_path, 1, RunConfig())
        assert result.accepted is True

    @patch("pipeline.capabilities.verify.genai")
    def test_two_failures_raise(self, mock_genai, tmp_path):
        img_path = _make_image(tmp_path)
        bad = MagicMock()
        bad.text = "bad {"
        bad.usage_metadata = None
        _mock_client(mock_genai, bad)

        from pipeline.capabilities.verify import verify

        with pytest.raises(VerifyError):
            verify(img_path, 1, RunConfig())

    @patch("pipeline.capabilities.verify.genai")
    def test_normalizes_input_orientation(self, mock_genai, tmp_path):
        img_path = _make_oriented_image(tmp_path)
        response = MagicMock()
        response.text = _make_verdict_json(score=8.5)
        response.usage_metadata = None
        client = _mock_client(mock_genai, response)

        from pipeline.capabilities.verify import verify

        verify(img_path, 1, RunConfig())

        sent_image = client.models.generate_content.call_args.kwargs["contents"][1]
        assert sent_image.size == (20, 40)
        assert sent_image.getexif().get(0x0112) is None


# --- public API test ---


class TestPublicAPI:
    def test_public_api_exports(self):
        import pipeline

        for name in [
            "plan",
            "execute",
            "verify",
            "EditPlan",
            "EditedImage",
            "Verdict",
            "RubricScores",
            "RunConfig",
            "Manifest",
        ]:
            assert hasattr(pipeline, name), f"Missing public API: {name}"
