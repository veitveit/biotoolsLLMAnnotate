from __future__ import annotations


def _fallback_main() -> None:
    """Argparse-based fallback when Typer is unavailable.

    Supports: `--help`, `--version`, and `run` subcommand with core options.
    """
    import argparse
    from pathlib import Path

    from . import __version__
    from .cli.run import execute_run

    parser = argparse.ArgumentParser(prog="biotoolsllmannotate")
    parser.add_argument("--version", action="store_true", help="Show version and exit")

    subparsers = parser.add_subparsers(dest="command")
    p_run = subparsers.add_parser("run", help="Fetch, assess, and emit outputs")

    p_run.add_argument("--from-date", default="7d")
    p_run.add_argument("--min-score", type=float, default=0.6)
    p_run.add_argument("--limit", type=int)
    p_run.add_argument("--dry-run", action="store_true")
    p_run.add_argument("--output", type=Path, default=Path("out/payload.json"))
    p_run.add_argument("--report", type=Path, default=Path("out/report.jsonl"))
    p_run.add_argument("--model", default="llama3.2")
    p_run.add_argument("--concurrency", type=int, default=8)

    args = parser.parse_args()
    if getattr(args, "version", False):
        print(__version__)
        return
    if args.command == "run":
        execute_run(
            from_date=args.from_date,
            min_score=args.min_score,
            limit=args.limit,
            dry_run=args.dry_run,
            output=args.output,
            report=args.report,
            model=args.model,
            concurrency=args.concurrency,
        )
        return
    # No subcommand: show help
    parser.print_help()


def main() -> None:
    try:
        import typer  # noqa: F401

        from .cli.main import app

        app()
    except ModuleNotFoundError as e:
        if e.name == "typer":
            _fallback_main()
        else:
            raise


if __name__ == "__main__":  # pragma: no cover
    main()
