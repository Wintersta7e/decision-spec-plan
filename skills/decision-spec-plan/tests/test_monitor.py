# SPDX-License-Identifier: MIT
"""The route monitor: `dsp_monitor.py`, its page skeleton and the names it shares."""

import base64
import concurrent.futures
import contextlib
import dataclasses
import hashlib
import ipaddress
import json
import math
import os
import re
import shlex
import socket
import subprocess
import threading
import time
import unittest.mock
from collections.abc import Callable
from http import HTTPStatus
from pathlib import Path
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


FAST = {"SCAN_S": 0.05}  # the scan's floor, short so a change shows within a poll


def runs_of(state: dict[str, object], key: str) -> list[dict[str, object]]:
    """The runs /api/state lists for route key: its live run, then its ended ones."""
    out = [
        cast("dict[str, object]", r["run"])
        for group in ("routes", "idle")
        for r in cast("list[dict[str, object]]", state[group])
        if r["key"] == key
    ]
    for r in cast("list[dict[str, object]]", state["ended"]):
        if r["key"] == key:
            ended = cast("list[dict[str, object]]", r["runs"])
            out += [{**x, "state": "ended"} for x in ended]
    return out


def states_of(state: dict[str, object], key: str) -> list[tuple[str, str]]:
    """(run key, state) of each run /api/state lists for route key, sorted."""
    return sorted((str(r["key"]), str(r["state"])) for r in runs_of(state, key))


class Machine(support.MonitorSandbox):
    """The synthetic machine every monitor test builds on."""

    def test_builder_stays_synthetic(self) -> None:
        """Every path is under T; every name synthetic; no real HOME or mount."""
        m = self.build_machine()
        outside = [p for p in m.written if not p.is_relative_to(self.T)]
        self.ok(f"{len(m.written)} paths, all under T", m.written and not outside)
        sessions = {p.name.split(".")[0] for p in m.registry.rglob("*.json*")}
        names = set(m.routes)
        bad = [n for n in names if not re.fullmatch(r"route-[a-f]", n)]
        bad += [s for s in sessions if not re.fullmatch(r"s\d+", s)]
        self.ok(
            f"{len(names)} routes, {len(sessions)} sessions", names and not bad, bad
        )
        real = os.environ["HOME"]
        strings: list[str] = []

        def walk(v: object) -> None:
            if isinstance(v, str):
                strings.append(v)
            elif isinstance(v, dict):
                for k, x in cast("dict[str, object]", v).items():
                    walk(k)
                    walk(x)
            elif isinstance(v, list):
                for x in cast("list[object]", v):
                    walk(x)

        for p in m.written:
            if p.suffix in {".json", ".jsonl"}:
                for line in p.read_text().splitlines():
                    walk(cast("object", json.loads(line)))
        leaks = [s for s in strings if real in s or "/mnt/" in s]
        self.ok(f"{len(strings)} strings, none real", strings and not leaks, leaks)


class Discovery(support.MonitorSandbox):
    """Routes and runs from the registry, `previous` and the event logs (§4.3, §4.4)."""

    # this test's repository and planning dir, set by machine()
    repo: Path = Path()
    plan: Path = Path()

    def machine(self) -> support.Machine:
        """An empty machine of this test's own, with a repository and planning dir."""
        m = support.Machine(self.T / self._testMethodName)
        self.repo = self.init_repo(m.root / "repo")
        self.plan = self.repo / ".plan"
        self.plan.mkdir()
        return m

    def act(self, m: support.Machine, session: str, plan: Path | None = None) -> str:
        """`--activate` of plan (default the planning dir) by session on m; its run."""
        plan = plan or self.plan
        r = self.py(
            support.RS,
            plan,
            "--phase",
            "1",
            "--repo",
            self.repo,
            "--sections",
            "1-",
            "--activate",
            session=session,
            env=m.env,
            merge=True,
        )
        self.ok(f"{session} activates {plan.name}", r.code == 0, r.out)
        return str(self.marker(self.repo, plan).get("run"))

    def fixture(self, plan: Path, run: str) -> support.FixtureRoute:
        """The route on plan as the builder's line() needs it."""
        marker = self.MK(self.repo, plan)
        return support.FixtureRoute("route-a", self.repo, plan, marker, run, [])

    def test_reactivation_is_a_new_run(self) -> None:
        """A deleted marker re-activated is a new run; the old one ends with s1."""
        m = self.machine()
        old = self.act(m, "s1")
        r = self.fixture(self.plan, old)
        _ = m.put_events("s1", m.line(r, "s1", "turn-end", time.time() - 5))
        self.rm(r.marker)
        new = self.act(m, "s2")
        mon = self.monitor_on(m, consts=FAST)
        key, gone = r.key, r.run_key(old)
        s = mon.wait(lambda s: len(runs_of(s, key)) == len([old, new]))
        want = sorted([(r.run_key(new), "live"), (gone, "ended")])
        self.ok("a live and an ended run", states_of(s, key) == want, states_of(s, key))
        _, _, body = mon.get(f"/api/run?key={gone}")
        run = cast("dict[str, dict[str, object]]", json.loads(body))["run"]
        ids = [x["id"] for x in cast("list[dict[str, object]]", run["sessions"])]
        self.ok("the ended run has s1", ids == ["s1"], ids)

    def test_legacy_continuity(self) -> None:
        """A3 with R64: upgraded, moved legacy, pre buckets, the R64 marker check."""
        m = support.Machine(self.T / self._testMethodName)
        a = m.fixture_route("route-a", repo=False, upgraded=True)
        _ = m.put_entry("s1", a, legacy=True)
        b = m.fixture_route("route-b", repo=False, upgraded=True)
        moved = dataclasses.replace(b, marker=b.marker.with_name(common.MARKER))
        _ = m.put_entry("s2", moved, legacy=True)
        c = m.fixture_route("route-c", repo=False)
        _ = m.put_entry("s3", c, legacy=True)
        _ = m.put_entry("s4", c)
        d = m.fixture_route("route-d", repo=False, run=None)
        _ = m.put_entry("s5", d, legacy=True)
        f = m.fixture_route("route-f", repo=False, upgraded=True)
        _ = m.put_entry("s7", f)
        # another existing marker for route-f's planning dir: not its current one
        other = dataclasses.replace(f, marker=m.root / "other/.git/dsp-route.json")
        m.put_marker(other)
        _ = m.put_entry("s8", other, legacy=True, activated=time.time() - 60)
        mon = self.monitor_on(m, consts=FAST)
        s = mon.wait(lambda s: s["ready"])
        cases = {
            "upgraded: live, nothing ended": (a, [(a.run_key(), "live")]),
            "moved legacy marker: live": (b, [(b.run_key(), "live")]),
            "run, no run_upgraded: pre ended": (
                c,
                sorted([(c.run_key(), "live"), (f"{c.key}-pre", "ended")]),
            ),
            "3c70cb6 marker: pre live": (d, [(f"{d.key}-pre", "live")]),
            "another marker: pre ended (R64)": (
                f,
                sorted([(f.run_key(), "live"), (f"{f.key}-pre", "ended")]),
            ),
        }
        for label, (r, want) in cases.items():
            self.ok(label, states_of(s, r.key) == want, states_of(s, r.key))
        live = runs_of(s, b.key)
        sessions = [
            x["id"] for x in cast("list[dict[str, object]]", live[0]["sessions"])
        ]
        self.ok("moved legacy marker: s2 on the live run", sessions == ["s2"], live)
        self.ok(f"{len(cases)} cases", cases)

    def test_a28_split(self) -> None:
        """A 3c70cb6 rewrite then a new activation: r ended, r2 live, two runs."""
        m = self.machine()
        r = self.act(m, "s1")
        self.edit_marker(lambda mk: mk.pop("run"), self.repo)
        r2 = self.act(m, "s2")
        key = common.route_slug(str(self.plan))
        mon = self.monitor_on(m, consts=FAST)
        s = mon.wait(lambda s: s["ready"])
        want = sorted([(f"{key}-{r}", "ended"), (f"{key}-{r2}", "live")])
        got = states_of(s, key)
        self.ok("r ended, r2 live", r != r2 and got == want, got)

    def test_session_moved_routes(self) -> None:
        """A stays listed after s1 moves to B: by `previous` alone, then by a line."""
        m = self.machine()
        a_run = self.act(m, "s1")
        b_plan = self.repo / "planb"
        b_plan.mkdir()
        _ = self.act(m, "s1", b_plan)
        a = self.fixture(self.plan, a_run)
        mon = self.monitor_on(m, consts=FAST)
        s = mon.wait(lambda s: s["ready"])
        want = [(a.run_key(), "live")]
        self.ok("(ii) no log: A listed by previous", states_of(s, a.key) == want, s)
        _ = m.put_events("s1", m.line(a, "s1", "turn-end", time.time() - 5))
        s = mon.wait(
            lambda s: runs_of(s, a.key) and runs_of(s, a.key)[0]["first_seen_at"]
        )
        self.ok("(i) a line: A listed", states_of(s, a.key) == want, s)
        self.rm(a.marker)
        s = mon.wait(lambda s: states_of(s, a.key) == [(a.run_key(), "ended")])
        self.ok("A's marker deleted: ended", s)

    def test_bad_registry_files(self) -> None:
        """A sidecar is ignored; a bad entry or `previous` item is one error each."""
        m = support.Machine(self.T / self._testMethodName)
        a = m.fixture_route("route-a", repo=False)
        _ = m.put_entry("s1", a)
        _ = m.put(m.registry / "s1.waits.json", '{"jobs": []}\n')
        _ = m.put(m.registry / "s2.json", '{"marker": ')
        _ = m.put_entry("s3", a, previous=[{"marker": 1}])
        extra = cast("dict[str, object]", json.loads(m.put_entry("s4", a).read_text()))
        extra["zz_new"] = 1
        _ = m.put(m.registry / "s4.json", json.dumps(extra))
        mon = self.monitor_on(m, consts=FAST)
        s = mon.wait(lambda s: s["ready"])
        errors = cast("list[dict[str, str]]", s["errors"])
        sources = sorted(e["source"] for e in errors)
        self.ok(
            f"{len(errors)} errors: s2, s3", sources == ["s2.json", "s3.json"], errors
        )
        live = runs_of(s, a.key)
        ids = [x["id"] for x in cast("list[dict[str, object]]", live[0]["sessions"])]
        self.ok("s1, s3 and s4 load", ids == ["s1", "s3", "s4"], ids)
        listed = len(cast("list[object]", s["routes"])) + len(
            cast("list[object]", s["ended"])
        )
        self.ok("one route", listed == 1, s)

    def test_idle_collapse_order(self) -> None:
        """Two active and three idle routes, each newest first; flips at IDLE_S."""
        m = support.Machine(self.T / self._testMethodName)
        idle = dsp_monitor.IDLE_S
        ages = {
            "route-a": 10,
            "route-b": 20,
            "route-c": idle + 100,
            "route-d": idle + 200,
            "route-e": idle + 300,
        }
        for i, (name, age) in enumerate(ages.items(), 1):
            r = m.fixture_route(name, repo=False)
            _ = m.put_entry(f"s{i}", r, activated=time.time() - age)
            self.touch(r.marker, -age)
        keys = {n: r.key for n, r in m.routes.items()}
        mon = self.monitor_on(m, consts=FAST)
        s = mon.wait(lambda s: s["ready"])

        def order(state: dict[str, object], group: str) -> list[str]:
            return [
                str(r["key"]) for r in cast("list[dict[str, object]]", state[group])
            ]

        want_active = [keys["route-a"], keys["route-b"]]
        want_idle = [keys["route-c"], keys["route-d"], keys["route-e"]]
        self.ok("routes: the 2 active, newest first", order(s, "routes") == want_active)
        self.ok("idle: the 3 idle, newest first", order(s, "idle") == want_idle)
        counts = cast("dict[str, int]", s["counts"])
        self.ok("counts.idle 3", counts["idle"] == len(want_idle), counts)
        e = m.routes["route-e"].marker
        self.touch(e.with_name(f"{e.stem}.s5.last"), -5)
        s = mon.wait(lambda s: keys["route-e"] in order(s, "routes"))
        self.ok("route-e's .last now: active", order(s, "routes")[0] == keys["route-e"])


