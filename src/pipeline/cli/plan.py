"""pipeline-plan CLI — call Gemini to produce an EditPlan JSON."""

import json
from pathlib import Path

import typer

app = typer.Typer(help="Generate a declutter plan for an image.")


@app.command()
def main(
    input: Path = typer.Option(..., help="Input image path"),
    out: Path = typer.Option(..., help="Output plan JSON path"),
    config: Path = typer.Option(None, help="RunConfig JSON path (uses defaults if omitted)"),
) -> None:
    """
    Example: pipeline-plan --input photo.jpg --out plan.json
    """
    from pipeline.capabilities.plan import plan as do_plan
    from pipeline.config import RunConfig
    from pipeline.errors import DeclutterError

    if not input.exists():
        typer.echo(f"Error: input file not found: {input}", err=True)
        raise typer.Exit(1)

    run_config = RunConfig.from_env()
    if config and config.exists():
        run_config = RunConfig.model_validate_json(config.read_text())

    try:
        edit_plan = do_plan(input, run_config)
    except DeclutterError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(2)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(edit_plan.model_dump_json(indent=2), encoding="utf-8")
    result = {"plan_path": str(out), "removable_count": len(edit_plan.removable_objects)}
    typer.echo(json.dumps(result))


if __name__ == "__main__":
    app()
