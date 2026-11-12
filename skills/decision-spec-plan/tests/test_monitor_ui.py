# SPDX-License-Identifier: MIT
"""The monitor page, `dsp_monitor.html`, read as text.

T1 scans it for anything that could request a resource off its origin, T3 holds its
labels to the Python enums, and the literal scan proves its script compares no status
and no interval of the server's.
"""

import json
import math
import re
from typing import Final, NamedTuple, cast

import dsp_monitor
import support
from dsp_route import common

PAGE: Final = support.SCRIPTS / "dsp_monitor.html"
# the page's own polling numbers (§4.9), the one place they may appear (R95)
PAGE_NUMBERS: Final = {
    "poll_visible_ms": 5000,
    "poll_hidden_ms": 30000,
    "abort_ms": 10000,
    "backoff_ms": [5000, 10000, 20000, 30000],
    "finished_shown": 20,
}
ENUMS: Final = 12  # §4.9's twelve label enums
TIMES: Final = 12  # §4.6's interval and threshold names, at least
# the values only Python may compare against (AC-P1-4-37)
STATUS: Final = frozenset(
    dsp_monitor.BOARD_COLUMNS
    + dsp_monitor.ROUTE_STATUS
    + dsp_monitor.RECORDING
    + dsp_monitor.ATTENTION
)
SVG_NS: Final = "http://www.w3.org/2000/svg"
PLANTED_IMG: Final = '<img src="https://x.invalid/">'
PLANTED_HTML: Final = "el.innerHTML = s;"
PLANTED_STATUS: Final = "if (r.status === 'idle') {}\nif (a > 720000) {}\n"

_ATTRS = r"(?:xlink:href|formaction|srcset|poster|action|href|src|data)"
_Q = r"[\"']"


class Rule(NamedTuple):
    """One kind of sink: the region it is looked for in, and what admits a hit.

    Each allow pattern is matched at the hit; `once` names those that admit one hit.
    """

    region: str
    sink: re.Pattern[str]
    allow: tuple[tuple[str, re.Pattern[str]], ...] = ()


def _re(pattern: str, flags: re.RegexFlag = re.NOFLAG) -> re.Pattern[str]:
    return re.compile(pattern, flags)


# D6 §3 T1's sinks, by region; every hit no allow pattern admits is refused
RULES: Final = (
    Rule(
        "markup",
        _re(rf"(?<=\s){_ATTRS}\s*=", re.IGNORECASE),
        (
            ("hash link", _re(rf"href\s*=\s*{_Q}?#", re.IGNORECASE)),
            ("favicon", _re(rf"href\s*=\s*{_Q}?data:", re.IGNORECASE)),
        ),
    ),
    Rule(
        "style",
        _re(r"url\(|@import|@font-face", re.IGNORECASE),
        (("data url", _re(rf"url\(\s*{_Q}?data:", re.IGNORECASE)),),
    ),
    Rule(
        "script",
        _re(rf"\bsetAttribute\s*\(\s*{_Q}{_ATTRS}{_Q}"),
        (("hash link", _re(rf"setAttribute\s*\(\s*{_Q}href{_Q}\s*,\s*{_Q}#")),),
    ),
    Rule("script", _re(rf"\bsetAttributeNS\s*\([^,]*,\s*{_Q}{_ATTRS}{_Q}")),
    Rule("script", _re(rf"\.{_ATTRS}\b\s*=(?!=)")),
    Rule(
        "script",
        _re(r"\bfetch\s*\("),
        (("api fetch", _re(rf"fetch\s*\(\s*{_Q}/api/")),),
    ),
    Rule(
        "script",
        _re(
            r"XMLHttpRequest|WebSocket|EventSource|sendBeacon|\bimport\s*\("
            r"|importScripts|(?<!Shared)Worker\s*\(|SharedWorker|\bwindow\s*\.\s*open\b"
        ),
    ),
    Rule(
        "script",
        _re(
            r"\blocation\s*(?:\.\s*\w+\s*)?=(?!=)"
            r"|\blocation\s*\.\s*(?:assign|replace)\s*\(|\bhistory\s*\.\s*\w+\s*\("
        ),
    ),
    Rule(
        "script",
        _re(
            r"\bdocument\s*\.\s*write|innerHTML|outerHTML|insertAdjacentHTML"
            r"|\beval\s*\(|\bFunction\s*\("
        ),
    ),
    Rule("script", _re(rf"\bset(?:Timeout|Interval)\s*\(\s*{_Q}")),
)
# scheme literals over the whole file: `<scheme>://` and a protocol-relative `//host`
SCHEMES: Final = Rule(
    "file",
    _re(r"(?<![a-z0-9+.-])[a-z][a-z0-9+.-]*:(?=//)|(?<!:)//[a-z0-9]", re.IGNORECASE),
    (("svg namespace", _re(re.escape(SVG_NS) + r"(?![\w/.-])")),),
)
ONCE: Final = frozenset({"favicon", "svg namespace"})