class MarkerReader(support.MonitorSandbox):
    """The marker read: one retry on a failed read, none on a torn one."""

    def test_absent_and_torn_marker(self) -> None:
        """Absent once: ok; twice: ended; torn: kept, or live and unreadable."""
        good = b'{"planning_dir": "p", "run": "r"}'
        path = self.T / "x.json"
        sleep = unittest.mock.patch("time.sleep")
        cases = {
            "absent once: ok": ([FileNotFoundError(), good], "ok", 2, 1),
            "absent twice: absent": ([FileNotFoundError(), OSError()], "absent", 2, 1),
            "truncated: torn": ([good[:9]], "torn", 1, 0),
        }
        for label, (effects, want, calls, sleeps) in cases.items():
            with (
                sleep as slept,
                unittest.mock.patch.object(
                    dsp_monitor, "_read_bytes", side_effect=effects
                ) as read,
            ):
                got = dsp_monitor.read_marker(path).status
            self.ok(f"{label}", got == want, got)
            self.ok(f"{label}: {calls} reads", read.call_count == calls)
            self.ok(f"{label}: {sleeps} sleeps", slept.call_count == sleeps)
        m = support.Machine(self.T / self._testMethodName)
        a = m.fixture_route("route-a", repo=False)
        _ = m.put_entry("s1", a)
        scanner = dsp_monitor.Scanner(m.registry, m.registry / "events")

        def model(effects: object, prev: dsp_monitor.Model | None) -> dsp_monitor.Model:
            with (
                sleep,
                unittest.mock.patch.object(
                    dsp_monitor, "_read_bytes", side_effect=effects
                ),
            ):
                return dsp_monitor.discover(
                    scanner.scan(time.time()), prev, time.time()
                )

        body = a.marker.read_bytes()
        first = model([FileNotFoundError(), body], None)
        live = first.routes[a.key].live
        self.ok("absent once: live", live is not None and live.run == a.run)
        gone = model(OSError, first)
        self.ok("absent twice: ended", gone.routes[a.key].live is None)
        kept = model([body[:9]], first).routes[a.key]
        self.ok("torn after a scan: still live", kept.live is not None)
        fresh = model([body[:9]], None).routes[a.key]
        self.ok("torn, no scan before: live", fresh.live is not None)
        detail = dsp_monitor.run_detail(fresh, fresh.live) if fresh.live else {}
        items = cast("list[dict[str, object]]", detail.get("attention", []))
        names = [i["subject"] for i in items]
        self.ok("an unreadable item names it", names == [a.marker.name], items)


# one event of a fold case: its kind, its seconds after T0 and its fields
Step = tuple[str, float, dict[str, object]]
W = support.WORKER
T0 = float(int(time.time()) - 1000)
DISPATCH: Step = ("dispatch", 0, {"tuid": "t-1", "name": "worker-1"})
LAUNCH: Step = (
    "launch",
    1,
    {"tuid": "t-1", "child": W, "mode": "background", "name": "worker-1"},
)
START: Step = ("start", 2, {"agent": W})
BASH: Step = ("pre", 3, {"agent": W, "tool": "Bash", "tuid": "t-2"})
RUNNING = ("dispatched", "launched", "active")
MATE: list[Step] = [
    ("dispatch", 0, {"tuid": "t-1", "name": "mate-1"}),
    (
        "launch",
        1,
        {"tuid": "t-1", "child": W, "mode": "teammate", "name": "mate-1", "team": "tm"},
    ),
    START,
    ("stop", 3, {"agent": W}),
]
# case: (its lines, the one agent's expected fields or None for no agent, unjoined)
FOLD: dict[str, tuple[list[Step], dict[str, object] | None, int]] = {
    "unnamed dispatch, start, pre, launch: one active agent": (
        [
            ("dispatch", 0, {"tuid": "t-1"}),
            START,
            BASH,
            ("launch", 4, {"tuid": "t-1", "child": W, "mode": "background"}),
        ],
        {"state": "active", "mode": "background", "open_tool": "Bash"},
        0,
    ),
    "dispatch, launch, then start: still active": (
        [DISPATCH, LAUNCH, START],
        {"state": "active", "name": "worker-1", "mode": "background"},
        0,
    ),
    "a bare stop opens no agent": ([("stop", 0, {"agent": W})], None, 1),
    "a background stop: returned at its ts": (
        [DISPATCH, LAUNCH, START, BASH, ("stop", 10, {"agent": W})],
        {
            "state": "returned",
            "ended_at": dsp_monitor.iso(T0 + 10),
            "duration_s": 10.0,
            "final_tokens": None,
            "open_tool": None,
        },
        0,
    ),
    "TaskStop by name: stopped, its call closed": (
        [
            DISPATCH,
            LAUNCH,
            START,
            BASH,
            ("post", 9, {"tool": "TaskStop", "tuid": "t-3", "target": "worker-1"}),
        ],
        {"state": "stopped", "ended_at": dsp_monitor.iso(T0 + 9), "open_tool": None},
        0,
    ),
    "TaskStop by task id: unjoined, nothing changes": (
        [
            DISPATCH,
            LAUNCH,
            START,
            BASH,
            ("post", 9, {"tool": "TaskStop", "tuid": "t-3", "target": "b0tsk1"}),
        ],
        {"state": "active", "ended_at": None, "open_tool": "Bash"},
        1,
    ),
    "a denied dispatch: held, no mode": (
        [("dispatch", 0, {"tuid": "t-1", "name": "worker-1", "decision": "deny"})],
        {"state": "held", "mode": None},
        0,
    ),
    "a dispatch, then the lead's turn-end: interrupted": (
        [DISPATCH, ("turn-end", 1, {})],
        {"state": "interrupted"},
        0,
    ),
    "a return with no launch: foreground, its figures": (
        [
            DISPATCH,
            START,
            (
                "return",
                5,
                {
                    "tuid": "t-1",
                    "child": W,
                    "name": "worker-1",
                    "ms": 4000,
                    "tools": 3,
                    "final_tokens": 900,
                },
            ),
        ],
        {
            "state": "returned",
            "mode": "foreground",
            "duration_s": 4.0,
            "tools": 3,
            "final_tokens": 900,
        },
        0,
    ),
    "a teammate's stop: stopped": (MATE, {"state": "stopped", "mode": "teammate"}, 0),
    "a teammate restarted, then idle by name and team": (
        [
            *MATE,
            ("start", 4, {"agent": W}),
            ("idle", 5, {"teammate": "mate-1", "team": "tm"}),
        ],
        {"state": "idle"},
        0,
    ),
    "session-end: ended with the session": (
        [DISPATCH, LAUNCH, START, ("session-end", 5, {"reason": "other"})],
        {"state": "ended-with-session"},
        0,
    ),
    "resume: lost": (
        [DISPATCH, LAUNCH, START, ("session", 4, {"source": "resume"})],
        {"state": "lost"},
        0,
    ),
    "resume, then its pre: active again": (
        [
            DISPATCH,
            LAUNCH,
            START,
            ("session", 4, {"source": "resume"}),
            ("pre", 5, {"agent": W, "tool": "Read", "tuid": "t-5"}),
        ],
        {"state": "active", "last_tool": "Read"},
        0,
    ),
    "a later pre after a later post closes the open call": (
        [
            DISPATCH,
            LAUNCH,
            START,
            BASH,
            ("post", 4, {"agent": W, "tool": "Read", "tuid": "t-4"}),
            ("pre", 5, {"agent": W, "tool": "Edit", "tuid": "t-5"}),
        ],
        {"open_tool": "Edit", "open_since": dsp_monitor.iso(T0 + 5)},
        0,
    ),
    "api-error: failed until a later start": (
        [DISPATCH, LAUNCH, START, ("api-error", 3, {"agent": W})],
        {"state": "failed"},
        0,
    ),
    "api-error, then a start: active": (
        [
            DISPATCH,
            LAUNCH,
            START,
            ("api-error", 3, {"agent": W}),
            ("start", 4, {"agent": W}),
        ],
        {"state": "active"},
        0,
    ),
}


