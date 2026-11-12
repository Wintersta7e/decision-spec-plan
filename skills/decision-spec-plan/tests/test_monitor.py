# SPDX-License-Identifier: MIT
"""The route monitor: `dsp_monitor.py`, its page skeleton and the names it shares."""

import base64
import contextlib
import hashlib
import ipaddress
import json
import re
import shlex
import socket
import time
from http import HTTPStatus
from typing import cast

import dsp_monitor
import support
from dsp_route import common
from support import PY, SCRIPTS, free_ports

PAGE = SCRIPTS / "dsp_monitor.html"
# the paths the monitor serves; `/api/run` answers 404 for a key it does not list
PATHS = ("/", "/api/state", "/api/run?key=x", "/api/ping")
EXIT_PAGE = 2  # the monitor's exit code for a missing or malformed page
NONCE_HEX = 16  # secrets.token_hex(8)


def refused(host: str, port: int) -> bool:
    """A TCP connect to (host, port) is refused, not accepted or left unanswered."""
    try:
        with socket.create_connection((host, port), 0.5):
            return False
    except ConnectionRefusedError:
        return True
    except OSError:
        return False


def parses(body: bytes) -> bool:
    """Body is JSON."""
    try:
        _ = cast("object", json.loads(body))
    except ValueError:
        return False
    return True


def csp_hash(page: str, tag: str) -> str:
    """The CSP source of page's one tag element: `'sha256-<base64>'` of its text."""
    m = re.search(rf"<{tag}>(.*?)</{tag}>", page, re.DOTALL)
    text = m.group(1) if m else ""
    digest = hashlib.sha256(text.encode()).digest()
    return f"'sha256-{base64.b64encode(digest).decode()}'"


class SharedNames(support.Sandbox):
    """The route slug and the agent-id name, owned by `common` for every reader."""

    def test_route_slug_and_id_name(self) -> None:
        """The slug is the marker's; the name drops the `a` and the hash suffix."""
        want = hashlib.sha1(b"/x/plan", usedforsecurity=False).hexdigest()[:10]
        self.ok("route slug", common.route_slug("/x/plan") == want)
        cases = {
            "aexec-p1-04-1-0123abcd": "exec-p1-04-1",
            "ab_c-12345678": "b_c",
            "lead": "lead",
        }
        for agent, name in cases.items():
            self.ok(f"id_name({agent})", common.id_name(agent) == name)


class StartUp(support.MonitorSandbox):
    """What the monitor checks before it binds a port, and that it starts anywhere."""

    def test_page_required_at_start(self) -> None:
        """No page, a directory, or two scripts: exit 2, one line, no port bound."""
        two = self.write(self.T / "two.html", PAGE.read_text() + "<script></script>\n")
        cases = {
            "missing": self.T / "no-such.html",
            "directory": self.T,
            "two scripts": two,
        }
        for name, page in cases.items():
            port = free_ports(1)
            r = self.run_monitor(page=page, port=port)
            lines = r.stderr.splitlines()
            self.ok(f"{name}: exit 2", r.returncode == EXIT_PAGE, r.stderr)
            self.ok(f"{name}: one stderr line", len(lines) == 1, r.stderr)
            self.ok(f"{name}: no URL", r.stdout == "", r.stdout)
            self.ok(f"{name}: port {port} never bound", refused("127.0.0.1", port))
        self.ok(f"{len(cases)} page cases", cases)

    def test_starts_without_os_nice(self) -> None:
        """Where os.nice is missing (Windows), it still starts and answers its ping."""
        m = self.start_monitor(delete_nice=True)
        code, _, body = m.get("/api/ping")
        ping = cast("dict[str, object]", json.loads(body))
        self.ok("ping answers 200", code == HTTPStatus.OK, code)
        self.ok("ping says dsp", ping.get("monitor") == "dsp", ping)
        self.ok("ping version 1", ping.get("version") == 1, ping)
        self.ok("ping pid is the process", ping.get("pid") == m.proc.pid, ping)
        nonce = str(ping.get("nonce"))
        self.ok("ping nonce", re.fullmatch(f"[0-9a-f]{{{NONCE_HEX}}}", nonce), ping)

    def test_owner_checks(self) -> None:
        """A constant that disagrees with its owner module stops every launch."""
        # the hook path's modules are imported lazily everywhere (TID253)
        from dsp_route import record

        cases: dict[str, object] = {
            "STUCK_S": record.HEARTBEAT_S,
            "ATTENTION_FLAGS": ["no-such-kind"],
        }
        for name, value in cases.items():
            r = self.run_monitor(consts={name: value})
            self.ok(f"{name}: non-zero exit", r.returncode != 0, r.stderr[-2000:])
            self.ok(f"{name}: named on stderr", name in r.stderr, r.stderr[-2000:])
            self.ok(f"{name}: no URL", r.stdout == "", r.stdout)


