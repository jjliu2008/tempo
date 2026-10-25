"""Logging configuration. Keep structured logging setup here, not in modules."""

import logging
import sys


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Keep noisy third-party loggers quieter than our own.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