def model_of(m: support.Machine) -> dsp_monitor.Model:
    """One in-process scan of m and the model it gives."""
    now = time.time()
    scanner = dsp_monitor.Scanner(m.registry, m.registry / "events")
    return dsp_monitor.discover(scanner.scan(now), None, now)


def detail_of(
    model: dsp_monitor.Model, r: support.FixtureRoute, run: str | None = None
) -> dict[str, object]:
    """The RunDetail of r's run (default its own) in model."""
    route = model.routes[r.key]
    found = next(x for x in route.runs if x.key == r.run_key(run))
    return dsp_monitor.run_detail(route, found)


class Events(support.MonitorSandbox):
    """The event logs: tailing, the agent fold and recording states (§4.5, §3.6.4)."""

    def test_event_log_tolerance(self) -> None:
        """Skips counted, a partial line waits, a replaced log restarts, dupes once."""
        m = support.Machine(self.T / self._testMethodName)
        a = m.fixture_route("route-a", repo=False)
        _ = m.put_entry("s1", a)
        pre = m.line(a, "s1", "pre", T0, tool="Bash", tuid="t-1")
        bare = m.line(a, "s1", "post", T0 + 1, tool="Read")
        lines = [
            support.jline(pre),
            '{"v": 1, "ts": ',
            support.jline({**pre, "v": 99, "tuid": "t-9"}),
            support.jline(pre),
            support.jline(bare),
            support.jline({**bare, "ts": T0 + 2}),
            support.jline(bare),
            support.jline({**pre, "ev": "zz-new", "tuid": "t-8"}),
        ]
        tail = support.jline(m.line(a, "s1", "turn-end", T0 + 3))
        log = m.put(m.registry / "events/s1.jsonl", "\n".join(lines) + "\n" + tail)
        scanner = dsp_monitor.Scanner(m.registry, m.registry / "events")
        group = (a.run, str(a.plan), str(a.marker))

        def counts() -> tuple[int, int, list[int]]:
            now = time.time()
            model = dsp_monitor.discover(scanner.scan(now), None, now)
            sessions = cast("list[dict[str, object]]", detail_of(model, a)["sessions"])
            got = scanner.logs["s1"].groups[group].lines
            skipped = cast("int", sessions[0]["events_skipped"])
            return got, skipped, cast("list[int]", sessions[0]["unknown_versions"])

        written = [*lines, f"{tail} (no newline)"]
        got = counts()
        kept = ["pre", "bare", "bare a ts later"]
        self.ok(f"{len(written)} lines written", written, "\n".join(written))
        self.ok(
            "3 lines: a dupe once, a ts apart twice, no unknown ev, no partial line",
            got[0] == len(kept),
            got,
        )
        self.ok("a torn line and v 99 skipped", got[1] == len(["torn", "v99"]), got)
        self.ok("unknown_versions [99]", got[2] == [99], got)
        with log.open("a") as f:
            _ = f.write("\n")
        got = counts()
        self.ok(
            "the partial line, completed, counts", got[0] == len([*kept, tail]), got
        )
        new = log.with_name("s1.new")
        _ = new.write_text(f"{tail}\n{support.jline(pre)}\n")
        _ = new.replace(log)
        got = counts()
        self.ok("a replaced shorter log: re-read from 0", got == (2, 0, []), got)
        _ = log.write_text(f"{tail}\n")
        got = counts()
        self.ok("a log cut in place: re-read from 0", got == (1, 0, []), got)

    def test_recording_states(self) -> None:
        """Recording none (naming the switch), reduced, expired, seen; no switch key."""
        from dsp_route import record, switch

        m = support.Machine(self.T / self._testMethodName)
        now = time.time()
        a = m.fixture_route("route-a", repo=False)
        _ = m.put_entry("s1", a)
        b = m.fixture_route("route-b", repo=False)
        _ = m.put_entry("s2", b)
        _ = m.put_events(
            "s2",
            m.line(b, "s2", "turn-end", now - 10),
            m.line(b, "s2", "cap", now - 5, bytes=record.CAP_BYTES),
        )
        past = now - (record.RETENTION_DAYS + 1) * 86400
        c = m.fixture_route("route-c", repo=False)
        old = support.run_id(50)
        _ = m.put_entry("s3", c, previous=[m.prev(c, old)], activated=past)
        d = m.fixture_route("route-d", repo=False)
        _ = m.put_entry("s4", d, previous=[m.prev(d, old)], activated=past)
        _ = m.put_events("s4", m.line(d, "s4", "turn-end", past, run=old))
        model = model_of(m)
        cases = {
            "no log: none": (a, None, "none"),
            "a cap line: reduced": (b, None, "reduced"),
            "ended, past retention, no line: expired": (c, old, "expired"),
            "ended, past retention, a line: seen": (d, old, "seen"),
            "live, no line: none": (c, None, "none"),
        }
        for label, (r, run, want) in cases.items():
            got = detail_of(model, r, run)
            self.ok(label, got["recording"] == want, got)
            hint = got["recording_hint"]
            named = isinstance(hint, str) and switch.NAME in hint
            self.ok(f"{label}: hint", named if want == "none" else hint is None, hint)
            running = cast("dict[str, object]", got["summary"])["agents_running"]
            unknown = want in {"none", "expired"}
            self.ok(f"{label}: agents_running", (running is None) == unknown, running)
        ref = refreshed(model)
        for label, r in {"none": a, "reduced": b}.items():
            route = model.routes[r.key]
            run = route.live
            got = (
                {} if run is None else dsp_monitor.run_detail(route, run, ref.of(route))
            )
            self.ok(f"{label}: still carries its report", got.get("report"), got)
        live = dsp_monitor.Live(dsp_monitor.read_page(dsp_monitor.PAGE), "n")
        live.bound(0)
        live.publish(model)
        keys: list[str] = []

        def walk(v: object) -> None:
            if isinstance(v, dict):
                for k, x in cast("dict[str, object]", v).items():
                    keys.append(k)
                    walk(x)
            elif isinstance(v, list):
                for x in cast("list[object]", v):
                    walk(x)

        for body in [live.state, *live.runs.values()]:
            walk(cast("object", json.loads(body)))
        bad = [k for k in keys if k in {"tracking", "switch", "enabled"}]
        self.ok(f"{len(keys)} keys, no machine-wide switch", keys and not bad, bad)

    def test_api_never_exposes_event_text(self) -> None:
        """desc, cwd, to and error reach no response body of any endpoint."""
        mark = "ZZ-MARK-7f3a"
        m = support.Machine(self.T / self._testMethodName)
        a = m.fixture_route("route-a", repo=False)
        _ = m.put_entry("s1", a)
        now = time.time()
        log = m.put_events(
            "s1",
            m.line(a, "s1", "dispatch", now - 50, tuid="t-1", name="w-1", desc=mark),
            m.line(
                a,
                "s1",
                "launch",
                now - 49,
                tuid="t-1",
                child=W,
                mode="background",
                name="w-1",
                cwd=mark,
            ),
            m.line(
                a, "s1", "pre", now - 40, agent=W, tool="Bash", tuid="t-2", desc=mark
            ),
            m.line(a, "s1", "pre", now - 30, tool="SendMessage", tuid="t-3", to=mark),
            m.line(a, "s1", "failed", now - 20, tuid="t-4", name="w-2", error=mark),
            m.line(a, "s1", "api-error", now - 10, agent=W, error=mark),
        )
        marked = ["dispatch desc", "launch cwd", "pre desc", "to", "error", "error"]
        found = log.read_text().count(mark)
        self.ok(f"the mark is in the log {found} times", found == len(marked))
        mon = self.monitor_on(m, consts=FAST)
        s = mon.wait(lambda s: runs_of(s, a.key) and runs_of(s, a.key)[0]["agents"])
        agents = cast("list[object]", runs_of(s, a.key)[0]["agents"])
        self.ok(f"{len(agents)} agents folded", len(agents) == len(["w-1", "w-2"]))
        paths = ["/api/state", "/api/ping"]
        paths += [f"/api/run?key={r['key']}" for r in runs_of(s, a.key)]
        bodies = [mon.get(p)[2] for p in paths]
        size = sum(map(len, bodies))
        leaks = [p for p, b in zip(paths, bodies, strict=True) if mark.encode() in b]
        self.ok(
            f"{size} bytes, {len(paths)} responses: no mark", size and not leaks, leaks
        )

    def test_agent_fold(self) -> None:
        """§3.6.4's states, the joins as measured, a TaskStop by name; one per case."""
        for i, (label, (steps, want, unjoined)) in enumerate(FOLD.items()):
            m = support.Machine(self.T / f"case{i}")
            a = m.fixture_route("route-a", repo=False)
            _ = m.put_entry("s1", a)
            lines = [m.line(a, "s1", ev, T0 + at, **f) for ev, at, f in steps]
            _ = m.put_events("s1", *lines)
            model = model_of(m)
            got = detail_of(model, a)
            agents = cast("list[dict[str, object]]", got["agents"])
            count = 0 if want is None else 1
            self.ok(f"{label}: {count} agent", len(agents) == count, agents)
            self.ok(
                f"{label}: {unjoined} unjoined",
                model.events_unjoined == unjoined,
                model.events_unjoined,
            )
            running = cast("dict[str, object]", got["summary"])["agents_running"]
            want_running = sum(x["state"] in RUNNING for x in agents)
            self.ok(f"{label}: agents_running", running == want_running, running)
            if want is not None and agents:
                diff = {
                    k: agents[0].get(k) for k in want if agents[0].get(k) != want[k]
                }
                self.ok(f"{label}: fields", not diff, diff)
        self.ok(f"{len(FOLD)} cases", FOLD)


def one_route(
    root: Path, steps: list[Step], t0: float, quiet: float = 0
) -> tuple[support.Machine, support.FixtureRoute]:
    """A machine of one route, session s1, its lines at t0 + each step's offset.

    quiet: how long ago the route's entry, marker and lines last moved, besides t0.
    """
    m = support.Machine(root)
    a = m.fixture_route("route-a", repo=False)
    _ = m.put_entry("s1", a, activated=time.time() - quiet)
    support.Sandbox.touch(a.marker, -quiet)
    lines = [m.line(a, "s1", ev, t0 - quiet + at, **f) for ev, at, f in steps]
    if lines:
        _ = m.put_events("s1", *lines)
    return m, a