class Scan(NamedTuple):
    """What T1 found in a page: its size, sinks and scheme literals, the verdicts."""

    bytes: int
    lines: int
    sinks: int
    schemes: int
    allowed: int
    refused: list[str]

    @property
    def summary(self) -> str:
        """The line AC-P1-4-30 prints."""
        return (
            f"scanned {self.bytes} B / {self.lines} lines: {self.sinks} sinks, "
            f"{self.schemes} scheme literals, {self.allowed} allowed, "
            f"{len(self.refused)} refused"
        )


def page_parts(text: str) -> tuple[str, str, str]:
    """The markup, the `<style>` body and the `<script>` body of a page.

    CR LF and CR become LF first, as a browser's HTML parser does. The page holds
    exactly one `<script` and one `<style`, and neither opening tag holds `src`.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    bodies: dict[str, str] = {}
    markup = text
    for tag in ("style", "script"):
        n = len(re.findall(rf"<{tag}\b", text, re.IGNORECASE))
        m = re.search(
            rf"<{tag}\b([^>]*)>(.*?)</{tag}\s*>", text, re.IGNORECASE | re.DOTALL
        )
        if n != 1 or m is None or "src" in m.group(1).lower():
            msg = f"wants one <{tag}> without src, has {n}: {m and m.group(1)!r}"
            raise AssertionError(msg)
        bodies[tag] = m.group(2)
        markup = markup.replace(m.group(2), "", 1)
    return markup, bodies["style"], bodies["script"]


def _block_re(name: str) -> re.Pattern[str]:
    return re.compile(rf"/\* dsp:{name} \*/(.*?)/\* /dsp:{name} \*/", re.DOTALL)


def json_block(script: str, name: str) -> object:
    """The JSON between `/* dsp:<name> */` and `/* /dsp:<name> */`."""
    m = _block_re(name).search(script)
    if m is None:
        msg = f"the script has no dsp:{name} block"
        raise AssertionError(msg)
    return cast("object", json.loads(m.group(1)))


def as_dict(value: object) -> dict[str, object]:
    """Value when it is a JSON object, else an empty one."""
    if isinstance(value, dict):
        return cast("dict[str, object]", value)
    return {}


def _hits(region: str, text: str, rule: Rule, used: set[str]) -> list[str | None]:
    """Each hit of rule in text: None when admitted, else what was refused."""
    out: list[str | None] = []
    for m in rule.sink.finditer(text):
        names = [n for n, p in rule.allow if p.match(text, m.start())]
        name = next((n for n in names if n not in ONCE or n not in used), None)
        if name is not None:
            used.add(name)
            out.append(None)
        else:
            out.append(f"{region}: {text[m.start() : m.start() + 60]!r}")
    return out


def outbound_scan(text: str) -> Scan:
    """T1 (AC-P1-4-30): every URL sink and scheme literal of a page, and its verdict."""
    markup, style, script = page_parts(text)
    regions = {"markup": markup, "style": style, "script": script}
    used: set[str] = set()
    sinks = [
        h
        for rule in RULES
        for h in _hits(rule.region, regions[rule.region], rule, used)
    ]
    schemes = _hits("file", text, SCHEMES, used)
    found = sinks + schemes
    return Scan(
        bytes=len(text.encode()),
        lines=len(text.splitlines()),
        sinks=len(sinks),
        schemes=len(schemes),
        allowed=found.count(None),
        refused=[h for h in found if h is not None],
    )


_ESC = re.compile(r"\\(u\{[0-9a-fA-F]+\}|u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|.)", re.DOTALL)
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}
_STRING = re.compile(r"'(?:[^'\\\n]|\\.)*'|\"(?:[^\"\\\n]|\\.)*\"")
_NUMBER = re.compile(
    r"(?<![\w$.])(?:\d[\d_]*(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?(?![\w$])"
)


def _unescape(m: re.Match[str]) -> str:
    e = m.group(1)
    if len(e) > 1 and e[0] in "ux":
        return chr(int(e.strip("ux{}"), 16))
    return _ESCAPES.get(e, e)


def script_literals(script: str) -> tuple[list[str], list[float]]:
    """The string and number literals of a script outside its two JSON blocks.

    It drops the `dsp:labels` and `dsp:page` blocks, then every `/* … */` comment,
    then reads quoted strings (escapes decoded), then numbers in what is left. The
    page uses no template literal (asserted: no backtick) and no regex literal, so
    this reading is exact.
    """
    if "`" in script:
        msg = "the script holds a backtick: template literals are not read"
        raise AssertionError(msg)
    for name in ("labels", "page"):
        script = _block_re(name).sub("", script)
    script = re.sub(r"/\*.*?\*/", " ", script, flags=re.DOTALL)
    quoted = cast("list[str]", _STRING.findall(script))
    strings = [_ESC.sub(_unescape, s[1:-1]) for s in quoted]
    rest = _STRING.sub(" ", script)
    numbers = [
        float(n.replace("_", "")) for n in cast("list[str]", _NUMBER.findall(rest))
    ]
    return strings, numbers


def times() -> dict[str, float]:
    """§4.6's intervals and thresholds: dsp_monitor's `*_S` numbers, ABSENT_RETRY_S."""
    names: dict[str, object] = {n: getattr(dsp_monitor, n) for n in dir(dsp_monitor)}
    out = {
        n: float(v)
        for n, v in names.items()
        if n.endswith("_S") and isinstance(v, int | float) and not isinstance(v, bool)
    }
    return {**out, "ABSENT_RETRY_S": common.ABSENT_RETRY_S}


def computed(script: str) -> tuple[list[str], int, int]:
    """AC-P1-4-37's findings in a script: status strings and §4.6 numbers it holds.

    Also the counts of string and number literals checked.
    """
    strings, numbers = script_literals(script)
    found = [f"string {s!r}" for s in strings if s in STATUS]
    for name, v in times().items():
        found += [
            f"number {n:g} = {name}"
            for n in numbers
            if math.isclose(n, v) or math.isclose(n, v * 1000)
        ]
    return found, len(strings), len(numbers)


def plant(text: str, before: str, planted: str) -> str:
    """Text with planted inserted before the first `before`."""
    i = text.index(before)
    return text[:i] + planted + text[i:]


def owners() -> dict[str, tuple[str, ...]]:
    """Each enum the labels block mirrors, and the tuple owning its values and order."""
    from dsp_route import record, report  # the hooks import them lazily (TID253)

    return {
        "stage": report.STAGES,
        "stage_state": report.STAGE_STATES,
        "lane": report.LANE_STATES,
        "gate": report.GATE_STATES,
        "agent_state": record.AGENT_STATES,
        "agent_mode": record.AGENT_MODES,
        "run_state": dsp_monitor.RUN_STATES,
        "route_status": dsp_monitor.ROUTE_STATUS,
        "recording": dsp_monitor.RECORDING,
        "attention": dsp_monitor.ATTENTION,
        "git_state": dsp_monitor.GIT_STATES,
        "board_column": dsp_monitor.BOARD_COLUMNS,
    }


class OutboundScan(support.Sandbox):
    """T1: the page holds no reference off its own origin (AC-P1-4-30)."""

    def test_static_outbound_scan(self) -> None:
        """The real page scans clean; a planted `<img src>` and `innerHTML` fail."""
        text = PAGE.read_text(encoding="utf-8")
        scan = outbound_scan(text)
        self.ok(
            scan.summary,
            scan.bytes > 0 and scan.sinks > 0 and not scan.refused,
            scan.refused,
        )
        for label, copy in (
            ("planted <img src>", plant(text, "</body>", PLANTED_IMG)),
            ("planted innerHTML", plant(text, "</script>", PLANTED_HTML)),
        ):
            got = outbound_scan(copy)
            self.ok(f"{label}: {got.summary}", got.refused, got)


class LabelMirror(support.Sandbox):
    """T3: the labels block mirrors the Python enums (AC-P1-4-32)."""

    def labels(self) -> dict[str, object]:
        """The page's `dsp:labels` block."""
        _, _, script = page_parts(PAGE.read_text(encoding="utf-8"))
        return as_dict(json_block(script, "labels"))

    def test_label_mirror(self) -> None:
        """Every enum value has a label with text and glyph, in the owner's order."""
        block = self.labels()
        enums = owners()
        want = {*enums, "copy"}
        self.ok(f"LABELS keys: {sorted(block)}", set(block) == want, sorted(want))
        n = 0
        for name, owner in enums.items():
            entries = as_dict(block.get(name))
            bad = [
                v
                for v in owner
                if not all(
                    isinstance(t, str) and t
                    for t in (as_dict(entries.get(v)).get(k) for k in ("text", "glyph"))
                )
            ]
            self.ok(
                f"{name}: {len(owner)} values, {len(entries)} labels",
                list(entries) == list(owner) and not bad,
                (list(entries), bad),
            )
            n += bool(entries)
        self.ok(f"{n} enums labelled (want {ENUMS})", n >= ENUMS)

    def test_copy_keys(self) -> None:
        """The script's `copy.<key>` names are exactly the keys `LABELS.copy` holds."""
        _, _, script = page_parts(PAGE.read_text(encoding="utf-8"))
        held = as_dict(self.labels().get("copy"))
        rest = _block_re("labels").sub("", script)
        used = set(re.findall(r"\bcopy\.([A-Za-z_]\w*)", rest))
        empty = [k for k, v in held.items() if not (isinstance(v, str) and v)]
        self.ok(
            f"copy: {len(used)} keys used, {len(held)} held",
            used and used == set(held) and not empty,
            (sorted(used ^ set(held)), empty),
        )