class Listener(support.MonitorSandbox):
    """Where it listens, whom it answers and the headers of every answer."""

    def test_loopback_bind_only(self) -> None:
        """It answers on 127.0.0.1 only: not 127.0.0.2, not any host address."""
        m = self.start_monitor()
        code, _, _ = m.get("/api/ping")
        self.ok("ping answers on 127.0.0.1", code == HTTPStatus.OK, code)
        # a 0.0.0.0 bind would accept this one; the loopback routes all of 127/8
        self.ok("127.0.0.2 refused", refused("127.0.0.2", m.port))
        found: set[str] = set()
        with contextlib.suppress(OSError):
            for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                found.add(str(info[4][0]))
        # the source address of the default route; a UDP connect sends nothing
        with (
            contextlib.suppress(OSError),
            socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp,
        ):
            udp.connect(("192.0.2.1", 9))
            found.add(str(cast("tuple[str, int]", udp.getsockname())[0]))
        addrs = sorted(a for a in found if not ipaddress.ip_address(a).is_loopback)
        if not addrs:
            self.skipTest("no non-loopback IPv4 address")
        for addr in addrs:
            self.ok(f"{addr}:{m.port} refused", refused(addr, m.port))
        self.ok(f"tried {len(addrs)} addresses", addrs)

    def bad_hosts(self, port: int) -> dict[str, list[str]]:
        """The Host header sets the monitor on port must refuse, by label."""
        return {
            f"evil.test:{port}": [f"evil.test:{port}"],
            f"127.0.0.1:{port + 1}": [f"127.0.0.1:{port + 1}"],
            f"localhost.evil.test:{port}": [f"localhost.evil.test:{port}"],
            "no Host": [],
            "two Hosts": [f"127.0.0.1:{port}", f"127.0.0.1:{port}"],
        }

    def test_host_check(self) -> None:
        """Only Host 127.0.0.1:<port> or localhost:<port> is answered; else 421."""
        m = self.start_monitor()
        p = m.port
        n = 0
        for path in PATHS:
            for label, hosts in self.bad_hosts(p).items():
                code, _, body = m.get(path, hosts)
                self.ok(
                    f"{path} {label}: 421, empty",
                    code == HTTPStatus.MISDIRECTED_REQUEST and body == b"",
                    f"{code} {body[:200]!r}",
                )
                n += 1
            want = HTTPStatus.NOT_FOUND if "key=" in path else HTTPStatus.OK
            for host in (f"127.0.0.1:{p}", f"localhost:{p}"):
                code, _, _ = m.get(path, host)
                self.ok(f"{path} {host}: {want.value}", code == want, code)
                n += 1
        self.ok(f"{n} requests", n)

    def test_response_headers(self) -> None:
        """Every answer is no-store and nosniff, with no CORS header; POST gets 501."""
        m = self.start_monitor()
        p = m.port
        got: dict[str, tuple[int, dict[str, str], bytes]] = {}
        for path in PATHS:
            for label, hosts in self.bad_hosts(p).items():
                got[f"{path} {label}"] = m.get(path, hosts)
            for host in (f"127.0.0.1:{p}", f"localhost:{p}"):
                got[f"{path} {host}"] = m.get(path, host)
        got["POST /api/state"] = m.get("/api/state", method="POST")
        got["GET /nope"] = m.get("/nope")
        for label, (_, headers, _) in got.items():
            self.ok(f"{label}: no-store", headers.get("cache-control") == "no-store")
            self.ok(
                f"{label}: nosniff", headers.get("x-content-type-options") == "nosniff"
            )
            cors = [h for h in headers if h.startswith("access-control-")]
            self.ok(f"{label}: no CORS header", not cors, cors)
        self.ok(f"{len(got)} responses", got)
        code, _, body = got["POST /api/state"]
        self.ok("POST: 501", code == HTTPStatus.NOT_IMPLEMENTED, code)
        self.ok("POST: no JSON body", not parses(body), body[:200])
        code, headers, _ = got["GET /nope"]
        self.ok("/nope: 404", code == HTTPStatus.NOT_FOUND, code)
        self.ok("/nope: empty", headers.get("content-length") == "0", headers)
        code, headers, body = got[f"/ 127.0.0.1:{p}"]
        self.ok("/: the page bytes", body == PAGE.read_bytes())
        self.ok(
            "/: html",
            headers.get("content-type") == "text/html; charset=utf-8",
            headers,
        )
        csp = headers.get("content-security-policy", "")
        page = body.decode()
        for directive in (
            f"script-src {csp_hash(page, 'script')}",
            f"style-src {csp_hash(page, 'style')}",
            "default-src 'none'",
            "connect-src 'self'",
        ):
            self.ok(f"/: CSP {directive}", directive in csp, csp)
        for label in (f"/api/ping 127.0.0.1:{p}", f"/api/state 127.0.0.1:{p}"):
            ctype = got[label][1].get("content-type")
            self.ok(f"{label}: JSON", ctype == "application/json; charset=utf-8")