def items_of(detail: dict[str, object], group: str) -> list[dict[str, object]]:
    """The `waiting` or `attention` items of a RunDetail."""
    return cast("list[dict[str, object]]", detail[group])


ASK: Step = ("pre", 3, {"agent": W, "tool": "AskUserQuestion", "tuid": "t-2"})
# case: (its lines, whether the one agent is likely stuck, the stuck items' subjects)
STUCK: dict[str, tuple[list[Step], bool | None, list[str]]] = {
    "an open Bash pre past STUCK_S": (
        [DISPATCH, LAUNCH, START, BASH],
        True,
        ["worker-1"],
    ),
    "a bare dispatch": ([DISPATCH], False, []),
    "an idle teammate": (
        [
            *MATE[:3],
            ("pre", 3, {"agent": W, "tool": "Bash", "tuid": "t-2"}),
            ("idle", 4, {"teammate": "mate-1", "team": "tm"}),
        ],
        False,
        [],
    ),
    "a failed agent": (
        [DISPATCH, LAUNCH, START, BASH, ("api-error", 4, {"agent": W})],
        False,
        [],
    ),
    "an open AskUserQuestion pre": ([DISPATCH, LAUNCH, START, ASK], False, []),
    "a held pre": (
        [
            DISPATCH,
            LAUNCH,
            START,
            ("pre", 3, {"agent": W, "tool": "Bash", "tuid": "t-2", "decision": "ask"}),
        ],
        False,
        [],
    ),
    "closed by a later post, then a recent pre": (
        [
            DISPATCH,
            LAUNCH,
            START,
            BASH,
            ("post", 4, {"agent": W, "tool": "Read", "tuid": "t-4"}),
            ("pre", 990, {"agent": W, "tool": "Edit", "tuid": "t-5"}),
        ],
        False,
        [],
    ),
    "closed by a stop": (
        [DISPATCH, LAUNCH, START, BASH, ("stop", 4, {"agent": W})],
        False,
        [],
    ),
    # a foreground agent: its return is the Agent call's only PostToolUse
    "closed by a return": (
        [
            DISPATCH,
            START,
            BASH,
            ("return", 4, {"tuid": "t-1", "child": W, "name": "worker-1"}),
        ],
        False,
        [],
    ),
    "closed by a failed": (
        [DISPATCH, LAUNCH, START, BASH, ("failed", 4, {"tuid": "t-1", "child": W})],
        False,
        [],
    ),
    "the lead's open Bash pre": (
        [("pre", 3, {"tool": "Bash", "tuid": "t-9"})],
        None,
        ["lead"],
    ),
    "the lead's call closed by its turn-end": (
        [("pre", 3, {"tool": "Bash", "tuid": "t-9"}), ("turn-end", 4, {})],
        None,
        [],
    ),
    "a cap line: still stuck, worded uncertain": (
        [DISPATCH, LAUNCH, START, BASH, ("cap", 4, {"bytes": 1})],
        True,
        ["worker-1"],
    ),
}


class Attention(support.MonitorSandbox):
    """Likely stuck, waiting on you, and the attention items (§4.5, §4.10)."""

    def test_likely_stuck(self) -> None:
        """An open call past STUCK_S, and only that; never on an idle route."""
        t0 = time.time() - 1000
        cases = {k: (*v, 0.0) for k, v in STUCK.items()}
        bash = [DISPATCH, LAUNCH, START, BASH]
        cases["an idle route's agent"] = (bash, False, [], dsp_monitor.IDLE_S + 100)
        for i, (label, (steps, want, subjects, quiet)) in enumerate(cases.items()):
            m, a = one_route(self.T / f"stuck{i}", steps, t0, quiet)
            got = detail_of(model_of(m), a)
            agents = cast("list[dict[str, object]]", got["agents"])
            if want is not None:
                flag = agents[0]["likely_stuck"] if agents else None
                self.ok(f"{label}: likely_stuck {want}", flag is want, agents)
            stuck = [i for i in items_of(got, "attention") if i["kind"] == "stuck"]
            names = [i["subject"] for i in stuck]
            self.ok(f"{label}: stuck items {subjects}", names == subjects, stuck)
            for item in stuck:
                text = str(item["text"])
                self.ok(f"{label}: amber", item["severity"] == "amber", item)
                self.ok(
                    f"{label}: text",
                    text.startswith("may be stuck — Bash open for "),
                    text,
                )
                capped = "cap line" in label
                qualified = dsp_monitor.COPY["reduced"] in text
                self.ok(f"{label}: qualifier {capped}", qualified == capped, text)
        self.ok(f"{len(cases)} cases", cases)

    def test_waiting_on_you(self) -> None:
        """Asked and input from each session's newest lead event; ordered, counted."""
        t0 = float(int(time.time()) - 1000)
        bash: Step = ("pre", 900, {"agent": W, "tool": "Bash", "tuid": "t-2"})
        cases: dict[str, tuple[list[Step], str | None]] = {
            "a pre held to ask": (
                [("pre", 1, {"tool": "Bash", "tuid": "t-9", "decision": "ask"})],
                "asked",
            ),
            "a dispatch held to ask": (
                [("dispatch", 2, {"tuid": "t-1", "decision": "ask"})],
                "asked",
            ),
            "an AskUserQuestion pre": (
                [("pre", 3, {"tool": "AskUserQuestion", "tuid": "t-9"})],
                "asked",
            ),
            "a permission prompt": (
                [("notify", 4, {"type": "permission_prompt"})],
                "asked",
            ),
            "an elicitation dialog": (
                [("notify", 5, {"type": "elicitation_dialog"})],
                "asked",
            ),
            "a notify of another type is skipped": (
                [
                    ("pre", 6, {"tool": "AskUserQuestion", "tuid": "t-9"}),
                    ("notify", 7, {"type": "auth_success"}),
                ],
                "asked",
            ),
            "a turn-end with no background task": (
                [("turn-end", 8, {"bg_tasks": 0})],
                "input",
            ),
            "an idle prompt": ([("notify", 9, {"type": "idle_prompt"})], "input"),
            "a turn-end with background tasks": (
                [("turn-end", 10, {"bg_tasks": 2})],
                None,
            ),
            "a turn-end while an agent runs": (
                [DISPATCH, LAUNCH, START, bash, ("turn-end", 950, {"bg_tasks": 0})],
                None,
            ),
            "a newer lead line": (
                [
                    ("pre", 11, {"tool": "AskUserQuestion", "tuid": "t-9"}),
                    ("post", 12, {"tool": "AskUserQuestion", "tuid": "t-9"}),
                ],
                None,
            ),
            "an ended session": (
                [
                    ("pre", 13, {"tool": "AskUserQuestion", "tuid": "t-9"}),
                    ("session-end", 14, {"reason": "other"}),
                ],
                None,
            ),
            "a reduced session: asked, qualified": (
                [
                    ("cap", 15, {"bytes": 1}),
                    ("pre", 16, {"tool": "AskUserQuestion", "tuid": "t-9"}),
                ],
                "asked",
            ),
        }
        live = dsp_monitor.Live(dsp_monitor.read_page(dsp_monitor.PAGE), "n")
        live.bound(0)
        routes: dict[str, dsp_monitor.Route] = {}
        for i, (label, (steps, want)) in enumerate(cases.items()):
            m, a = one_route(self.T / f"wait{i}", steps, t0)
            model = model_of(m)
            routes |= model.routes
            got = items_of(detail_of(model, a), "waiting")
            kinds = [x["kind"] for x in got]
            self.ok(f"{label}: {want}", kinds == ([want] if want else []), got)
            name = model.routes[a.key].name
            for x in got:
                # the newest line that counts: a skipped notify does not
                at = t0 + steps[-2 if "skipped" in label else -1][1]
                text = str(x["text"])
                self.ok(f"{label}: no severity", x["severity"] is None, x)
                self.ok(f"{label}: subject s1", x["subject"] == "s1", x)
                self.ok(f"{label}: since", x["since"] == dsp_monitor.iso(at), x)
                head = f"{name} · {x['kind']} · since {dsp_monitor.hhmm(at)}"
                self.ok(f"{label}: text", text.startswith(head), text)
                reduced = dsp_monitor.COPY["reduced"] in text
                self.ok(f"{label}: qualifier", reduced == ("reduced" in label), text)
        live.publish(dsp_monitor.Model(routes, []))
        state = cast("dict[str, object]", json.loads(live.state))
        top = cast("list[dict[str, object]]", state["waiting"])
        sinces = [str(x["since"]) for x in top]
        want = sum(1 for _, w in cases.values() if w)
        self.ok(f"{len(top)} waiting, oldest first", len(top) == want, top)
        self.ok("ordered by since", sinces == sorted(sinces), sinces)
        counts = cast("dict[str, int]", state["counts"])
        self.ok("counts.waiting", counts["waiting"] == want, counts)
        self.ok(f"{len(cases)} cases", cases)

    def test_attention_items(self) -> None:
        """blind, dir-missing, reduced and unreadable: kind, severity, text, order."""
        m = support.build_machine(self.T / "machine")
        a, b, c, d = (m.routes[f"route-{x}"] for x in "abcd")
        _ = m.put_events("s1", {"v": 1, "ts": "torn"})
        _ = m.put_events("s2", m.line(b, "s2", "cap", time.time() - 20, bytes=1))
        self.rm(d.plan)
        model = model_of(m)
        want = [
            (a, [("unreadable", "amber", "s1.jsonl", "unreadable: s1.jsonl")]),
            (b, [("reduced", "amber", None, dsp_monitor.COPY["reduced"])]),
            (c, [("blind", "red", None, "— tool_use_id")]),
            (d, [("dir-missing", "red", None, dsp_monitor.COPY["dir-missing"])]),
        ]
        for r, items in want:
            got = items_of(detail_of(model, r), "attention")
            have = [(x["kind"], x["severity"], x["subject"]) for x in got]
            self.ok(f"{r.name}: {items}", have == [i[:3] for i in items], got)
            texts = [str(x["text"]) for x in got]
            ends = all(t.endswith(i[3]) for t, i in zip(texts, items, strict=False))
            self.ok(f"{r.name}: texts", ends, texts)
        live = dsp_monitor.Live(dsp_monitor.read_page(dsp_monitor.PAGE), "n")
        live.bound(0)
        live.publish(model)
        state = cast("dict[str, object]", json.loads(live.state))
        top = cast("list[dict[str, object]]", state["attention"])
        kinds = [x["kind"] for x in top]
        order = ["blind", "dir-missing", "reduced", "unreadable"]
        self.ok(f"{len(top)} items: red, oldest first, then amber", kinds == order, top)


