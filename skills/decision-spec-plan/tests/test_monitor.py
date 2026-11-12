# SPDX-License-Identifier: MIT
"""The route monitor: `dsp_monitor.py`, its page skeleton and the names it shares."""

import base64
import contextlib
import dataclasses
import hashlib
import ipaddress
import json
import os
import re
import shlex
import socket
import time
import unittest.mock
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
