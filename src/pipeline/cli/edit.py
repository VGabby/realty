"""pipeline-edit CLI — call Gemini edit model for one phase/attempt."""

import json
from pathlib import Path

import typer

app = typer.Typer(help="Execute one edit pass on an image.")


@app.command()
def main(
    phase: int = typer.Option(..., help="Phase id: 1=broad removal, 2=surgical fixes"),
    input: Path = typer.Option(..., help="Input image path"),
    plan: Path = typer.Option(..., help="EditPlan JSON path"),
    attempt: int = typer.Option(1, help="1-indexed attempt number"),
    hint: str | None = typer.Option(None, help="Reviewer hint for retry"),
    out: Path = typer.Option(..., help="Output image path"),
    config: Path | None = typer.Option(None, help="RunConfig JSON path"),
    prompt_file: Path | None = typer.Option(None, help="Override base prompt (plain text file)"),
) -> None:
    """
    Example: pipeline-edit --phase 1 --input input.jpg --plan plan.json \
--attempt 1 --out edited.jpg
    """
    from pipeline.capabilities.execute import execute as do_execute
    from pipeline.config import RunConfig
    from pipeline.contracts import EditPlan
    from pipeline.errors import DeclutterError

    if not input.exists():
        typer.echo(f"Error: input not found: {input}", err=True)
        raise typer.Exit(1)
    if not plan.exists():
        typer.echo(f"Error: plan not found: {plan}", err=True)
        raise typer.Exit(1)
    if phase not in (1, 2):
        typer.echo("Error: --phase must be 1 or 2", err=True)
        raise typer.Exit(1)

    run_config = RunConfig.from_env()
    if config and config.exists():
        run_config = RunConfig.model_validate_json(config.read_text())

    edit_plan = EditPlan.model_validate_json(plan.read_text())
    system_prompt = (
        prompt_file.read_text(encoding="utf-8") if prompt_file and prompt_file.exists() else None
    )

    try:
        edited = do_execute(
            input, edit_plan, phase, attempt, hint or None, out, run_config, system_prompt
        )
    except DeclutterError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(2)

    result = {
        "path": str(edited.path),
        "sha256": edited.sha256,
        "phase_id": edited.phase_id,
        "attempt": edited.attempt,
    }
    typer.echo(json.dumps(result))


if __name__ == "__main__":
    app()