# every interval of the refresher at most 1 s, so a test sees several cycles
QUICK = {"SCAN_S": 0.05, "FREE_TTL_S": 1, "GIT_TTL_S": 1, "GIT_FLOOR_S": 1}


def probed(path: Path) -> list[dict[str, object]]:
    """The probe's records so far."""
    if not path.exists():
        return []
    return [
        cast("dict[str, object]", json.loads(x)) for x in path.read_text().splitlines()
    ]


def live_runs(state: dict[str, object]) -> list[dict[str, object]]:
    """The live run of every route /api/state lists as active or idle."""
    return [
        cast("dict[str, object]", r["run"])
        for group in ("routes", "idle")
        for r in cast("list[dict[str, object]]", state[group])
    ]


def git_of(state: dict[str, object], key: str) -> dict[str, object]:
    """The `git` of route key's live run; {} while it is not listed."""
    runs = [r for r in live_runs(state) if str(r["key"]).startswith(f"{key}-")]
    return cast("dict[str, object]", runs[0]["git"]) if runs else {}


def refreshed(model: dsp_monitor.Model) -> dsp_monitor.Refresher:
    """A refresher that ran, in-process, every refresh due on model."""
    ref = dsp_monitor.Refresher(lambda: None)
    ref.due(model, time.monotonic())
    ref.pool.shutdown(wait=True)
    return ref


