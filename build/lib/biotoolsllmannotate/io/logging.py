from __future__ import annotations

import logging
import sys
from typing import Optional

from rich.console import Console
from rich.logging import RichHandler

DEFAULT_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def setup_logging(
    level: int = logging.INFO,
    fmt: str = DEFAULT_FORMAT,
    *,
    console: Optional[Console] = None,
) -> None:
    """Set up structured logging for the CLI pipeline."""

    basic_kwargs: dict[str, object] = {"level": level, "force": True}

    if console is not None:
        handler = RichHandler(
            console=console,
            show_path=False,
            markup=True,
            rich_tracebacks=True,
            log_time_format="%H:%M:%S",
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        basic_kwargs["handlers"] = [handler]
        basic_kwargs["format"] = "%(message)s"
    else:
        basic_kwargs["format"] = fmt
        basic_kwargs["stream"] = sys.stderr

    logging.basicConfig(**basic_kwargs)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
