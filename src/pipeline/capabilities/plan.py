import json
import sys
import time
from pathlib import Path

from google import genai
from google.genai import types

from pipeline.config import RunConfig
from pipeline.contracts import EditPlan
from pipeline.errors import PlanError
from pipeline.images import open_normalized_image

_PLAN_PROMPT = """You are a professional real estate photo editor.

Analyze this image and produce a JSON declutter plan. Identify:
1. All portable, out-of-place items that should be removed\
 (clutter: personal items, trash, laundry, bottles, bags, etc.)
2. Structural and furniture elements that must be preserved\
 (sofa, rug, curtains, lamps, architectural features)

Produce a JSON object with this exact schema:
{
  "removable_objects": ["<specific item description>", ...],   // min 1 item
  "structural_keep": ["<element to preserve>", ...],           // min 1 item
  "rationale": "<one paragraph explanation of the declutter strategy>",
  "phase1_instructions": "<detailed instructions for broad removal pass>",
  "phase2_instructions": "<detailed instructions for surgical artifact cleanup pass>"
}

phase1_instructions should focus on: remove the listed objects completely, inpaint naturally.
phase2_instructions should focus on: fix residual shadows, edge discontinuities,\
 texture seams from phase 1.

Return ONLY valid JSON, no markdown fences.
"""


def plan(input_path: Path, config: RunConfig) -> EditPlan:
    api_key = __import__("os").environ.get(config.api_key_env)
    if not api_key:
        raise PlanError(f"Missing env var {config.api_key_env}")

    client = genai.Client(api_key=api_key)

    img = open_normalized_image(input_path)
    contents = [_PLAN_PROMPT, img]

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
            return EditPlan.model_validate(data)
        except Exception as exc:
            if attempt == 2:
                raise PlanError(f"Failed to parse plan after 2 attempts: {exc}") from exc
            print(f"[plan] attempt {attempt} failed ({exc}), retrying", file=sys.stderr)

    raise PlanError("Unreachable")


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
