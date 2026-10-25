"""Safe domain errors; provider response bodies and credentials never reach clients."""

from typing import Literal

CalendarErrorKind = Literal[
    "not_configured", "invalid_request", "unauthorized", "forbidden", "upstream", "timeout"
]


class CalendarError(Exception):
    def __init__(self, kind: CalendarErrorKind, message: str) -> None:
        super().__init__(message)
        self.kind = kind