class NoComputation(support.Sandbox):
    """The script compares no status and no interval of the server's (AC-P1-4-37)."""

    def test_no_status_literal(self) -> None:
        """No status string and no §4.6 number, in seconds or ms, outside the blocks."""
        text = PAGE.read_text(encoding="utf-8")
        names = sorted(times())
        self.ok(f"{len(names)} interval names: {names}", len(names) >= TIMES)
        _, _, script = page_parts(text)
        found, n_str, n_num = computed(script)
        self.ok(
            f"{n_str} strings against {len(STATUS)} status values, {n_num} numbers "
            f"against {len(names)} intervals: {len(found)} found",
            n_str and n_num and not found,
            found,
        )
        _, _, planted = page_parts(plant(text, "</script>", PLANTED_STATUS))
        got, _, _ = computed(planted)
        for want in ("string 'idle'", "number 720000 = STUCK_S"):
            self.ok(f"planted copy: {want}", want in got, got)

    def test_page_numbers(self) -> None:
        """The `dsp:page` block holds exactly the page's §4.9 numbers."""
        _, _, script = page_parts(PAGE.read_text(encoding="utf-8"))
        got = json_block(script, "page")
        self.ok(f"dsp:page: {got}", got == PAGE_NUMBERS, PAGE_NUMBERS)
