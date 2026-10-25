"""Calendar URLs: fetching works, and the URL never shows up in any output."""

import http.server
import json
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from hellweek.cli import URL_ENV_VAR, main
from hellweek.make_demo import build_calendar
from hellweek.parse import CalendarSourceError, fetch_url, read_calendar

SECRET = "private-0123456789abcdefSECRET"
ICS_PATH = f"/calendar/ical/student%40example.edu/{SECRET}/basic.ics"
RANGE = ["--start", "2026-10-19", "--end", "2026-10-25"]


class CalendarHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == ICS_PATH:
            self.reply(200, "text/calendar", build_calendar().to_ical())
        elif self.path == "/login.html":
            self.reply(200, "text/html", b"<html>Sign in</html>")
        else:
            self.reply(404, "text/plain", b"not found")

    def reply(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture(scope="module")
def base_url() -> Iterator[str]:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), CalendarHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def run_cli(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int | str | None, str]:
    """Run the CLI, returning (exit code, everything it printed)."""
    try:
        code: int | str | None = main(argv)
    except SystemExit as exc:
        code = exc.code
    captured = capsys.readouterr()
    return code, captured.out + captured.err


@pytest.mark.parametrize(
    ("given", "fetched"),
    [
        ("webcal://p01-caldav.icloud.com/x.ics", "https://p01-caldav.icloud.com/x.ics"),
        ("WEBCALS://host/x.ics", "https://host/x.ics"),
        ("http://calendar.google.com/x.ics", "https://calendar.google.com/x.ics"),
        ("http://127.0.0.1:8000/x.ics", "http://127.0.0.1:8000/x.ics"),
        ("  https://host/x.ics\n", "https://host/x.ics"),
    ],
)
def test_fetch_url_uses_https(given: str, fetched: str) -> None:
    assert fetch_url(given) == fetched


def test_read_calendar_fetches_url(base_url: str) -> None:
    cal = read_calendar(base_url + ICS_PATH)
    assert len(cal.walk("VEVENT")) > 20


def test_analyze_from_url_never_prints_it(
    base_url: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "load.json"
    code, printed = run_cli(["analyze", base_url + ICS_PATH, *RANGE, "--out", str(out)], capsys)
    assert code == 0
    assert SECRET not in printed
    assert SECRET not in out.read_text(encoding="utf-8")
    assert len(json.loads(out.read_text(encoding="utf-8"))["days"]) == 7


def test_url_from_env_var(
    base_url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(URL_ENV_VAR, base_url + ICS_PATH)
    code, printed = run_cli(["events", *RANGE], capsys)
    assert code == 0
    assert "CHEM 210 Midterm 1" in printed
    assert SECRET not in printed


@pytest.mark.parametrize(
    "bad_source",
    [
        "{base}/calendar/ical/student%40example.edu/wrong-SECRET-path/basic.ics",  # 404
        "{base}/login.html",  # HTML, not iCal
        "https://calendar.google.com:notaport/calendar/ical/x/{secret}/basic.ics",  # bad URL
        "https://no-such-host.invalid/calendar/ical/x/{secret}/basic.ics",  # DNS failure
        "calendar.google.com/calendar/ical/x/{secret}/basic.ics",  # no scheme
        "https:/calendar.google.com/calendar/ical/x/{secret}/basic.ics",  # mangled scheme
    ],
)
def test_failures_never_print_the_url(
    bad_source: str, base_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    source = bad_source.format(base=base_url, secret=SECRET)
    code, printed = run_cli(["analyze", source, *RANGE], capsys)
    assert code == 2
    assert "SECRET" not in printed
    assert "student" not in printed
    assert "error:" in printed


def test_fetch_errors_hide_the_url_from_tracebacks(base_url: str) -> None:
    with pytest.raises(CalendarSourceError) as exc:
        read_calendar(f"{base_url}/calendar/ical/x/{SECRET}/nope.ics")
    assert "HTTP 404" in str(exc.value)
    assert exc.value.__suppress_context__
    assert SECRET not in str(exc.value)


def test_no_calendar_and_no_env_var_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv(URL_ENV_VAR, raising=False)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    code, printed = run_cli(["analyze", *RANGE], capsys)
    assert code == 2
    assert URL_ENV_VAR in printed
