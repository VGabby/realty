"""Integration test — hits live Gemini API. Requires GEMINI_API_KEY."""

from pathlib import Path

import pytest

from pipeline.manifest import read_manifest


@pytest.mark.integration
def test_full_run_on_sample(tmp_path):
    import subprocess
    import sys

    sample = Path("samples/test_vs.jpg")
    if not sample.exists():
        pytest.skip("Sample image not found; add samples/livingroom-01.jpg")

    import shutil

    declutter_bin = shutil.which("declutter") or str(Path(sys.executable).parent / "declutter")
    result = subprocess.run(
        [declutter_bin, str(sample)],
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, f"CLI failed:\n{result.stderr}"

    run_dir = Path(result.stdout.strip())
    assert run_dir.exists()

    manifest = read_manifest(run_dir / "manifest.json")
    assert manifest.outcome in ("accepted", "escalated")
    assert manifest.schema_version == 1
    assert (run_dir / "final.jpg").exists()
    assert (run_dir / "narration.md").exists()
