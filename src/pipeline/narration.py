"""Strict-template narration writer. No prose outside templates."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pipeline.contracts import EditPlan, PlanNextDecision
from pipeline.manifest import AttemptRecord, Manifest


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class Narration:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def _append(self, text: str) -> None:
        with self._path.open("a", encoding="utf-8") as f:
            f.write(text)

    def write_header(self, manifest: Manifest) -> None:
        inp = manifest.input
        cfg = manifest.config
        sha12 = inp.sha256[:12]
        self._append(
            f"# Run {manifest.run_id}\n\n"
            f"**Input:** {inp.path} ({sha12}, {inp.width}×{inp.height})\n"
            f"**Config:** edit={cfg.edit_model} · review={cfg.review_model}"
            f" · thresholds={cfg.phase1_threshold}/{cfg.phase2_threshold}\n"
            f"**Started:** {manifest.created_at.isoformat()}\n\n"
        )

    def write_plan(self, plan: EditPlan) -> None:
        remove_lines = "\n".join(f"  - {obj}" for obj in plan.removable_objects)
        keep_lines = "\n".join(f"  - {el}" for el in plan.structural_keep)
        self._append(
            f"## Plan\n\n"
            f"{plan.rationale}\n\n"
            f"- **Remove:**\n{remove_lines}\n"
            f"- **Keep:**\n{keep_lines}\n\n"
        )

    def write_phase_header(
        self, phase_id: int, phase_name: str, threshold: float, max_attempts: int
    ) -> None:
        self._append(
            f"## Phase {phase_id} — {phase_name}\n\n"
            f"Threshold: {threshold} · Max attempts: {max_attempts}\n\n"
        )

    def write_attempt(
        self,
        rec: AttemptRecord,
        prompt_file: str,
        run_dir: Path,
    ) -> None:
        verdict = rec.review
        sha12 = rec.edit_output.sha256[:12]
        try:
            rel_path = Path(rec.edit_output.path).relative_to(run_dir)
        except ValueError:
            rel_path = Path(rec.edit_output.path)

        hint_suffix = f' + hint: "{rec.hint}"' if rec.hint else ""
        issues_str = "; ".join(verdict.issues) if verdict.issues else "none"

        if rec.accepted:
            decision = "- Decision: accept → advance"
        elif rec.retry_reason:
            hint = rec.hint or ""
            decision = f'- Decision: retry — hint: "{hint}"'
        else:
            decision = (
                f"- Decision: escalate — best score {verdict.score} < threshold, using best attempt"
            )

        rubric_str = ", ".join(f"{k} {v}" for k, v in verdict.rubric.scores.items())
        self._append(
            f"### Attempt {rec.attempt}\n"
            f"- Prompt: `{prompt_file}`{hint_suffix}\n"
            f"- Output: `{rel_path}` ({sha12})\n"
            f"- Score: **{verdict.score}**/10"
            f" ({rubric_str})\n"
            f"- Accepted: {rec.accepted}\n"
            f"- Issues: {issues_str}\n"
            f"{decision}\n\n"
        )

    def write_plan_next_decision(self, decision: PlanNextDecision) -> None:
        if decision.action == "add_phase":
            action_str = f"add_phase → {decision.next_phase_id}"
        else:
            action_str = "done"
        self._append(
            f"## Planner Decision\n\n"
            f"- **Action:** {action_str}\n"
            f"- **Rationale:** {decision.rationale}\n\n"
        )

    def write_final(self, manifest: Manifest, wall_seconds: float) -> None:
        assert manifest.final_output is not None
        attempts_str = ", ".join(
            f"P{i + 1}={len(p.attempts)}" for i, p in enumerate(manifest.phases)
        )
        completed = manifest.completed_at.isoformat() if manifest.completed_at else "unknown"
        self._append(
            f"## Final\n"
            f"- **Outcome:** {manifest.outcome}\n"
            f"- **File:** `{manifest.final_output.path}`\n"
            f"- **Attempts:** {attempts_str}\n"
            f"- **Wall time:** {wall_seconds:.1f}s\n"
            f"- **Completed:** {completed}\n"
        )

    def write_error(self, phase: str, message: str, stderr_tail: str) -> None:
        self._append(
            f"## Error\n"
            f"- **Phase:** {phase}\n"
            f"- **Message:** {message}\n"
            f"- **Stderr tail:**\n"
            f"  ```\n"
            f"  {stderr_tail}\n"
            f"  ```\n"
        )
