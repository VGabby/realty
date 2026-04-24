"""declutter — real estate photo declutter CLI orchestrator."""

import shutil
import time
from datetime import UTC, datetime
from pathlib import Path

import typer

app = typer.Typer(help="Declutter a real estate photo using the dynamic Gemini agent loop.")

_SKILL_DIR_DEFAULT = ".claude/skills/real-estate-declutter"


@app.command()
def main(
    input_path: Path = typer.Argument(..., help="Input image path"),
    run_id: str | None = typer.Option(None, help="Override run ID (default: timestamp_stem)"),
    config: Path | None = typer.Option(None, help="RunConfig JSON path"),
) -> None:
    """
    Example: declutter samples/livingroom-01.jpg

    Runs the declutter agent loop and writes results to runs/<id>/.
    """
    from pipeline.agent import run_agent
    from pipeline.capabilities.plan import plan as do_plan
    from pipeline.config import RunConfig
    from pipeline.errors import DeclutterError
    from pipeline.manifest import ErrorRecord, InputRef, Manifest, write_manifest
    from pipeline.narration import Narration

    if not input_path.exists():
        typer.echo(f"Error: input not found: {input_path}", err=True)
        raise typer.Exit(1)

    run_config = RunConfig.from_env()
    if config and config.exists():
        run_config = RunConfig.model_validate_json(config.read_text())

    stem = input_path.stem.replace(" ", "_")
    rid = run_id or Manifest.make_run_id(stem)
    run_dir = Path("runs") / rid
    run_dir.mkdir(parents=True, exist_ok=True)

    dest_input = run_dir / "input.jpg"
    shutil.copy2(input_path, dest_input)

    created_at = datetime.now(UTC)
    t_start = time.monotonic()

    input_ref = InputRef.from_file(dest_input, base=run_dir)
    manifest = Manifest(
        run_id=rid,
        created_at=created_at,
        input=input_ref,
        config=run_config,
    )
    narration = Narration(run_dir / "narration.md")
    narration.write_header(manifest)
    write_manifest(run_dir / "manifest.json", manifest)

    def halt_on_error(phase: str, exc: Exception, stderr_tail: str = "") -> None:
        manifest.outcome = "error"
        manifest.error = ErrorRecord(phase=phase, message=str(exc), stderr_tail=stderr_tail[-2048:])
        manifest.completed_at = datetime.now(UTC)
        write_manifest(run_dir / "manifest.json", manifest)
        narration.write_error(phase, str(exc), stderr_tail[-2048:])
        typer.echo(f"Error in {phase}: {exc}", err=True)
        raise typer.Exit(2)

    # Plan — Gemini identifies what to remove
    narration._append("## Plan\n\n")
    try:
        edit_plan = do_plan(dest_input, run_config)
        plan_path = run_dir / "plan.json"
        plan_path.write_text(edit_plan.model_dump_json(indent=2), encoding="utf-8")
        manifest.plan = edit_plan
        narration.write_plan(edit_plan)
        write_manifest(run_dir / "manifest.json", manifest)
    except DeclutterError as exc:
        halt_on_error("plan", exc)

    try:
        run_agent(
            input_path=dest_input,
            skill_dir=Path(_SKILL_DIR_DEFAULT),
            run_dir=run_dir,
            edit_plan=edit_plan,
            manifest=manifest,
            narration=narration,
            config=run_config,
        )
    except DeclutterError as exc:
        halt_on_error("agent", exc)

    wall_seconds = time.monotonic() - t_start
    narration.write_final(manifest, wall_seconds)

    typer.echo(str(run_dir))


if __name__ == "__main__":
    app()
