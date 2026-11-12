# SPDX-License-Identifier: MIT
"""Show every dsp route on this machine, live, in one browser page.

dsp_monitor.py serves a page and a JSON API on 127.0.0.1 and prints the page's URL. It
finds the routes the registry under ~/.claude/dsp-routes names, reads their planning
dirs and repositories, and reads the agent events the recording switch writes (see
INSTALL.md). It starts only by hand; Ctrl-C stops it.

Options:
  --port N  listen on the first free port of N to N+9 (default 47961). A port of the
            range that a dsp monitor holds already is the answer: its URL is
            printed and this launch exits. On WSL, a port where Windows' curl.exe
            reaches another process is passed over. 0 binds one ephemeral port,
            with no scan and no check.
  --open    also open the page in a browser tab, on every launch.

It writes nothing anywhere: no lock, PID, cache or log file. It listens on 127.0.0.1
only, and answers only a request whose Host is 127.0.0.1:<port> or localhost:<port>.
No authentication: every local process that can reach the loopback can read it.

Exit codes: 0 stopped by Ctrl-C or SIGTERM, or a dsp monitor already serves; 1 no
port of the range can be served; 2 a bad argument, or its page (dsp_monitor.html
beside it) is missing or malformed.
"""

import argparse
import base64
import contextlib
import datetime as dt
import errno
import hashlib
import http.client
import http.server
import json
import os
import pathlib
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
import types
import urllib.parse
import webbrowser
from collections.abc import Callable
from typing import TYPE_CHECKING, Literal, NamedTuple, TypeVar

from dsp_route import common

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


def ping(port: int) -> bool:
    """Ask the listener on port for `/api/ping`: is it a dsp monitor?

    Args:
        port: A port on 127.0.0.1 that another process holds.

    Returns:
        True when it answered within PING_TIMEOUT_S with `monitor == "dsp"`.
    """
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=PING_TIMEOUT_S)
    try:
        conn.request("GET", "/api/ping")
        body = conn.getresponse().read()
        answer = common.as_dict(common.parse_json(body)) or {}
    except (OSError, http.client.HTTPException, ValueError):
        return False
    finally:
        conn.close()
    return answer.get("monitor") == "dsp"


def self_check(port: int, nonce: str) -> Literal["ours", "foreign", "none"]:
    """Ask the port through Windows' curl.exe, where WSL interop has one.

    On WSL2, a Windows process listening on the port gets Windows' requests to
    localhost while the bind here still succeeds.

    Args:
        port: The port this process serves.
        nonce: This process's ping nonce.

    Returns:
        ours: the answer is this process's, or there is no curl.exe to ask; foreign:
        another process answered; none: no answer.
    """
    curl = shutil.which("curl.exe")
    if curl is None:
        return "ours"
    url = f"http://localhost:{port}/api/ping"
    try:
        r = subprocess.run(
            [curl, "-s", "-m", str(PING_TIMEOUT_S), url],
            capture_output=True,
            text=True,
            timeout=PING_TIMEOUT_S + 1,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "none"
    if r.returncode != 0 or not r.stdout.strip():
        return "none"
    try:
        answer = common.as_dict(common.parse_json(r.stdout)) or {}
    except ValueError:
        return "foreign"
    return "ours" if answer.get("nonce") == nonce else "foreign"


def bind_scan(port: int, live: Live) -> Server | str | None:
    """Serve on the first port of port's range that no other process answers on.

    Args:
        port: The first port of the range; 0 binds one ephemeral port, with no scan,
            no ping and no self-check.
        live: The answers to serve; told the bound port.

    Returns:
        The serving server; or the URL of a dsp monitor that holds a port of the
        range; or None, after one stderr line, when no port could be served.
    """
    last = port + PORT_SPAN - 1
    for p in [port] if port == 0 else range(port, last + 1):
        try:
            server = Server(("127.0.0.1", p), handler(live))
        except OSError as e:
            if port != 0 and e.errno == errno.EADDRINUSE:
                if ping(p):
                    return f"http://localhost:{p}/"
                continue
            where = "an ephemeral port" if port == 0 else f"{p} in {port}–{last}"
            print(f"dsp_monitor: cannot bind {where}: {e.strerror}", file=sys.stderr)
            return None
        live.bound(server.server_address[1])
        threading.Thread(target=server.serve_forever, daemon=True).start()
        verdict = "ours" if port == 0 else self_check(live.port, live.nonce)
        if verdict == "foreign":
            server.shutdown()
            server.server_close()
            continue
        if verdict == "none":
            print(
                f"dsp_monitor: curl.exe got no answer from localhost:{live.port}; "
                "the page may not open from Windows",
                file=sys.stderr,
            )
        return server
    print(f"dsp_monitor: ports {port}–{last} are all taken", file=sys.stderr)
    return None


def _interrupt(_signum: int, _frame: types.FrameType | None) -> None:
    """Turn SIGTERM (and SIGINT, even when ignored at launch) into a Ctrl-C."""
    raise KeyboardInterrupt


class _Args(argparse.Namespace):
    """The command line."""

    port: int = PORT
    open_tab: bool = False


def _port(text: str) -> int:
    """Return a --port value whose whole range fits under 65536."""
    n = int(text)
    top = 65536 - PORT_SPAN
    if not 0 <= n <= top:
        msg = f"{n} is not in 0 to {top}"
        raise argparse.ArgumentTypeError(msg)
    return n


def _args(argv: list[str] | None) -> _Args:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    _ = ap.add_argument("--port", type=_port, default=PORT)
    _ = ap.add_argument("--open", action="store_true", dest="open_tab")
    return ap.parse_args(argv, namespace=_Args())


def _show(url: str, *, open_tab: bool) -> None:
    """Print url, and open it in a browser tab with --open."""
    print(url, flush=True)
    if open_tab and not webbrowser.open(url):
        print(f"dsp_monitor: no browser opened {url}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    """Serve the monitor until Ctrl-C or SIGTERM.

    Args:
        argv: The arguments; None reads sys.argv.

    Returns:
        The exit code the module docstring lists.
    """
    check_owners()
    args = _args(argv)
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
    found = bind_scan(args.port, live)
    if found is None:
        return 1
    if isinstance(found, str):
        _show(found, open_tab=args.open_tab)
        return 0
    try:
        _show(f"http://localhost:{live.port}/", open_tab=args.open_tab)
        with contextlib.suppress(KeyboardInterrupt):
            while True:
                time.sleep(3600)
    finally:
        found.shutdown()
        found.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
