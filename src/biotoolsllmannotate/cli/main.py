from __future__ import annotations

import typer
from pathlib import Path

from .. import __version__

app = typer.Typer(
    help="CLI to fetch Pub2Tools candidates, LLM‑assess, and emit bio.tools annotations.\n\nExamples:\n  python -m biotoolsllmannotate --from-date 2023-01-01 --to-date 2023-01-31 --min-score 0.6 --output out/payload.json --report out/report.jsonl\n  python -m biotoolsllmannotate --input tests/fixtures/pub2tools/sample.json --dry-run --report out/report.jsonl\n  python -m biotoolsllmannotate --offline --quiet\n  python -m biotoolsllmannotate --help\n\nNote: For faster fetching, configure EuropePMC-only mode in config.yaml or via environment variables.\nTip: Point pipeline.input_path or pub2tools.to_biotools_file at any Pub2Tools export JSON to skip invoking the CLI.",
    add_completion=False,
)


def _write_default_config_callback() -> None:
    """Write default config.yaml and exit."""
    import yaml
    from ..config import DEFAULT_CONFIG_YAML

    try:
        with open("config.yaml", "w") as f:
            yaml.dump(DEFAULT_CONFIG_YAML, f, sort_keys=False, default_flow_style=False)
        typer.echo("Default config.yaml written to ./config.yaml")
    except Exception as e:
        typer.echo(f"Error writing config.yaml: {e}", err=True)
        raise typer.Exit(code=1)

    raise typer.Exit(code=0)


def raise_exit() -> None:
    raise typer.Exit(code=0)