class Refresh(support.MonitorSandbox):
    """Report refreshes: only after polls, under per-route limits and deadlines."""

    def machine(self) -> tuple[support.Machine, Path]:
        """This test's own machine, and its own directory for the shim and probe."""
        d = self.T / self._testMethodName
        return support.build_machine(d), d

    def test_no_work_without_polls(self) -> None:
        """Once every live run's git is in, no poll means no git and no collect."""
        m, d = self.machine()
        _, log = self.git_shim(d / "shim")
        probe = d / "probe.jsonl"
        mon = self.monitor_on(m, consts=QUICK, probe=probe, path_prefix=[d / "shim"])
        _ = mon.wait(
            lambda s: (
                live_runs(s)
                and all(
                    cast("dict[str, object]", r["git"])["state"] != "pending"
                    for r in live_runs(s)
                )
            ),
            timeout=60,
        )

        def counts() -> tuple[int, int]:
            spawns = len(log.read_text().splitlines()) if log.exists() else 0
            return spawns, len(probed(probe))

        # what the last polls made due finishes first
        before, end = counts(), time.monotonic() + 30
        while time.monotonic() < end:
            time.sleep(1)
            now = counts()
            if now == before:
                break
            before = now
        time.sleep(3 * max(QUICK.values()))
        after = counts()
        spawned, collected = after[0] - before[0], after[1] - before[1]
        self.ok(f"{before[0]} spawns before; {spawned} without polls", spawned == 0)
        self.ok(f"{before[1]} probe lines before; {collected} without", collected == 0)
        self.ok("work was done while polled", before[0] and before[1], before)

    def test_limits_apply_to_every_poll(self) -> None:
        """Three clients polling: git refreshes per route and git processes capped."""
        m, d = self.machine()
        _, log = self.git_shim(d / "shim", ends=True)
        probe = d / "probe.jsonl"
        mon = self.monitor_on(m, consts=QUICK, probe=probe, path_prefix=[d / "shim"])
        window = 6.0
        w0 = time.monotonic()

        def poll() -> None:
            while time.monotonic() < w0 + window:
                _ = mon.get("/api/state")
                time.sleep(0.2)

        threads = [threading.Thread(target=poll) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        w1 = time.monotonic()
        per_route: dict[str, int] = {}
        for x in probed(probe):
            t0 = cast("float", x["t0"])
            if x["what"] == "collect" and x["use_git"] and w0 <= t0 <= w1:
                key = str(x["planning_dir"])
                per_route[key] = per_route.get(key, 0) + 1
        cap = math.ceil(window / QUICK["GIT_FLOOR_S"]) + 1
        most = max(per_route.values(), default=0)
        self.ok(f"{len(per_route)} routes: at most {most} git refreshes", per_route)
        self.ok(f"each at most {cap}", 0 < most <= cap, per_route)
        time.sleep(1)
        events: list[tuple[int, int]] = []
        for line in log.read_text().splitlines():
            kind, _, stamp = line.split(" ", 3)[:3]
            events.append((int(stamp), 1 if kind == "start" else -1))
        running = peak = 0
        for _, step in sorted(events):
            running += step
            peak = max(peak, running)
        workers = dsp_monitor.WORKERS
        self.ok(f"{len(events)} git stamps: {peak} at once", 0 < peak <= workers)

    def test_slow_repo_bounded_by_deadline(self) -> None:
        """route-d slow: kept git, deadline doubled, answers fast, git off handlers."""
        m, d = self.machine()
        flag = d / "slow"
        repo, plan = m.routes["route-d"].repo, str(m.routes["route-d"].plan)
        _, _log = self.git_shim(d / "shim", slow=(repo, flag))
        probe = d / "probe.jsonl"
        consts = {**QUICK, "DEADLINE_S": 3, "DEADLINE_MAX_S": 12, "WORKERS": 1}
        mon = self.monitor_on(m, consts=consts, probe=probe, path_prefix=[d / "shim"])
        key_d, key_a = m.routes["route-d"].key, m.routes["route-a"].key
        answers: list[float] = []

        def until(
            pred: Callable[[dict[str, object]], object], limit: float
        ) -> dict[str, object]:
            end = time.monotonic() + limit
            while True:
                t0 = time.monotonic()
                s = mon.state()
                answers.append(time.monotonic() - t0)
                if pred(s) or time.monotonic() > end:
                    return s
                time.sleep(0.2)

        s = until(lambda s: git_of(s, key_d).get("state") == "fresh", 60)
        good = git_of(s, key_d)
        self.ok("route-d: a good refresh first", good["state"] == "fresh", good)
        _ = flag.write_text("8")
        t_flag = time.monotonic()

        def slow_d() -> list[dict[str, object]]:
            return [
                x
                for x in probed(probe)
                if x["what"] == "collect"
                and x["use_git"]
                and x["planning_dir"] == plan
                and cast("float", x["t0"]) > t_flag
            ]

        s = until(lambda _: len(slow_d()) >= len(["3 s", "6 s"]), 60)
        flag.unlink()
        s = mon.state()
        got = git_of(s, key_d)
        self.ok("route-d: slow", got["state"] == "slow", got)
        self.ok("route-d: the good refresh's as_of", got["as_of"] == good["as_of"], got)
        took = [cast("float", x["t1"]) - cast("float", x["t0"]) for x in slow_d()]
        self.ok(f"route-d's slow refreshes took {took}", len(took) >= len(["3", "6"]))
        first, second = [*took, 0.0, 0.0][:2]
        self.ok("the first ends by its deadline + 1 s", first <= 3 + 1, took)
        self.ok("the next one's deadline doubled", 3 + 1 < second <= 6 + 1, took)
        self.ok(
            "route-a: fresh", git_of(s, key_a)["state"] == "fresh", git_of(s, key_a)
        )
        slowest = max(answers)
        self.ok(f"{len(answers)} answers, slowest {slowest:.3f} s", slowest < 1)
        records = probed(probe)
        runs = [x for x in records if x["what"] == "run"]
        off = [x for x in runs if not str(x["thread_name"]).startswith("dsp-worker")]
        self.ok(f"{len(runs)} spawns, {len(off)} off a worker", runs and not off, off)
        free = [x for x in records if x["what"] == "collect" and not x["use_git"]]
        bound = [x for x in free if not x["deadline_unset"]]
        self.ok(
            f"{len(free)} git-free collects, none under a deadline", free and not bound
        )

    def test_wall_step_back_keeps_refreshing(self) -> None:
        """The wall clock stepping an hour back delays no refresh that comes due."""
        m, d = self.machine()
        probe, step = d / "probe.jsonl", d / "step"
        plan = str(m.routes["route-a"].plan)
        mon = self.monitor_on(m, consts=QUICK, probe=probe, wall_step=(step, -3600))

        def collects(since: float) -> int:
            return sum(
                x["what"] == "collect"
                and x["planning_dir"] == plan
                and cast("float", x["t0"]) > since
                for x in probed(probe)
            )

        some = len(["one", "the next"])
        _ = mon.wait(lambda _: collects(0) >= some, timeout=30)
        _ = step.write_text("")
        t_step = time.monotonic() + 0.2
        end = t_step + 5 * QUICK["FREE_TTL_S"]
        while time.monotonic() < end:
            _ = mon.state()
            time.sleep(0.2)
        after = collects(t_step)
        self.ok(f"route-a: {after} refreshes after the step", after >= some, after)

    def test_deadline_halves_only_when_fast(self) -> None:
        """A refresh between d and 2 d: slow once, then fresh, and fresh again."""
        from dsp_route import report

        m = support.Machine(self.T / self._testMethodName)
        a = m.fixture_route("route-a")
        _ = m.put_entry("s1", a)
        model = model_of(m)

        def slower(*_a: object, **_k: object) -> dict[str, object]:
            time.sleep(2.5)
            return {"version": report.VERSION, "generated_at": time.time(), "git": None}

        seen: list[tuple[str, float]] = []
        with (
            unittest.mock.patch.multiple(dsp_monitor, DEADLINE_S=2, DEADLINE_MAX_S=12),
            unittest.mock.patch.object(report, "collect", slower),
        ):
            ref = dsp_monitor.Refresher(lambda: None)
            for i in range(3):
                # a scan far enough on that the git tier is due each time
                ref.due(model, time.monotonic() + 10_000 * (i + 1))
                end = time.monotonic() + 20
                while ref.routes[a.key].busy and time.monotonic() < end:
                    time.sleep(0.05)
                r = ref.routes[a.key]
                seen.append((r.git_state, r.deadline))
            ref.pool.shutdown(wait=True)
        want = [("slow", 4), ("fresh", 4), ("fresh", 4)]
        self.ok(f"three cycles: {seen}", seen == want, seen)


# §4.7's board table, written from the spec: (report lane state, its dependencies
# met; None where that does not matter) -> (column, gating)
SPEC_BOARD: dict[tuple[str, bool | None], tuple[str, bool]] = {
    ("queued", True): ("queued", False),
    ("queued", False): ("blocked", False),
    ("running", None): ("running", False),
    ("gating", None): ("running", True),
    ("ready", None): ("ready", False),
    ("red", None): ("failed", False),
    ("merged", None): ("merged", False),
}
# the key set of each §4.7 shape (with the amendments: routes/idle/counts, the
# recording hint, per-session skips, files_as_of and rev), written from the spec
SHAPES = {
    "state": {
        "version",
        "page",
        "generated_at",
        "ready",
        "monitor",
        "waiting",
        "attention",
        "routes",
        "idle",
        "counts",
        "ended",
        "errors",
        "events_unjoined",
    },
    "monitor": {"pid", "port"},
    "counts": {"waiting", "idle", "ended"},
    "item": {"kind", "severity", "route", "run", "subject", "since", "text"},
    "route": {
        "key",
        "name",
        "planning_dir",
        "repo",
        "status",
        "last_activity_at",
        "planning_dir_missing",
        "runs",
        "run",
    },
    "run": {
        "key",
        "run",
        "state",
        "first_seen_at",
        "last_activity_at",
        "ended_at",
        "sessions",
        "recording",
        "recording_hint",
        "blind_since",
        "report",
        "report_as_of",
        "report_error",
        "current_files",
        "files_as_of",
        "git",
        "lanes",
        "summary",
        "budget",
        "agents",
        "waiting",
        "attention",
    },
    "session": {
        "id",
        "activated_at",
        "last_activity_at",
        "recording",
        "blind_since",
        "ended",
        "events_skipped",
        "unknown_versions",
    },
    "agent": {
        "key",
        "session",
        "name",
        "mode",
        "state",
        "model",
        "started_at",
        "ended_at",
        "duration_s",
        "tools",
        "last_tool",
        "last_tool_at",
        "open_tool",
        "open_since",
        "final_tokens",
        "compactions",
        "likely_stuck",
    },
    "git": {"state", "as_of", "ms"},
    "lane": {"column", "gating"},
    "summary": {
        "stage",
        "waves_merged",
        "waves_total",
        "lanes_merged",
        "lanes_total",
        "agents_running",
    },
    "budget": {"label", "estimate", "groups", "at"},
    "ended": {"key", "name", "planning_dir", "runs"},
    "run_summary": {
        "key",
        "run",
        "first_seen_at",
        "last_activity_at",
        "sessions",
        "agents",
        "recording",
        "has_report",
        "rev",
    },
    "error": {"source", "reason"},
    "run_response": {"version", "generated_at", "route", "run"},
    "route_ref": {"key", "name", "planning_dir", "repo"},
}
# a skill digest no fixture id contains, written into route-a's registry entry
SKILL_DIGEST = "5ca1ab1e5ca1ab1e"


def strings(v: object) -> list[str]:
    """Every string of a parsed JSON value, keys included."""
    if isinstance(v, str):
        return [v]
    if isinstance(v, dict):
        d = cast("dict[str, object]", v)
        return [s for k, x in d.items() for s in [k, *strings(x)]]
    if isinstance(v, list):
        return [s for x in cast("list[object]", v) for s in strings(x)]
    return []


def dicts(v: object) -> list[dict[str, object]]:
    """Every object of a parsed JSON value, nested ones included."""
    if isinstance(v, dict):
        d = cast("dict[str, object]", v)
        return [d, *(o for x in d.values() for o in dicts(x))]
    if isinstance(v, list):
        return [o for x in cast("list[object]", v) for o in dicts(x)]
    return []


def run_of(state: dict[str, object], key: str) -> dict[str, object]:
    """The live run of route key in /api/state; {} while it is not listed."""
    runs = [r for r in live_runs(state) if str(r["key"]).startswith(f"{key}-")]
    return runs[0] if runs else {}


def ended_of(state: dict[str, object], key: str) -> list[dict[str, object]]:
    """The RunSummary list of route key in /api/state's `ended`."""
    for r in cast("list[dict[str, object]]", state["ended"]):
        if r["key"] == key:
            return cast("list[dict[str, object]]", r["runs"])
    return []


class Shape:
    """Checks of key sets and enum values; the mismatches and the fields checked."""

    def __init__(self) -> None:
        """No check made yet."""
        self.bad: list[tuple[str, object]] = []
        self.fields: int = 0

    def keys(self, obj: object, shape: str) -> dict[str, object]:
        """Obj as an object, its key set checked against SHAPES[shape]."""
        d = cast("dict[str, object]", obj)
        self.fields += len(d)
        if set(d) != SHAPES[shape]:
            self.bad.append((shape, sorted(set(d) ^ SHAPES[shape])))
        return d

    def enum(self, value: object, allowed: tuple[object, ...], what: str) -> None:
        """Value is one of allowed."""
        self.fields += 1
        if value not in allowed:
            self.bad.append((what, value))

    def items(self, items: object) -> None:
        """Each waiting or attention item."""
        for i in cast("list[object]", items):
            d = self.keys(i, "item")
            self.enum(d["kind"], dsp_monitor.ATTENTION, "item.kind")
            self.enum(d["severity"], ("red", "amber", None), "item.severity")

    def run(self, obj: object) -> dict[str, object]:
        """A RunDetail and every object in it."""
        from dsp_route import record

        d = self.keys(obj, "run")
        self.enum(d["state"], dsp_monitor.RUN_STATES, "run.state")
        self.enum(d["recording"], dsp_monitor.RECORDING, "run.recording")
        for s in cast("list[object]", d["sessions"]):
            ses = self.keys(s, "session")
            self.enum(ses["recording"], dsp_monitor.RECORDING, "session.recording")
        git = self.keys(d["git"], "git")
        self.enum(git["state"], dsp_monitor.GIT_STATES, "git.state")
        for lane in cast("dict[str, object]", d["lanes"]).values():
            column = self.keys(lane, "lane")["column"]
            self.enum(column, dsp_monitor.BOARD_COLUMNS, "lane.column")
        _ = self.keys(d["summary"], "summary")
        if d["budget"] is not None:
            _ = self.keys(d["budget"], "budget")
        for a in cast("list[object]", d["agents"]):
            agent = self.keys(a, "agent")
            self.enum(agent["mode"], (*record.AGENT_MODES, None), "agent.mode")
            self.enum(agent["state"], record.AGENT_STATES, "agent.state")
        self.items(d["waiting"])
        self.items(d["attention"])
        return d

    def state(self, obj: object) -> None:
        """A /api/state answer and every object in it."""
        d = self.keys(obj, "state")
        _ = self.keys(d["monitor"], "monitor")
        _ = self.keys(d["counts"], "counts")
        self.items(d["waiting"])
        self.items(d["attention"])
        for group in ("routes", "idle"):
            for r in cast("list[object]", d[group]):
                route = self.keys(r, "route")
                self.enum(route["status"], dsp_monitor.ROUTE_STATUS, "route.status")
                _ = self.run(route["run"])
        for e in cast("list[object]", d["ended"]):
            for x in cast("list[object]", self.keys(e, "ended")["runs"]):
                rs = self.keys(x, "run_summary")
                self.enum(rs["recording"], dsp_monitor.RECORDING, "summary.recording")
        for e in cast("list[object]", d["errors"]):
            _ = self.keys(e, "error")


class Derived(support.MonitorSandbox):
    """What the API derives for the page: board, summary, budget, ended runs, shape."""

    def machine(self) -> tuple[support.Machine, Path]:
        """This test's own machine, and its own directory for the shim and probe."""
        d = self.T / self._testMethodName
        return support.build_machine(d), d

    def settled(self, mon: support.Monitor, key: str) -> dict[str, object]:
        """/api/state once route key's live run has a report and fresh git."""

        def ready(s: dict[str, object]) -> bool:
            run = run_of(s, key)
            git = cast("dict[str, object]", run.get("git") or {})
            return bool(run) and run["report"] is not None and git["state"] == "fresh"

        return mon.wait(ready, timeout=60)

    def responses(self, mon: support.Monitor) -> dict[str, object]:
        """Every answer of the API: /api/state, /api/ping and /api/run of each run."""
        state = mon.state()
        out: dict[str, object] = {"/api/state": state}
        code, _, body = mon.get("/api/ping")
        out["/api/ping"] = json.loads(body) if code == HTTPStatus.OK else None
        keys = [str(r["key"]) for r in live_runs(state)]
        for r in cast("list[dict[str, object]]", state["ended"]):
            keys += [str(x["key"]) for x in cast("list[dict[str, object]]", r["runs"])]
        for k in keys:
            code, _, body = mon.get(f"/api/run?key={k}")
            out[k] = json.loads(body) if code == HTTPStatus.OK else None
        return out

    def test_board_mapping(self) -> None:
        """Every report lane state on route-a's board, as §4.7's table maps it."""
        from dsp_route import report

        m, _ = self.machine()
        mon = self.monitor_on(m, consts=QUICK)
        run = run_of(self.settled(mon, m.live_route_key), m.live_route_key)
        rep = cast("dict[str, object]", run["report"])
        lanes = cast("list[dict[str, object]]", rep["lanes"])
        waves = cast("dict[str, dict[str, object]]", rep["waves"])
        board = cast("dict[str, dict[str, object]]", run["lanes"])
        merged = {x["plan"] for x in lanes if x["state"] == "merged"}
        seen: set[tuple[str, bool | None]] = set()
        bad: list[object] = []
        for state in report.LANE_STATES:
            for lane in (x for x in lanes if x["state"] == state):
                needs = cast("list[str]", waves[str(lane["plan"])]["waits_for"])
                row = (state, set(needs) <= merged if state == "queued" else None)
                seen.add(row)
                got = board.get(str(lane["id"]), {})
                if (got.get("column"), got.get("gating")) != SPEC_BOARD[row]:
                    bad.append((lane["id"], row, got))
        self.ok(
            f"{len(seen)} of the table's rows on the board", seen == set(SPEC_BOARD)
        )
        self.ok(f"{len(lanes)} lanes, each in its row's column", lanes and not bad, bad)
        self.ok("one board entry per lane", len(board) == len(lanes), board)
        want = ("queued", "running", "ready", "merged", "blocked", "failed")
        self.ok("BOARD_COLUMNS in display order", want == dsp_monitor.BOARD_COLUMNS)
        summary = run["summary"]
        expect = {
            "stage": "exec",
            "waves_merged": 0,
            "waves_total": 2,
            "lanes_merged": 1,
            "lanes_total": 8,
            "agents_running": 1,
        }
        self.ok("route-a's summary", summary == expect, summary)

    def test_ended_runs_show_what_was_kept(self) -> None:
        """route-e: no git, current files on its newest run, rev follows the files."""
        m, d = self.machine()
        e = m.routes["route-e"]
        kept = m.put(e.plan / "lanes/p1-01-x-checkpoint.md", f"Final SHA: {'0' * 40}\n")
        _, log = self.git_shim(d / "shim")
        probe = d / "probe.jsonl"
        consts = {**QUICK, "FREE_IDLE_S": 1}
        mon = self.monitor_on(m, consts=consts, probe=probe, path_prefix=[d / "shim"])

        def collects() -> int:
            return sum(
                x["what"] == "collect" and x["planning_dir"] == str(e.plan)
                for x in probed(probe)
            )

        def newest(s: dict[str, object]) -> dict[str, object]:
            runs = ended_of(s, e.key)
            return runs[0] if runs else {}

        def after(n: int) -> dict[str, object]:
            """/api/state once route-e had n more refreshes."""
            want = collects() + n
            return mon.wait(lambda _: collects() >= want, timeout=30)

        s = mon.wait(lambda s: newest(s).get("has_report") is True, timeout=30)
        s = after(3)
        spawns = [x for x in log.read_text().splitlines() if str(e.repo) in x]
        self.ok(f"{collects()} refreshes of route-e, {len(spawns)} git", not spawns)
        runs = ended_of(s, e.key)
        self.ok(f"{len(runs)} ended runs", len(runs) == len(["new", "old"]), runs)
        new, old = (str(r["key"]) for r in runs[:2])
        self.ok("the newest is route-e's own run", new == e.run_key(), runs)
        detail: dict[str, dict[str, object]] = {}
        for k in (new, old):
            code, _, body = mon.get(f"/api/run?key={k}")
            self.ok(f"/api/run {k[-6:]}: {code}", code == HTTPStatus.OK)
            detail[k] = cast("dict[str, object]", json.loads(body)["run"])
        mtime = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(kept.stat().st_mtime))
        n = detail[new]
        self.ok("newest: a report", n["report"] is not None)
        self.ok("newest: current files", n["current_files"] is True, n["current_files"])
        self.ok("newest: as of its file", n["files_as_of"] == mtime, n["files_as_of"])
        git = cast("dict[str, object]", n["git"])
        self.ok("newest: git not tracked", git["state"] == "not_tracked", git)
        o = detail[old]
        self.ok("older: no report", o["report"] is None and not o["current_files"])
        error = str(o["report_error"])
        self.ok(f"older, seen only as previous: {error!r}", "args" in error)
        self.ok("older: no budget", o["budget"] is None)
        rev = newest(s)["rev"]
        s = after(2)
        self.ok("rev unchanged over two refreshes", newest(s)["rev"] == rev, rev)
        support.Sandbox.touch(kept, -3600)
        s = mon.wait(lambda s: newest(s).get("rev") not in {rev, None}, timeout=30)
        touched = newest(s)["rev"]
        self.ok(f"rev {rev} -> {touched} after a touch", touched != rev)
        self.rm(m.registry / "events/s5.jsonl")
        s = mon.wait(lambda s: newest(s).get("rev") not in {touched, None}, timeout=30)
        gone = newest(s)["rev"]
        self.ok(f"rev {touched} -> {gone} after the log went", gone != touched)

    def shapes(self, answers: dict[str, object]) -> None:
        """Each answer's shapes, enums, version and keys."""
        from dsp_route import report

        shape = Shape()
        shape.state(answers["/api/state"])
        for path, body in answers.items():
            if path.startswith("/api/"):
                continue
            self.ok(f"/api/run {path[-6:]} answered", body is not None)
            r = shape.keys(body, "run_response")
            _ = shape.keys(r["route"], "route_ref")
            _ = shape.run(r["run"])
        self.ok(f"{shape.fields} fields of {len(answers)} answers", shape.fields)
        self.ok("every shape and enum as §4.7 says", not shape.bad, shape.bad)
        versions = {
            p: cast("dict[str, object]", b)["version"] for p, b in answers.items()
        }
        bad_v = {p: v for p, v in versions.items() if v != dsp_monitor.API_VERSION}
        self.ok(f"{len(versions)} versions, all API_VERSION", not bad_v, bad_v)
        flags = sorted(set(dsp_monitor.ATTENTION_FLAGS) - set(report.FLAG_KINDS))
        self.ok("every ATTENTION_FLAGS kind is a report flag", not flags, flags)
        keys = [str(o["key"]) for o in dicts(list(answers.values())) if "key" in o]
        bad_k = [k for k in keys if not re.fullmatch(r"[0-9A-Za-z_-]+", k)]
        self.ok(f"{len(keys)} keys, all [0-9A-Za-z_-]+", keys and not bad_k, bad_k)

    def test_api_shape_and_enums(self) -> None:
        """Exact shapes, owners' enums, safe keys; HOME as ~, no planning file text."""
        from dsp_route import report

        m, _ = self.machine()
        a = m.routes["route-a"]
        _ = self.git("-C", a.repo, "worktree", "add", "-q", m.home / "wt-h", "p1-04-x")
        entry = m.registry / "s1.json"
        data = cast("dict[str, object]", json.loads(entry.read_text()))
        data["skill_digests"] = {"SKILL.md": SKILL_DIGEST}
        _ = m.put(entry, json.dumps(data) + "\n")
        mon = self.monitor_on(m, consts=QUICK)
        _ = self.settled(mon, a.key)
        answers = self.responses(mon)
        state = cast("dict[str, object]", answers["/api/state"])
        self.shapes(answers)
        # the report as collected, before the API copy
        args = common.checked(common.route_args, {"args": a.args})
        if args is None:
            self.fail("route-a's args do not parse")
        full = report.collect(args, use_git=False, write_cache=False)
        if full is None:
            self.fail("route-a gave no report")
        lasts = {f["last_line"] for f in full["files"] if f["last_line"]}
        found = strings(list(answers.values()))
        home = [x for x in found if str(m.home) in x]
        lines = [x for x in found for t in lasts if t in x]
        digest = [x for x in found if SKILL_DIGEST in x or x == "skill_digests"]
        self.ok(f"{len(found)} strings: none holds HOME", found and not home, home[:5])
        self.ok(f"{len(lasts)} last lines: none sent", lasts and not lines, lines[:5])
        self.ok("no skill digest sent", not digest, digest)
        run = run_of(state, a.key)
        rep = cast("dict[str, object]", run["report"])
        files = cast("list[dict[str, object]]", rep["files"])
        rflags = cast("list[dict[str, object]]", rep["flags"])
        kept = [k for k in ("extra",) if k in rep]
        kept += [
            f"files[{i}].last_line" for i, f in enumerate(files) if "last_line" in f
        ]
        kept += [f"flags[{i}].line" for i, f in enumerate(rflags) if "line" in f]
        self.ok(
            f"{len(files)} files, {len(rflags)} flags: no text",
            files and not kept,
            kept,
        )
        decisions = cast("dict[str, object]", rep["decisions"])
        same = (
            decisions["index"] == full["decisions"]["index"]
            and rep["lane_files"] == full["lane_files"]
        )
        self.ok("decisions.index and lane_files pass through", same)
        git = cast("dict[str, object]", rep["git"])
        trees = cast("dict[str, dict[str, object]]", git["lanes"])
        paths = [
            str(cast("dict[str, object]", t["worktree"])["path"])
            for t in trees.values()
            if t["worktree"] is not None
        ]
        tilde = [rep["planning_dir"], git["repo"]]
        self.ok(
            f"planning dir and repo under ~/: {tilde}",
            all(str(x).startswith("~/") for x in tilde),
        )
        self.ok(f"a worktree under ~/: {paths}", any(p.startswith("~/") for p in paths))

    def test_budget_recorded_never_spend(self) -> None:
        """route-a's budget is its last record; no answer names spend."""
        # not the test's name for its directory: the paths sent hold it
        m = support.build_machine(self.T / "budget")
        a = m.routes["route-a"]
        mon = self.monitor_on(m, consts=QUICK)
        state = self.settled(mon, a.key)
        recorded = common.budgets(a.plan, {}, "1")
        self.ok(f"{len(recorded)} budget records", recorded)
        last = recorded[-1]
        want = {
            "label": last["label"],
            "estimate": last["estimate"],
            "groups": last.get("groups"),
            "at": last["at"],
        }
        got = run_of(state, a.key)["budget"]
        self.ok("route-a's budget is the last record", got == want, got)
        answers = self.responses(mon)
        found = strings(list(answers.values()))
        spend = [x for x in found if "spend" in x.lower()]
        self.ok(
            f"{len(found)} keys and values: none says spend", found and not spend, spend
        )


