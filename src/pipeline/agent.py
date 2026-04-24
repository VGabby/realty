"""Generic Plan-Execute-Review-Replan agent loop."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

from pipeline.capabilities.execute import execute as do_execute
from pipeline.capabilities.plan_next import plan_next as do_plan_next
from pipeline.capabilities.verify import verify as do_verify
from pipeline.config import RunConfig
from pipeline.contracts import EditPlan
from pipeline.errors import AgentError, DeclutterError
from pipeline.images import open_normalized_image
from pipeline.manifest import AttemptRecord, ImageRef, Manifest, PhaseRecord, write_manifest
from pipeline.narration import Narration
from pipeline.phase_catalog import PhaseCatalog, PhaseSpec

MAX_PHASES = 5


def _synthesize_hint(verdict) -> str:
    if verdict.suggestions:
        return verdict.suggestions[0][:120]
    if verdict.issues:
        return f"Fix: {verdict.issues[0]}"[:120]
    return "Improve overall realism and completeness."


def run_agent(
    input_path: Path,
    skill_dir: Path,
    run_dir: Path,
    edit_plan: EditPlan,
    manifest: Manifest,
    narration: Narration,
    config: RunConfig,
) -> None:
    """Run the Plan-Execute-Review-Replan loop.

    Starts with catalog.default_entry_phase, executes it, reviews it, and calls
    plan_next() to decide whether to add another phase. Stops when plan_next()
    says "done", no available phases remain, or MAX_PHASES is reached.

    Mutates manifest in-place (appends PhaseRecord entries, sets final_output and outcome).
    Writes manifest.json to run_dir after each phase.
    """
    catalog = PhaseCatalog.from_skill_dir(skill_dir)
    manifest.skill_id = catalog.skill_id
    completed: list[tuple[PhaseSpec, PhaseRecord]] = []
    current_source = input_path
    next_phase_id: str | None = catalog.default_entry_phase

    while next_phase_id is not None and len(completed) < MAX_PHASES:
        spec = catalog.get(next_phase_id)

        # Enforce dependencies: all deps must be in completed
        completed_ids = {s.phase_id for s, _ in completed}
        missing_deps = [d for d in spec.dependencies if d not in completed_ids]
        if missing_deps:
            raise AgentError(
                f"Phase '{spec.phase_id}' requires dependencies {missing_deps} "
                f"which have not been completed yet."
            )

        # 1-indexed phase_index based on loop position
        phase_index = len(completed) + 1
        phase_record = _run_phase(
            spec=spec,
            phase_index=phase_index,
            source=current_source,
            run_dir=run_dir,
            edit_plan=edit_plan,
            config=config,
            narration=narration,
            skill_dir=skill_dir,
        )

        completed.append((spec, phase_record))
        manifest.phases.append(phase_record)
        write_manifest(run_dir / "manifest.json", manifest)

        assert phase_record.final_output is not None
        current_source = run_dir / phase_record.final_output.path

        # Determine available phases: dependency-satisfied and not yet run
        updated_completed_ids = {s.phase_id for s, _ in completed}
        available = [
            p
            for p in catalog.phases
            if p.phase_id not in updated_completed_ids
            and all(d in updated_completed_ids for d in p.dependencies)
        ]

        if not available:
            # No more phases possible — stop without an LLM call
            break

        decision = do_plan_next(completed, catalog, available, config)
        narration.write_plan_next_decision(decision)

        if decision.action == "add_phase":
            next_phase_id = decision.next_phase_id
        else:
            next_phase_id = None

    if not completed:
        raise AgentError("Agent loop completed without running any phase.")

    # Finalize: copy last phase output to final.jpg
    last_spec, last_record = completed[-1]
    assert last_record.final_output is not None
    last_output_path = run_dir / last_record.final_output.path
    final_path = run_dir / "final.jpg"
    shutil.copy2(last_output_path, final_path)
    final_ref = ImageRef.from_file(final_path, base=run_dir)
    manifest.final_output = final_ref
    manifest.outcome = "accepted" if all(r.accepted for _, r in completed) else "escalated"
    manifest.completed_at = datetime.now(UTC)
    write_manifest(run_dir / "manifest.json", manifest)


def _run_phase(
    spec: PhaseSpec,
    phase_index: int,
    source: Path,
    run_dir: Path,
    edit_plan: EditPlan,
    config: RunConfig,
    narration: Narration,
    skill_dir: Path,
) -> PhaseRecord:
    """Execute a single phase (multiple attempts) and return the PhaseRecord."""
    # Load prompt and rubric from skill_dir
    prompt_path = skill_dir / spec.prompt_file
    rubric_path = skill_dir / spec.rubric_file

    if not prompt_path.exists():
        raise AgentError(f"Prompt file not found: {prompt_path}")
    if not rubric_path.exists():
        raise AgentError(f"Rubric file not found: {rubric_path}")

    system_prompt = prompt_path.read_text(encoding="utf-8")
    rubric_text = rubric_path.read_text(encoding="utf-8")

    phase_record = PhaseRecord(
        phase_id=phase_index,
        name=spec.name,
        prompt_file=str(spec.prompt_file),
    )
    narration.write_phase_header(phase_index, spec.name, spec.threshold, spec.max_attempts)
    hint: str | None = None

    for attempt_num in range(1, spec.max_attempts + 1):
        started_at = datetime.now(UTC)
        out_path = run_dir / f"phase{phase_index}_attempt{attempt_num}.jpg"

        try:
            edited = do_execute(
                source,
                edit_plan,
                phase_index,
                attempt_num,
                hint,
                out_path,
                config,
                system_prompt=system_prompt,
            )
            verdict = do_verify(out_path, phase_index, config, rubric_override=rubric_text)
        except DeclutterError:
            raise

        completed_at = datetime.now(UTC)
        accepted = verdict.score >= spec.threshold

        retry_reason: str | None = None
        if not accepted and attempt_num < spec.max_attempts:
            hint = _synthesize_hint(verdict)
            retry_reason = f"score {verdict.score} < {spec.threshold}; hint: {hint!r}"

        with open_normalized_image(out_path) as img:
            w, h = img.size
        edit_output = ImageRef(
            path=str(out_path.relative_to(run_dir)),
            sha256=edited.sha256,
            width=w,
            height=h,
        )

        rec = AttemptRecord(
            attempt=attempt_num,
            started_at=started_at,
            completed_at=completed_at,
            hint=hint if attempt_num > 1 else None,
            edit_output=edit_output,
            review=verdict,
            accepted=accepted,
            retry_reason=retry_reason,
        )
        phase_record.attempts.append(rec)
        narration.write_attempt(rec, str(spec.prompt_file), run_dir)

        if accepted:
            phase_record.final_output = edit_output
            phase_record.accepted = True
            break
    else:
        # Escalate: pick best attempt
        best = max(phase_record.attempts, key=lambda a: a.review.score)
        phase_record.final_output = best.edit_output
        phase_record.accepted = False

    return phase_record
