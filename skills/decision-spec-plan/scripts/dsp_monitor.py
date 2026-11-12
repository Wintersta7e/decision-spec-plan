# SPDX-License-Identifier: MIT
"""Show every dsp route on this machine, live, in one browser page.

dsp_monitor.py serves a page and a JSON API on 127.0.0.1 and prints the page's URL. It
finds the routes the registry under ~/.claude/dsp-routes names, reads their planning
dirs and repositories, and reads the agent events the recording switch writes (see
INSTALL.md). It starts only by hand; Ctrl-C stops it.

Options:
  --port N  listen on N (default 47961); a port that holds a dsp monitor already is
            taken as the answer: its URL is printed and this launch exits. 0 binds
            one ephemeral port.
  --open    also open the page in a browser tab, on every launch.

It writes nothing anywhere: no lock, PID, cache or log file. It listens on 127.0.0.1
only, and answers only a request whose Host is 127.0.0.1:<port> or localhost:<port>.
No authentication: every local process that can reach the loopback can read it.

Exit codes: 0 stopped by Ctrl-C or SIGTERM, or a dsp monitor already serves; 1 the
port cannot be bound; 2 a bad argument, or its page (dsp_monitor.html beside it) is
missing or malformed.
"""

import argparse
import base64
import contextlib
import datetime as dt
import hashlib
import http.server
import json
import os
import pathlib
import re
import secrets
import signal
import sys
import threading
import time
import types
import urllib.parse
import webbrowser
from collections.abc import Callable
from typing import TYPE_CHECKING, NamedTuple, TypeVar

if TYPE_CHECKING:
    from typing_extensions import override
else:
    _F = TypeVar("_F", bound=Callable[..., object])

    def override(method: _F) -> _F:
        """Return method unchanged: `typing.override`, which Python 3.11 lacks."""
        return method


API_VERSION = 1
PORT = 47961
PORT_SPAN = 10
PING_TIMEOUT_S = 2
IDLE_S = 7200
STUCK_S = 720
NICE = 10
WORKERS = 2
SCAN_S = 2
FREE_TTL_S = 15
FREE_IDLE_S = 600
GIT_TTL_S = 120
GIT_FLOOR_S = 30
GIT_IDLE_S = 1800
DEADLINE_S = 20
DEADLINE_MAX_S = 120
PAGE = pathlib.Path(__file__).with_name("dsp_monitor.html")

RUN_STATES = ("live", "ended")
ROUTE_STATUS = ("active", "idle")
RECORDING = ("seen", "none", "reduced", "expired")
ATTENTION = (
    "asked",
    "input",
    "blind",
    "dir-missing",
    "stuck",
    "reduced",
    "git-slow",
    "unreadable",
    "flag",
)
GIT_STATES = ("pending", "fresh", "slow", "not_tracked")
BOARD_COLUMNS = ("queued", "running", "ready", "merged", "blocked", "failed")
ATTENTION_FLAGS = (
    "gate-red",
    "base-drift",
    "main-missing",
    "lane-moved-past-merge",
    "sha-unknown",
    "manifest-invalid",
)
WAIT_NOTIFY = ("permission_prompt", "elicitation_dialog", "idle_prompt")

# each report lane state: its board column and whether it is gating; a queued lane
# whose dependencies are not all merged shows as blocked instead
BOARD = {
    "queued": ("queued", False),
    "running": ("running", False),
    "gating": ("running", True),
    "ready": ("ready", False),
    "red": ("failed", False),
    "merged": ("merged", False),
}


def check_owners() -> None:
    """Stop the launch when a constant here disagrees with the module that owns it.

    Raises:
        RuntimeError: Named after the constant that disagrees.
    """
    # the hook path imports these lazily too; a module-level import would slow it
    from dsp_route import record, report

    if set(BOARD) != set(report.LANE_STATES):
        msg = f"BOARD: maps {sorted(BOARD)}, report.LANE_STATES is {report.LANE_STATES}"
        raise RuntimeError(msg)
    if STUCK_S <= record.HEARTBEAT_S:
        beat = record.HEARTBEAT_S
        msg = f"STUCK_S: {STUCK_S} s is not above record.HEARTBEAT_S ({beat} s)"
        raise RuntimeError(msg)
    unknown = sorted(set(ATTENTION_FLAGS) - set(report.FLAG_KINDS))
    if unknown:
        msg = f"ATTENTION_FLAGS: {unknown} not in report.FLAG_KINDS"
        raise RuntimeError(msg)


class Page(NamedTuple):
    """The page as served: its bytes, its CSP and the id the API reports."""

    body: bytes
    csp: str
    digest: str


