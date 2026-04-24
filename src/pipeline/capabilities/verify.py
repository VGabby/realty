import json
import sys
import time
from pathlib import Path

from google import genai
from google.genai import types

from pipeline.config import RunConfig
from pipeline.contracts import RubricScores, Verdict
from pipeline.errors import VerifyError
from pipeline.images import open_normalized_image

_REVIEW_RUBRIC = """You are a professional real estate photo quality reviewer.

Score this edited real estate photo on three axes (0.0–10.0 each):

1. **realism** (weight 0.4): Does the inpainting look photorealistic? No obvious AI artifacts?
2. **completeness** (weight 0.4): Were all out-of-place portable items removed?\
 Room looks listing-ready?
3. **artifacts** (weight 0.2): Are there residual shadows, edge seams, or texture\
 discontinuities? Higher = fewer artifacts.

Composite score = 0.4*realism + 0.4*completeness + 0.2*artifacts

Acceptance threshold:
- Phase 1 (broad removal): accept if composite >= 7.0
- Phase 2 (surgical fixes): accept if composite >= 8.0

Return a JSON object with this exact schema:
{
  "accepted": <boolean>,
  "score": <composite float, 2 decimal places>,
  "rubric": {
    "realism": <float>,
    "completeness": <float>,
    "artifacts": <float>
  },
  "issues": ["<specific problem observed>", ...],
  "suggestions": ["<actionable fix instruction>", ...]
}

TWO-SHOT EXAMPLES:

ACCEPT example:
{
  "accepted": true,
  "score": 8.2,
  "rubric": {"realism": 8.5, "completeness": 8.0, "artifacts": 7.5},
  "issues": [],
  "suggestions": []
}

REJECT example:
{
  "accepted": false,
  "score": 5.8,
  "rubric": {"realism": 6.0, "completeness": 5.0, "artifacts": 7.0},
  "issues": ["shadow of removed bottle still visible on coffee table", "edge seam on left wall"],
  "suggestions": ["blend the coffee table surface to remove the shadow gradient",\
 "smooth the wall texture seam on the left side"]
}

Return ONLY valid JSON, no markdown fences.
"""


def verify(
    image_path: Path,
    phase_id: int,
    config: RunConfig,
    rubric_override: str | None = None,
) -> Verdict:
    api_key = __import__("os").environ.get(config.api_key_env)
    if not api_key:
        raise VerifyError(f"Missing env var {config.api_key_env}")

    threshold = config.phase1_threshold if phase_id == 1 else config.phase2_threshold
    base_rubric = rubric_override if rubric_override is not None else _REVIEW_RUBRIC
    prompt = base_rubric + f"\n\nFor this image, accepted = (score >= {threshold})."

    client = genai.Client(api_key=api_key)

    img = open_normalized_image(image_path)
    contents = [prompt, img]

    for attempt in range(1, 3):
        t0 = time.monotonic()
        try:
            response = client.models.generate_content(
                model=config.review_model,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                ),
            )
            latency_ms = int((time.monotonic() - t0) * 1000)
            _log_request(config.review_model, latency_ms, response.usage_metadata)

            data = json.loads(response.text.strip())
            rubric = RubricScores(scores=data["rubric"])
            if rubric_override is None:
                s = rubric.scores
                composite = round(
                    0.4 * s["realism"] + 0.4 * s["completeness"] + 0.2 * s["artifacts"], 2
                )
                data["score"] = composite
                data["accepted"] = composite >= threshold
            else:
                data["accepted"] = data["score"] >= threshold
            data["rubric"] = rubric
            return Verdict.model_validate(data)
        except VerifyError:
            raise
        except Exception as exc:
            if attempt == 2:
                raise VerifyError(f"Failed to get valid verdict after 2 attempts: {exc}") from exc
            print(f"[verify] attempt {attempt} failed ({exc}), retrying", file=sys.stderr)

    raise VerifyError("Unreachable")


def _log_request(model: str, latency_ms: int, usage) -> None:
    def _safe_int(obj, attr: str):
        v = getattr(obj, attr, None) if obj is not None else None
        return int(v) if isinstance(v, (int, float)) else None

    record = {
        "model": model,
        "latency_ms": latency_ms,
        "prompt_tokens": _safe_int(usage, "prompt_token_count"),
        "response_tokens": _safe_int(usage, "candidates_token_count"),
    }
    print(json.dumps(record), file=sys.stderr)