class SingleInstance(support.MonitorSandbox):
    """The port is the lock: a running monitor is found by its ping, not a file."""

    def test_second_launch(self) -> None:
        """A second launch on the port prints the first's URL and exits 0, fast."""
        p = free_ports(dsp_monitor.PORT_SPAN)
        first = self.start_monitor(port=p)
        t0 = time.monotonic()
        r = self.run_monitor(port=p)
        took = time.monotonic() - t0
        limit = dsp_monitor.PING_TIMEOUT_S + 1
        self.ok("the first serves on P", first.port == p, first.url)
        want = f"http://localhost:{p}/\n"
        self.ok("the second prints P's URL", r.stdout == want, r.stdout + r.stderr)
        self.ok("the second exits 0", r.returncode == 0, r.stderr)
        self.ok(f"the second took {took:.2f} s, under {limit} s", took < limit)
        self.ok("P+1 never bound", refused("127.0.0.1", p + 1))

    def test_port_scan(self) -> None:
        """A taken port is passed over; all of P to P+9 taken exits 1, naming them."""
        span = dsp_monitor.PORT_SPAN
        p = free_ports(span)
        fast = {"PING_TIMEOUT_S": 0.3}  # a plain listener never answers the ping
        with socket.socket() as s:
            s.bind(("127.0.0.1", p))
            s.listen()
            m = self.start_monitor(port=p, consts=fast)
            self.ok("a plain listener on P: serves on P+1", m.port == p + 1, m.url)
            self.ok("it stops with exit 0", m.stop() == 0, m.err)
        with contextlib.ExitStack() as stack:
            for port in range(p, p + span):
                s = stack.enter_context(socket.socket())
                s.bind(("127.0.0.1", port))
                s.listen()
            r = self.run_monitor(port=p, consts=fast)
        lines = r.stderr.splitlines()
        self.ok("all taken: exit 1", r.returncode == 1, r.stderr)
        self.ok("all taken: one stderr line", len(lines) == 1, r.stderr)
        named = bool(lines) and str(p) in lines[0] and str(p + span - 1) in lines[0]
        self.ok(f"all taken: the line names {p} and {p + span - 1}", named, r.stderr)
        self.ok("all taken: no URL", r.stdout == "", r.stdout)
        r = self.run_monitor(port=65536 - span + 1)
        self.ok("a range past 65535: exit 2", r.returncode == EXIT_PAGE, r.stderr)

    def test_windows_side_collision(self) -> None:
        """Windows' curl.exe reaching another process moves it on; no answer keeps P."""
        p = free_ports(dsp_monitor.PORT_SPAN)
        fetch = (
            f"{shlex.quote(PY)} -c 'import sys,urllib.request;"
            "print(urllib.request.urlopen(sys.argv[1]).read().decode())'"
        )
        foreign = (
            f'case "$url" in *:{p}/*) echo \'{{"monitor":"other"}}\' ;; '
            f'*) exec {fetch} "$url" ;; esac'
        )
        logs: dict[str, list[str]] = {}
        monitors: dict[str, support.Monitor] = {}
        for case, body in (("foreign", foreign), ("none", "exit 7")):
            stub_dir = self.T / f"curl-{case}"
            log = self.T / f"curl-{case}.log"
            script = f'#!/bin/sh\nfor url; do :; done\necho "$url" >> {log}\n{body}\n'
            self.chmod_x(self.write(stub_dir / "curl.exe", script))
            m = self.start_monitor(port=p, path_prefix=[stub_dir])
            self.ok(f"{case}: stops with exit 0", m.stop() == 0, m.err)
            monitors[case] = m
            logs[case] = log.read_text().splitlines() if log.exists() else []
        m, log = monitors["foreign"], logs["foreign"]
        self.ok("foreign: serves on P+1", m.port == p + 1, m.url)
        want = [f"http://localhost:{port}/api/ping" for port in (p, p + 1)]
        self.ok("foreign: curl.exe asked P, then P+1", log == want, log)
        self.ok("foreign: stderr empty", m.err == "", m.err)
        m, log = monitors["none"], logs["none"]
        self.ok("none: keeps P", m.port == p, m.url)
        self.ok("none: curl.exe asked P once", log == want[:1], log)
        self.ok("none: one stderr line", len(m.err.splitlines()) == 1, m.err)