def _run_impl(
    version: bool = typer.Option(  # noqa: D401 - short help by design
        False,
        "--version",
        help="Show version and exit",
        callback=lambda v: (typer.echo(__version__), raise_exit()) if v else None,
        is_eager=True,
    ),
    write_default_config: bool = typer.Option(
        False,
        "--write-default-config",
        help="Write default config.yaml and exit.",
        callback=lambda v: _write_default_config_callback() if v else None,
        is_eager=True,
    ),
    edam_owl: str | None = typer.Option(
        None, "--edam-owl", help="EDAM OWL URL for Pub2Tools."
    ),
    idf: str | None = typer.Option(None, "--idf", help="IDF file URL for Pub2Tools."),
    idf_stemmed: str | None = typer.Option(
        None, "--idf-stemmed", help="Stemmed IDF file URL for Pub2Tools."
    ),
    firefox_path: str | None = typer.Option(
        None,
        "--firefox-path",
        help="Path to Firefox binary for Selenium (optional).",
    ),
    from_date: str | None = typer.Option(
        None,
        "--from-date",
        help="Start date for Pub2Tools fetching (YYYY-MM-DD).",
    ),
    since: str | None = typer.Option(
        None,
        "--since",
        help="Relative window (e.g. 7d, 30d) overriding --from-date",
    ),
    to_date: str | None = typer.Option(
        None,
        "--to-date",
        help="End date for Pub2Tools fetching (YYYY-MM-DD).",
    ),
    min_score: float = typer.Option(
        0.6,
        "--min-score",
        min=0.0,
        max=1.0,
        help="Minimum LS and relevance score for inclusion.",
    ),
    limit: int | None = typer.Option(
        None, "--limit", help="Max candidates to process."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Assess and report only; do not write payload."
    ),
    output: Path = typer.Option(
        Path("out/payload.json"),
        "--output",
        help="Output path for biotoolsSchema payload JSON.",
    ),
    report: Path = typer.Option(
        Path("out/report.jsonl"),
        "--report",
        help="Output path for per-candidate JSONL report.",
    ),
    updated_entries: Path = typer.Option(
        Path("out/updated_entries.json"),
        "--updated-entries",
        help="Output path for full bio.tools entries JSON payload.",
    ),
    model: str | None = typer.Option(
        None, "--model", help="Ollama model name (default from config)."
    ),
    concurrency: int = typer.Option(
        8, "--concurrency", help="Max concurrent jobs (default from config)."
    ),
    quiet: bool = typer.Option(
        False, "--quiet", help="Suppress info output; only show errors."
    ),
    verbose: bool = typer.Option(False, "--verbose", help="Show extra debug output."),
    # Advanced features
    p2t_out: str | None = typer.Option(
        None, "--p2t-out", help="Path to Pub2Tools output JSON."
    ),
    input_path: str | None = typer.Option(
        None, "--input", help="Preferred input path (overrides Pub2Tools fetch)."
    ),
    offline: bool = typer.Option(
        False,
        "--offline",
        help="Disable web/repo fetching; mark uncertain candidates.",
    ),
    p2t_cli: str | None = typer.Option(
        None,
        "--p2t-cli",
        help="Path to Pub2Tools CLI executable (overrides auto-detection).",
    ),
    config_path: str | None = typer.Option(
        None,
        "--config",
        help="Path to config YAML file (default: config.yaml in project root).",
    ),
    ) -> None:
    """Run the annotation pipeline.

    Examples:
      biotools-annotate run --from-date 2023-01-01 --to-date 2023-01-31 --min-score 0.6 --output out/payload.json --report out/report.jsonl
      biotools-annotate run --input tests/fixtures/pub2tools/sample.json --dry-run --report out/report.jsonl
      biotools-annotate run --offline --quiet
      biotools-annotate run --help

    Exit codes:
      0: Success
      2: Payload schema validation failed
      3: Unhandled error

    """
    from .run import execute_run
    import sys
    from ..config import get_config_yaml

    # Load config first
    config = get_config_yaml()

    # Check required parameters

    # Use config defaults for optional parameters that weren't explicitly set
    # Note: CLI args take precedence over config values
    if since is not None:
        from_date = since
    if model is None:
        model = config.get("pipeline", {}).get("model")
    if output == Path("out/payload.json"):
        config_output = config.get("pipeline", {}).get("output")
        if config_output:
            output = Path(config_output)
    if report == Path("out/report.jsonl"):
        config_report = config.get("pipeline", {}).get("report")
        if config_report:
            report = Path(config_report)
    if updated_entries == Path("out/updated_entries.json"):
        config_updated = config.get("pipeline", {}).get("updated_entries")
        if config_updated:
            updated_entries = Path(config_updated)
    if concurrency == 8:
        config_concurrency = config.get("pipeline", {}).get("concurrency")
        if config_concurrency is not None:
            concurrency = config_concurrency
    if input_path is None:
        config_input = config.get("pipeline", {}).get("input_path")
        if config_input:
            input_path = config_input
    if input_path is None:
        config_to_biotools = config.get("pub2tools", {}).get("to_biotools_file")
        if config_to_biotools:
            input_path = config_to_biotools

    # Set logging level
    import logging

    if quiet:
        logging.basicConfig(level=logging.ERROR, stream=sys.stderr, force=True)
    elif verbose:
        logging.basicConfig(level=logging.DEBUG, stream=sys.stderr, force=True)
    else:
        logging.basicConfig(level=logging.INFO, stream=sys.stderr, force=True)

    # Use config defaults for pub2tools parameters that weren't explicitly set
    if edam_owl is None:
        edam_owl = config.get("pub2tools", {}).get("edam_owl")
    if idf is None:
        idf = config.get("pub2tools", {}).get("idf")
    if idf_stemmed is None:
        idf_stemmed = config.get("pub2tools", {}).get("idf_stemmed")
    if firefox_path is None:
        firefox_path = config.get("pub2tools", {}).get("firefox_path")
    if p2t_cli is None:
        p2t_cli = config.get("pub2tools", {}).get("p2t_cli")
    if from_date is None:
        from_date = config.get("pub2tools", {}).get("from_date")
    if to_date is None:
        to_date = config.get("pub2tools", {}).get("to_date")
    if to_date is None:
        to_date = config.get("pipeline", {}).get("to_date")

    try:
        execute_run(
            from_date=from_date,
            to_date=to_date,
            min_score=min_score,
            limit=limit,
            dry_run=dry_run,
            output=output,
            report=report,
            model=model,
            concurrency=concurrency,
            input_path=input_path,
            offline=offline,
            edam_owl=edam_owl,
            idf=idf,
            idf_stemmed=idf_stemmed,
            firefox_path=firefox_path,
            p2t_cli=p2t_cli,
            show_progress=not quiet,
            config_data=config,
            updated_entries=updated_entries,
        )
    except Exception as e:
        import traceback
        import typer

        typer.echo("\nERROR: Unhandled exception in pipeline:", err=True)
        typer.echo(str(e), err=True)
        typer.echo(traceback.format_exc(), err=True)
        sys.exit(3)


run = app.command("run")(_run_impl)


def main():
    app()
    return 0


if __name__ == "__main__":
    app()


if __name__ == "__main__":  # pragma: no cover
    app()


# For entry point
app