def read_page(path: pathlib.Path) -> Page:
    """Read the page and build the CSP from its one script and one style.

    Args:
        path: The page file.

    Returns:
        The page, its Content-Security-Policy and the first 12 hex of its sha256.

    Raises:
        ValueError: Why the page cannot be served.
    """
    try:
        body = path.read_bytes()
    except OSError as e:
        msg = e.strerror or type(e).__name__
        raise ValueError(msg) from e
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as e:
        msg = "not UTF-8"
        raise ValueError(msg) from e
    # a browser hashes the text after the HTML parser turned CR LF and CR into LF
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    hashes: dict[str, str] = {}
    for tag in ("script", "style"):
        n = len(re.findall(rf"<{tag}\b", text, re.IGNORECASE))
        m = re.search(
            rf"<{tag}\b[^>]*>(.*?)</{tag}\s*>", text, re.IGNORECASE | re.DOTALL
        )
        if n != 1 or m is None:
            msg = f"wants exactly one closed <{tag}> element, has {n} <{tag} tags"
            raise ValueError(msg)
        digest = hashlib.sha256(m.group(1).encode()).digest()
        hashes[tag] = base64.b64encode(digest).decode()
    csp = (
        f"default-src 'none'; script-src 'sha256-{hashes['script']}'; "
        f"style-src 'sha256-{hashes['style']}'; connect-src 'self'; img-src data:; "
        "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    )
    return Page(body, csp, hashlib.sha256(body).hexdigest()[:12])


def now_iso() -> str:
    """Return the current UTC time as ISO 8601 with `Z`."""
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def as_json(obj: object) -> bytes:
    """Return obj as compact UTF-8 JSON."""
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode()


class Live:
    """What the request handlers serve: bytes built once, read by every thread."""

    def __init__(self, page: Page, nonce: str) -> None:
        """Hold the page and this process's nonce; nothing is bound yet.

        Args:
            page: The page read at start-up.
            nonce: This process's ping nonce.
        """
        self.page: Page = page
        self.nonce: str = nonce
        self.pid: int = os.getpid()
        self.port: int = 0
        self.ping: bytes = b""
        self.state: bytes = b""

    def bound(self, port: int) -> None:
        """Take the port a server bound and build the answers that name it.

        Args:
            port: The bound port.
        """
        self.port = port
        self.ping = as_json(
            {
                "monitor": "dsp",
                "version": API_VERSION,
                "pid": self.pid,
                "nonce": self.nonce,
            }
        )
        self.state = as_json(
            {
                "version": API_VERSION,
                "page": self.page.digest,
                "generated_at": now_iso(),
                "ready": False,
                "monitor": {"pid": self.pid, "port": port},
                "waiting": [],
                "attention": [],
                "routes": [],
                "idle": [],
                "ended": [],
                "counts": {"waiting": 0, "idle": 0, "ended": 0},
                "errors": [],
                "events_unjoined": 0,
            }
        )


JSON = "application/json; charset=utf-8"


def handler(live: Live) -> type[http.server.BaseHTTPRequestHandler]:
    """Return the request handler class that serves live.

    Args:
        live: The answers to serve.

    Returns:
        A handler for GET only; any other method gets http.server's 501.
    """

    class Handler(http.server.BaseHTTPRequestHandler):
        """One request: the Host check first, then the page or an API answer."""

        @override
        def log_message(self, *_args: object, **_kwargs: object) -> None:
            """Log nothing: a page polling every 5 s would write a line each time."""

        @override
        def end_headers(self) -> None:
            """Add the headers every response carries, errors included."""
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            super().end_headers()

        def reply(
            self, code: int, body: bytes = b"", headers: dict[str, str] | None = None
        ) -> None:
            """Send code, headers and body."""
            self.send_response(code)
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            _ = self.wfile.write(body)

        def do_GET(self) -> None:
            """Answer a GET whose Host names this listener; else 421, empty."""
            hosts = self.headers.get_all("Host") or []
            mine = (f"127.0.0.1:{live.port}", f"localhost:{live.port}")
            if len(hosts) != 1 or hosts[0] not in mine:
                self.reply(421)
                return
            path = urllib.parse.urlsplit(self.path).path
            if path == "/":
                self.reply(
                    200,
                    live.page.body,
                    {
                        "Content-Type": "text/html; charset=utf-8",
                        "Content-Security-Policy": live.page.csp,
                    },
                )
            elif path == "/api/ping":
                self.reply(200, live.ping, {"Content-Type": JSON})
            elif path == "/api/state":
                self.reply(200, live.state, {"Content-Type": JSON})
            else:
                self.reply(404)

    return Handler


class Server(http.server.ThreadingHTTPServer):
    """The listener: one thread per request, none outliving the process."""

    daemon_threads: bool = True
    # Windows' SO_REUSEADDR admits a second listener on the port; Linux's does not
    allow_reuse_address: bool = os.name != "nt"


def _interrupt(_signum: int, _frame: types.FrameType | None) -> None:
    """Turn SIGTERM (and SIGINT, even when ignored at launch) into a Ctrl-C."""
    raise KeyboardInterrupt


class _Args(argparse.Namespace):
    """The command line."""

    port: int = PORT
    open_tab: bool = False


def _args(argv: list[str] | None) -> _Args:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    _ = ap.add_argument("--port", type=int, default=PORT)
    _ = ap.add_argument("--open", action="store_true", dest="open_tab")
    return ap.parse_args(argv, namespace=_Args())


def main(argv: list[str] | None = None) -> int:
    """Serve the monitor until Ctrl-C or SIGTERM.

    Args:
        argv: The arguments; None reads sys.argv.

    Returns:
        The exit code the module docstring lists.
    """
    check_owners()
    args = _args(argv)
    port = args.port
    try:
        page = read_page(PAGE)
    except ValueError as e:
        print(f"dsp_monitor: page {PAGE.name}: {e}", file=sys.stderr)
        return 2
    if hasattr(os, "nice"):
        _ = os.nice(NICE)
    live = Live(page, secrets.token_hex(8))
    for sig in (signal.SIGINT, signal.SIGTERM):
        _ = signal.signal(sig, _interrupt)
    server = Server(("127.0.0.1", port), handler(live))
    live.bound(server.server_address[1])
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://localhost:{live.port}/"
        print(url, flush=True)
        if args.open_tab and not webbrowser.open(url):
            print(f"dsp_monitor: no browser opened {url}", file=sys.stderr)
        with contextlib.suppress(KeyboardInterrupt):
            while True:
                time.sleep(3600)
    finally:
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
