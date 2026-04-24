import hashlib
import sys
import time
from pathlib import Path

from google import genai
from google.genai import types

from pipeline.config import RunConfig
from pipeline.contracts import EditedImage, EditPlan
from pipeline.errors import ExecuteError
from pipeline.images import open_normalized_image


def execute(
    input_path: Path,
    plan: EditPlan,
    phase_id: int,
    attempt: int,
    hint: str | None,
    output_path: Path,
    config: RunConfig,
    system_prompt: str,
) -> EditedImage:
    """Execute one edit pass. `system_prompt` is required — load it from the skill's prompt_file."""
    api_key = __import__("os").environ.get(config.api_key_env)
    if not api_key:
        raise ExecuteError(f"Missing env var {config.api_key_env}")

    client = genai.Client(api_key=api_key)

    prompt_parts = [system_prompt]
    if plan.removable_objects:
        items = "\n".join(f"- {obj}" for obj in plan.removable_objects)
        prompt_parts.append(f"\n\nOBJECTS TO REMOVE:\n{items}")
    if hint:
        prompt_parts.append(f"\n\nREVIEWER HINT (apply this correction):\n{hint}")
    full_prompt = "".join(prompt_parts)

    img = open_normalized_image(input_path)
    contents = [full_prompt, img]

    gen_config = types.GenerateContentConfig(
        response_modalities=["IMAGE"],
        image_config=types.ImageConfig(image_size=config.image_size) if config.image_size else None,
    )

    for attempt_num in range(1, 3):
        t0 = time.monotonic()
        try:
            response = client.models.generate_content(
                model=config.edit_model,
                contents=contents,
                config=gen_config,
            )
            latency_ms = int((time.monotonic() - t0) * 1000)
            _log_request(config.edit_model, latency_ms, response.usage_metadata)

            image_bytes = _extract_image_bytes(response)
            output_path.write_bytes(image_bytes)
            digest = hashlib.sha256(image_bytes).hexdigest()
            return EditedImage(
                path=output_path,
                sha256=digest,
                phase_id=phase_id,
                attempt=attempt,
                prompt_used=full_prompt,
            )
        except ExecuteError:
            raise
        except Exception as exc:
            if attempt_num == 2:
                raise ExecuteError(f"Edit failed after 2 attempts: {exc}") from exc
            print(f"[execute] attempt {attempt_num} failed ({exc}), retrying", file=sys.stderr)

    raise ExecuteError("Unreachable")


def _extract_image_bytes(response) -> bytes:
    for part in response.parts:
        if hasattr(part, "inline_data") and part.inline_data:
            return part.inline_data.data
    for cand in getattr(response, "candidates", []):
        for part in getattr(cand.content, "parts", []):
            if hasattr(part, "inline_data") and part.inline_data:
                return part.inline_data.data
    raise ExecuteError("Gemini response contained no image part")


def _log_request(model: str, latency_ms: int, usage) -> None:
    import json

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
