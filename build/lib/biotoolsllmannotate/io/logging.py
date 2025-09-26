import logging
import sys

DEFAULT_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def setup_logging(level=logging.INFO, fmt=DEFAULT_FORMAT):
    """Set up structured logging for the CLI pipeline.
    """
    logging.basicConfig(
        level=level,
        format=fmt,
        stream=sys.stdout,
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