# each route's commits in the interference test, and the commits after which a hook
# pair runs mid-loop
COMMITS = 60
MID_PAIRS = (20, 40)
# the report header's minute: the only clock reading a hook's output holds
MINUTE = re.compile(r"\d{4}-\d\d-\d\d \d\d:\d\d")


def tree_stat(*roots: Path) -> dict[str, tuple[int, int]]:
    """(size, mtime ns) of every file and directory under roots, by path."""
    out: dict[str, tuple[int, int]] = {}
    for root in roots:
        for p in [root, *root.rglob("*")]:
            with contextlib.suppress(OSError):
                st = p.lstat()
                out[str(p)] = (st.st_size, st.st_mtime_ns)
    return out


def index_locks(m: support.Machine) -> list[Path]:
    """Where git would take an index lock in m's repositories and their worktrees."""
    tops = [r.repo / ".git" for r in m.routes.values()]
    return [
        lock
        for top in tops
        for lock in [top / "index.lock", *top.glob("worktrees/*/index.lock")]
    ]


@dataclasses.dataclass
class LockWatch:
    """A thread that looks for an index lock every 10 ms until stopped."""

    paths: list[Path]
    seen: list[str] = dataclasses.field(default_factory=list)
    looks: int = 0
    done: threading.Event = dataclasses.field(default_factory=threading.Event)

    def run(self) -> None:
        """Look until done is set."""
        while not self.done.wait(0.01):
            self.looks += 1
            self.seen += [str(p) for p in self.paths if p.exists()]


