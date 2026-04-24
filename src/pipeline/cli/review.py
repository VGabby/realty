"""pipeline-review CLI — review an edited image and emit a Verdict JSON."""

import json
from pathlib import Path

import typer

app = typer.Typer(help="Review an edited image and produce a verdict.")


@app.command()
def main(
    phase: int = typer.Option(..., help="Phase id: 1 or 2 (sets acceptance threshold)"),
    image: Path = typer.Option(..., help="Image path to review"),
    out: Path = typer.Option(..., help="Output verdict JSON path"),
    config: Path | None = typer.Option(None, help="RunConfig JSON path"),
    rubric_file: Path | None = typer.Option(None, help="Override review rubric (plain text file)"),
) -> None:
    """
    Example: pipeline-review --phase 1 --image edited.jpg --out verdict.json
    """
    from pipeline.capabilities.verify import verify as do_verify
    from pipeline.config import RunConfig
    from pipeline.errors import DeclutterError

    if not image.exists():
        typer.echo(f"Error: image not found: {image}", err=True)
        raise typer.Exit(1)
    if phase not in (1, 2):
        typer.echo("Error: --phase must be 1 or 2", err=True)
        raise typer.Exit(1)

    run_config = RunConfig.from_env()
    if config and config.exists():
        run_config = RunConfig.model_validate_json(config.read_text())

    rubric_override = (
        rubric_file.read_text(encoding="utf-8") if rubric_file and rubric_file.exists() else None
    )

    try:
        verdict = do_verify(image, phase, run_config, rubric_override)
    except DeclutterError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(2)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(verdict.model_dump_json(indent=2), encoding="utf-8")
    result = {
        "verdict_path": str(out),
        "accepted": verdict.accepted,
        "score": verdict.score,
    }
    typer.echo(json.dumps(result))


if __name__ == "__main__":
    app()
