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

    p_run.add_argument("--from-date")
    p_run.add_argument("--to-date")
    p_run.add_argument("--min-score", type=float)
    p_run.add_argument(
        "--min-bio-score-add",
        "--min-bio-score",
        dest="min_bio_score_add",
        type=float,
    )
    p_run.add_argument("--min-bio-score-review", type=float)
    p_run.add_argument(
        "--min-doc-score-add",
        "--min-doc-score",
        dest="min_doc_score_add",
        type=float,
    )
    p_run.add_argument("--min-doc-score-review", type=float)
    p_run.add_argument("--limit", type=int)
    p_run.add_argument("--dry-run", action="store_true")
    p_run.add_argument("--model", default="llama3.2")
    p_run.add_argument("--concurrency", type=int, default=8)

    args = parser.parse_args()
    if getattr(args, "version", False):
        print(__version__)
        return
    if args.command == "run":
        from_date = args.from_date or "7d"
        bio_add = args.min_bio_score_add
        bio_review = args.min_bio_score_review
        doc_add = args.min_doc_score_add
        doc_review = args.min_doc_score_review

        if args.min_score is not None:
            if bio_add is None:
                bio_add = args.min_score
            if bio_review is None:
                bio_review = args.min_score
            if doc_add is None:
                doc_add = args.min_score
            if doc_review is None:
                doc_review = args.min_score

        bio_add = 0.6 if bio_add is None else max(0.0, min(bio_add, 1.0))
        doc_add = 0.6 if doc_add is None else max(0.0, min(doc_add, 1.0))
        bio_review = 0.5 if bio_review is None else max(0.0, min(bio_review, 1.0))
        doc_review = 0.5 if doc_review is None else max(0.0, min(doc_review, 1.0))

        if bio_review > bio_add:
            bio_review = bio_add
        if doc_review > doc_add:
            doc_review = doc_add
        execute_run(
            from_date=from_date,
            to_date=args.to_date,
            bio_thresholds=(bio_review, bio_add),
            doc_thresholds=(doc_review, doc_add),
            limit=args.limit,
            dry_run=args.dry_run,
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