class Isolation(support.MonitorSandbox):
    """The monitor writes nothing and never gets in a session's way (§1.3 rule 1)."""

    def lane_machine(
        self, d: Path
    ) -> tuple[support.Machine, dict[str, tuple[support.FixtureRoute, Path]]]:
        """Five routes, each with an open lane whose worktree is at its Final SHA.

        Each lane's branch is named after its checkpoint id; session s<n> holds the
        n-th route. Returns the machine, and each route and lane worktree by session.
        """
        m = support.Machine(d)
        out: dict[str, tuple[support.FixtureRoute, Path]] = {}
        names = ("route-a", "route-b", "route-c", "route-d", "route-e")
        for n, name in enumerate(names, 1):
            r = m.fixture_route(name)
            wt = d / f"wt-{name}"
            _ = self.git("-C", r.repo, "worktree", "add", "-q", "-b", "p1-01-x", wt)
            _ = self.write(wt / "f.txt", "start\n")
            _ = self.git("-C", wt, "add", "f.txt")
            _ = self.git("-C", wt, "commit", "-q", "-m", "start")
            sha = self.rev(wt)
            _ = m.put(r.plan / "lanes/p1-01-x-checkpoint.md", f"Final SHA: {sha}\n")
            _ = m.put(
                r.plan / "plans/p1-00-index.md",
                "# Phase 1 plans\n\n| Plan | Wave | Depends on |\n|---|---|---|\n"
                "| p1-01-x | 1 | — |\n",
            )
            _ = m.put_entry(f"s{n}", r)
            out[f"s{n}"] = (r, wt)
        return m, out

    def pair(
        self, m: support.Machine, session: str, r: support.FixtureRoute
    ) -> tuple[list[int], list[str]]:
        """Two concurrent PostToolUse hooks of session: exit codes, sorted outputs.

        Its throttle claims and every `.last` of its route go first, so each pair
        starts from the same files; the header's minute reads `<time>`.
        """
        for f in m.registry.glob(f"{session}.*.checked"):
            f.unlink(missing_ok=True)
        for f in r.marker.parent.glob(f"{r.marker.stem}*.last"):
            f.unlink(missing_ok=True)
        event = support.ev("PostToolUse", session, '"tool_name":"Bash"') + "\n"

        def hook() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [PY, str(support.RS), "--hook"],
                input=event,
                env=m.env,
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )

        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            done = [f.result() for f in [pool.submit(hook), pool.submit(hook)]]
        outs = sorted(MINUTE.sub("<time>", p.stdout) for p in done)
        return [p.returncode for p in done], outs

    def commit_loop(
        self, m: support.Machine, r: support.FixtureRoute, wt: Path, session: str
    ) -> tuple[list[tuple[list[int], list[str]]], list[str]]:
        """COMMITS commits in wt, the lane's Final SHA following HEAD after each.

        Returns the hook pairs run before, during (MID_PAIRS) and after the loop, and
        the output of each commit that failed.
        """
        pairs = [self.pair(m, session, r)]
        failed: list[str] = []
        for n in range(1, COMMITS + 1):
            _ = self.write(wt / "f.txt", f"{n}\n")
            c = self.git("-C", wt, "commit", "-q", "-am", f"c{n}", check=False)
            if c.code != 0:
                failed.append(c.out)
                continue
            # each git refresh then checks the worktree being committed to
            sha = self.rev(wt)
            _ = self.write(
                r.plan / "lanes/p1-01-x-checkpoint.md", f"Final SHA: {sha}\n"
            )
            if n in MID_PAIRS:
                pairs.append(self.pair(m, session, r))
        pairs.append(self.pair(m, session, r))
        return pairs, failed

    def test_monitor_writes_nothing(self) -> None:
        """A poll cycle, a git refresh of every live route, every run: no write."""
        d = self.T / self._testMethodName
        m = support.build_machine(d)
        a, wt = m.routes["route-a"], d / "wt-a"
        _ = self.write(wt / "f.txt", "one\n")
        _ = self.git("-C", wt, "add", "f.txt")
        _ = self.git("-C", wt, "commit", "-q", "-m", "f")
        sha = self.rev(wt)
        _ = m.put(a.plan / "lanes/p1-05-x-checkpoint.md", f"Final SHA: {sha}\n")
        # unchanged in HEAD, so only a stat refresh would rewrite the index
        self.stat_dirty(wt / "f.txt")
        roots = [m.home, wt]
        roots += [p for r in m.routes.values() for p in (r.plan, r.repo / ".git")]
        before, index = tree_stat(*roots), self.index_state(wt)
        _, log = self.git_shim(d / "shim")
        watch = LockWatch(index_locks(m))
        watcher = threading.Thread(target=watch.run)
        watcher.start()
        try:
            mon = self.monitor_on(m, consts=QUICK, path_prefix=[d / "shim"])

            def refreshed(s: dict[str, object]) -> bool:
                runs = live_runs(s)
                git = [cast("dict[str, object]", r["git"])["state"] for r in runs]
                lines = log.read_text().splitlines() if log.exists() else []
                status = [x for x in lines if " status " in x]
                done = all(g in {"fresh", "slow", "not_tracked"} for g in git)
                return bool(runs) and done and any(str(wt) in x for x in status)

            state = mon.wait(refreshed, timeout=60)
            keys = [str(r["key"]) for r in live_runs(state)]
            for r in cast("list[dict[str, object]]", state["ended"]):
                runs = cast("list[dict[str, object]]", r["runs"])
                keys += [str(x["key"]) for x in runs]
            codes = [mon.get(f"/api/run?key={k}")[0] for k in keys]
            self.ok(f"{len(codes)} runs answered", codes and set(codes) == {200}, codes)
            _ = mon.stop()
        finally:
            watch.done.set()
            watcher.join()
        after = tree_stat(*roots)
        paths = before.keys() | after.keys()
        changed = sorted(p for p in paths if before.get(p) != after.get(p))
        msg = f"{len(before)} paths scanned, {len(changed)} changed"
        self.ok(msg, before and not changed, changed[:20])
        same = self.index_state(wt) == index
        self.ok("the stat-dirty worktree's index unchanged", same)
        msg = f"{watch.looks} looks for an index lock: none seen"
        self.ok(msg, watch.looks and not watch.seen, watch.seen[:5])

    def test_no_interference_with_sessions(self) -> None:
        """Commits and hook pairs on five routes under a polled monitor: unaffected."""
        t_start = time.monotonic()
        d = self.T / self._testMethodName
        m, lanes = self.lane_machine(d)
        base0 = {s: self.pair(m, s, r) for s, (r, _) in lanes.items()}
        _, log = self.git_shim(d / "shim")
        mon = self.monitor_on(m, consts=QUICK, path_prefix=[d / "shim"])

        def fresh(s: dict[str, object]) -> bool:
            git = [cast("dict[str, object]", r["git"])["state"] for r in live_runs(s)]
            return len(git) == len(lanes) and set(git) == {"fresh"}

        _ = mon.wait(fresh, timeout=60)
        stop = threading.Event()

        def poll() -> None:
            while not stop.wait(0.2):
                _ = mon.get("/api/state")

        pollers = [threading.Thread(target=poll) for _ in range(3)]
        for t in pollers:
            t.start()
        t0 = time.time_ns()
        try:
            with concurrent.futures.ThreadPoolExecutor(len(lanes)) as pool:
                futures = {
                    s: pool.submit(self.commit_loop, m, r, wt, s)
                    for s, (r, wt) in lanes.items()
                }
                done = {s: f.result() for s, f in futures.items()}
        finally:
            t1 = time.time_ns()
            stop.set()
            for t in pollers:
                t.join()
            _ = mon.stop()
        base60 = {s: self.pair(m, s, r) for s, (r, _) in lanes.items()}
        stamps = [x.partition(" ") for x in log.read_text().splitlines()]
        status = sum(
            t0 <= int(t) <= t1 and " status " in f" {a} " for t, _, a in stamps
        )
        failed = [o for _, f in done.values() for o in f]
        locks = [o for o in failed if "index.lock" in o]
        commits = COMMITS * len(lanes) - len(failed)
        msg = f"{commits} commits, {len(locks)} failed on index.lock"
        self.ok(msg, commits and not locks, locks[:3])
        self.ok(f"{len(failed)} commits failed at all", not failed, failed[:3])
        self.ok(f"{status} monitor git status spawns during the loop", status)
        runs = [p for pairs, _ in done.values() for p in pairs]
        runs += [*base0.values(), *base60.values()]
        hooks = [c for codes, _ in runs for c in codes]
        self.ok(f"{len(hooks)} hooks, every one exit 0", hooks and set(hooks) == {0})
        unlike = [
            s
            for s, (pairs, _) in done.items()
            if pairs[0][1] != base0[s][1] or pairs[-1][1] != base60[s][1]
        ]
        msg = f"{2 * len(lanes)} pairs, each as its pair with no monitor"
        self.ok(msg, not unlike, unlike)
        took = time.monotonic() - t_start
        self.ok(f"took {took:.1f} s", took > 0)
