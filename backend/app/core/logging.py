"""Logging configuration. Keep structured logging setup here, not in modules."""

import logging
import sys


class OAuthQueryFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and len(record.args) == 5:
            path = record.args[2]
            if isinstance(path, str) and "/calendars/google/callback" in path:
                arguments = list(record.args)
                arguments[2] = path.split("?", 1)[0]
                record.args = tuple(arguments)
        return True


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s"))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Keep noisy third-party loggers quieter than our own.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, OAuthQueryFilter) for item in access.filters):
        access.addFilter(OAuthQueryFilter())
