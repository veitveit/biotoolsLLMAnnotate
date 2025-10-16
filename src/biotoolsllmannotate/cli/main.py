from __future__ import annotations

import typer
from pathlib import Path

from .. import __version__

app = typer.Typer(
    help="CLI to fetch Pub2Tools candidates, enrich, score, and emit bio.tools annotations with a live Rich scoreboard.\n\nExamples:\n  python -m biotoolsllmannotate --from-date 2024-01-01 --to-date 2024-01-31 --min-score 0.6\n  python -m biotoolsllmannotate --input tests/fixtures/pub2tools/sample.json --dry-run\n  python -m biotoolsllmannotate --write-default-config  # scaffold config.yaml with presets\n  python -m biotoolsllmannotate --offline --quiet\n\nTip: Use --resume-from-pub2tools (or set pipeline.resume_from_pub2tools: true) to reuse the latest Pub2Tools export without rerunning the CLI.",
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
    to_date: str | None = typer.Option(
        None,
        "--to-date",
        help="End date for Pub2Tools fetching (YYYY-MM-DD).",
    ),
    min_score: float | None = typer.Option(
        None,
        "--min-score",
        min=0.0,
        max=1.0,
        help="Legacy combined threshold applied to both bio and documentation scores when separate thresholds are not provided.",
    ),
    min_bio_score: float | None = typer.Option(
        None,
        "--min-bio-score",
        min=0.0,
        max=1.0,
        help="Minimum bio score required for inclusion (overrides pipeline.min_bio_score).",
    ),
    min_doc_score: float | None = typer.Option(
        None,
        "--min-doc-score",
        min=0.0,
        max=1.0,
        help="Minimum documentation score required for inclusion (overrides pipeline.min_documentation_score).",
    ),
    limit: int | None = typer.Option(
        None, "--limit", help="Max candidates to process."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Assess and report only; do not write payload."
    ),
    resume_from_pub2tools: bool = typer.Option(
        False,
        "--resume-from-pub2tools",
        help="Resume after the Pub2Tools export step by reusing the most recent cached to_biotools.json for the time-period folder.",
    ),
    resume_from_enriched: bool = typer.Option(
        False,
        "--resume-from-enriched",
        help="Resume pipeline starting from an enriched candidates cache.",
    ),
    resume_from_scoring: bool = typer.Option(
        False,
        "--resume-from-scoring",
        help="Resume pipeline after scoring by reusing the cached assessment report and enriched candidates.",
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
    registry_path: str | None = typer.Option(
        None,
        "--registry",
        help="Path to bio.tools registry JSON/CSV snapshot used for membership checks.",
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
        biotools-annotate run --from-date 2024-01-01 --to-date 2024-01-31 --min-score 0.6
        biotools-annotate run --input tests/fixtures/pub2tools/sample.json --dry-run
        biotools-annotate run --write-default-config
        biotools-annotate run --offline --quiet

    Exit codes:
      0: Success
      2: Payload schema validation failed
      3: Unhandled error

    """
    from .run import execute_run
    import sys
    from ..config import get_config_yaml, get_default_config_path

    # Load config first
    config_path_value = Path(config_path) if config_path else None
    config = get_config_yaml(str(config_path_value) if config_path_value else None)
    if config_path_value is not None:
        config_source_path = config_path_value
    else:
        config_source_path = Path(get_default_config_path())
    pub2tools_cfg = config.get("pub2tools", {}) or {}
    pipeline_cfg = config.get("pipeline", {}) or {}
    ollama_cfg = config.get("ollama", {}) or {}

    # Check required parameters

    # Use config defaults for optional parameters that weren't explicitly set
    # Note: CLI args take precedence over config values
    if from_date is None:
        from_date = pipeline_cfg.get("from_date")
    if to_date is None:
        to_date = pipeline_cfg.get("to_date")
    if model is None:
        model = ollama_cfg.get("model")
    if not resume_from_pub2tools:
        config_resume_pub2tools = pipeline_cfg.get("resume_from_pub2tools")
        if isinstance(config_resume_pub2tools, bool):
            resume_from_pub2tools = config_resume_pub2tools
        elif isinstance(config_resume_pub2tools, str):
            resume_from_pub2tools = config_resume_pub2tools.strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
    if not resume_from_enriched:
        config_resume = pipeline_cfg.get("resume_from_enriched")
        if isinstance(config_resume, bool):
            resume_from_enriched = config_resume
        elif isinstance(config_resume, str):
            resume_from_enriched = config_resume.strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
    if not resume_from_scoring:
        config_resume_scoring = pipeline_cfg.get("resume_from_scoring")
        if isinstance(config_resume_scoring, bool):
            resume_from_scoring = config_resume_scoring
        elif isinstance(config_resume_scoring, str):
            resume_from_scoring = config_resume_scoring.strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
    if concurrency == 8:
        config_concurrency = ollama_cfg.get("concurrency")
        if config_concurrency is not None:
            concurrency = config_concurrency
    if input_path is None:
        config_input = pipeline_cfg.get("input_path")
        if config_input:
            input_path = config_input
    if registry_path is None:
        config_registry = pipeline_cfg.get("registry_path")
        if config_registry:
            registry_path = config_registry

    if resume_from_pub2tools and input_path:
        raise typer.BadParameter(
            "cannot be used together with --input or pipeline.input_path",
            param_hint="--resume-from-pub2tools",
        )

    # Determine score thresholds (CLI > legacy min-score > config > default)
    def _coerce_threshold(value, default):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    config_min_bio = pipeline_cfg.get("min_bio_score")
    config_min_doc = pipeline_cfg.get("min_documentation_score")

    if min_score is not None:
        if min_bio_score is None:
            min_bio_score = min_score
        if min_doc_score is None:
            min_doc_score = min_score

    if min_bio_score is None:
        min_bio_score = _coerce_threshold(config_min_bio, 0.6)
    else:
        min_bio_score = _coerce_threshold(min_bio_score, 0.6)

    if min_doc_score is None:
        min_doc_score = _coerce_threshold(config_min_doc, 0.6)
    else:
        min_doc_score = _coerce_threshold(min_doc_score, 0.6)

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
        edam_owl = pub2tools_cfg.get("edam_owl")
    if idf is None:
        idf = pub2tools_cfg.get("idf")
    if idf_stemmed is None:
        idf_stemmed = pub2tools_cfg.get("idf_stemmed")
    if firefox_path is None:
        firefox_path = pub2tools_cfg.get("firefox_path")
    if p2t_cli is None:
        p2t_cli = pub2tools_cfg.get("p2t_cli")

    try:
        execute_run(
            from_date=from_date,
            to_date=to_date,
            min_bio_score=min_bio_score,
            min_doc_score=min_doc_score,
            limit=limit,
            dry_run=dry_run,
            model=model,
            concurrency=concurrency,
            input_path=input_path,
            registry_path=registry_path,
            offline=offline,
            edam_owl=edam_owl,
            idf=idf,
            idf_stemmed=idf_stemmed,
            firefox_path=firefox_path,
            p2t_cli=p2t_cli,
            show_progress=not quiet,
            config_data=config,
            resume_from_enriched=resume_from_enriched,
            resume_from_pub2tools=resume_from_pub2tools,
            resume_from_scoring=resume_from_scoring,
            config_file_path=config_source_path,
        )
    except Exception as e:
        import traceback

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
