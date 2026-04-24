"""plan_next capability: LLM call (review model) to decide if another phase should run."""

from __future__ import annotations

import json
import sys
import time

from google import genai
from google.genai import types

from pipeline.config import RunConfig
from pipeline.contracts import PlanNextDecision
from pipeline.errors import PlanNextError
from pipeline.manifest import PhaseRecord
from pipeline.phase_catalog import PhaseCatalog, PhaseSpec

_PLAN_NEXT_SCHEMA = """{
  "action": "done" | "add_phase",
  "next_phase_id": "<phase_id string> or null",
  "rationale": "<one sentence explaining the decision>"
}"""


def _build_prompt(
    completed: list[tuple[PhaseSpec, PhaseRecord]],
    available: list[PhaseSpec],
) -> str:
    lines: list[str] = [
        "You are a pipeline orchestrator deciding whether to run an additional processing phase.",
        "",
        "## Completed phases",
    ]
    for spec, record in completed:
        best_attempt = (
            max(record.attempts, key=lambda a: a.review.score) if record.attempts else None
        )
        if best_attempt:
            verdict = best_attempt.review
            issues_str = "; ".join(verdict.issues) if verdict.issues else "none"
            suggestions_str = "; ".join(verdict.suggestions) if verdict.suggestions else "none"
            lines.append(
                f"- **{spec.name}** (phase_id={spec.phase_id}): "
                f"score={verdict.score}, accepted={record.accepted}, "
                f"issues=[{issues_str}], suggestions=[{suggestions_str}]"
            )
        else:
            lines.append(f"- **{spec.name}** (phase_id={spec.phase_id}): no attempts recorded")

    lines += [
        "",
        "## Available phases (dependency-satisfied, not yet run)",
    ]
    for spec in available:
        lines.append(
            f"- **{spec.name}** (phase_id={spec.phase_id}): {spec.description} "
            f"When to add: {spec.when_to_add}"
        )

    lines += [
        "",
        "## Decision",
        "Based on the completed phase results above, decide whether to add another phase or stop.",
        "If the result quality is sufficient (high score, no critical issues), return action=done.",
        "If quality issues remain and an available phase would address them,"
        " return action=add_phase.",
        "",
        f"Return ONLY valid JSON matching this schema (no markdown fences):\n{_PLAN_NEXT_SCHEMA}",
        "",
        "Rules:",
        '- If action is "done", set next_phase_id to null.',
        '- If action is "add_phase", set next_phase_id to one of the available'
        " phase_ids listed above.",
        "- rationale must be a single sentence.",
    ]
    return "\n".join(lines)


def plan_next(
    completed: list[tuple[PhaseSpec, PhaseRecord]],
    catalog: PhaseCatalog,
    available: list[PhaseSpec],
    config: RunConfig,
) -> PlanNextDecision:
    """Call the review model to decide whether to add another phase.

    Retries once on invalid/unparseable response, then raises PlanNextError.
    """
    api_key = __import__("os").environ.get(config.api_key_env)
    if not api_key:
        raise PlanNextError(f"Missing env var {config.api_key_env}")

    prompt = _build_prompt(completed, available)
    client = genai.Client(api_key=api_key)
    valid_phase_ids = {spec.phase_id for spec in catalog.phases}

    last_exc: Exception | None = None
    for attempt in range(1, 3):
        t0 = time.monotonic()
        try:
            response = client.models.generate_content(
                model=config.review_model,
                contents=[prompt],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                ),
            )
            latency_ms = int((time.monotonic() - t0) * 1000)
            _log_request(config.review_model, latency_ms, response.usage_metadata)

            data = json.loads(response.text.strip())
            decision = PlanNextDecision.model_validate(data)

            # Validate next_phase_id when action is add_phase
            if decision.action == "add_phase":
                if decision.next_phase_id is None:
                    raise ValueError("action=add_phase but next_phase_id is null")
                if decision.next_phase_id not in valid_phase_ids:
                    raise ValueError(
                        f"next_phase_id={decision.next_phase_id!r} is not a valid phase_id "
                        f"in catalog {catalog.skill_id!r}. Valid: {sorted(valid_phase_ids)}"
                    )

            return decision

        except PlanNextError:
            raise
        except Exception as exc:
            last_exc = exc
            if attempt == 2:
                raise PlanNextError(f"plan_next failed after 2 attempts: {exc}") from exc
            print(f"[plan_next] attempt {attempt} failed ({exc}), retrying", file=sys.stderr)

    raise PlanNextError(f"plan_next failed: {last_exc}")  # unreachable but mypy-safe


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
