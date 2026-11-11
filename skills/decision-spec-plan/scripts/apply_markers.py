#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Insert supersede markers into a round's files from the markers agent's JSON list.

The agent judges what each ruling overrides; this script does the inserting. Each entry
is {"file": "D3-x.md", "anchor": "<verbatim text unique in that file>", "ruling": "A7",
"clause": "<what now holds>"}. The marker goes on its own line directly above the first
line of the block holding the anchor -- the paragraph, bullet, table row or code block:

    > **SUPERSEDED BY A7** — <clause>.

and every marked file gets `> **Read 00-arbiter.md first.**` under its title, once. Text
is never deleted or rewritten, and every line keeps its line ending (CRLF stays CRLF).
An anchor that is missing, or found more than once, is refused and named; a marker
already above its block is skipped, so a fixed list can be re-run. Each file is written
once.

Usage:
    apply_markers.py <decisions-dir> <markers.json> [--check]

--check reports without writing. Exit 0 when every entry applied or was already present,
1 when any was refused, 2 when the list, an entry of it (each needs string file, anchor,
ruling and clause) or a named file cannot be read; a malformed list writes nothing.
"""

import argparse
import json
import pathlib
import re
import sys
from typing import TypedDict, cast

HEADER = "> **Read 00-arbiter.md first.**"
KEYS = ("file", "anchor", "ruling", "clause")
BLOCK_START = re.compile(r"^\s*(\||#|>|[-*+]\s|\d+[.)]\s)")
FENCE = re.compile(r"^\s*(```|~~~)")
MARK = "> **SUPERSEDED BY"


class Entry(TypedDict):
    """One entry of the markers list."""

    file: str
    anchor: str
    ruling: str
    clause: str


class _Args(argparse.Namespace):
    """The parsed command line; argparse keeps these defaults, so they match its own."""

    decisions_dir: str = ""
    markers_json: str = ""
    check: bool = False


def marker(entry: Entry) -> str:
    """Return the supersede marker line for an entry."""
    clause = entry["clause"].strip()
    closers = "\"')]`*”\N{RIGHT SINGLE QUOTATION MARK}»"
    end = "" if clause.rstrip(closers).endswith((".", "!", "?")) else "."
    return f"> **SUPERSEDED BY {entry['ruling'].strip()}** — {clause}{end}"


def block_start(lines: list[str], i: int) -> int:
    """Return the first line of the block that line i belongs to.

    The paragraph, bullet or table row, or the opening fence of the code block holding
    it. A heading, table row or quote line above (an earlier marker is a quote line)
    ends the walk.
    """
    fence = None
    for k in range(i):
        if FENCE.match(lines[k]):
            fence = k if fence is None else None
    if fence is not None:
        return fence
    while i > 0 and not BLOCK_START.match(lines[i]) and lines[i - 1].strip():
        if re.match(r"^\s*(#|\||>)", lines[i - 1]):
            break
        i -= 1
    return i


def apply(
    lines: list[str], entries: list[Entry]
) -> tuple[list[str], list[int], list[tuple[Entry, str]]]:
    """Insert the entries' markers into a file's lines.

    Takes the file's lines without their endings. Returns the new lines, the original
    line each new line takes its line ending from, and one (entry, outcome) per entry:
    applied, present, missing or ambiguous (n).
    """
    # Marker lines are blanked for the search, so a clause that repeats its anchor does
    # not make a re-run ambiguous.
    text = "\n".join(" " * len(x) if x.startswith(MARK) else x for x in lines)
    results: list[tuple[Entry, str]] = []
    inserts: dict[int, list[str]] = {}
    for e in entries:
        n = text.count(e["anchor"])
        if n != 1:
            results.append((e, "missing" if n == 0 else f"ambiguous ({n})"))
            continue
        at = text[: text.index(e["anchor"])].count("\n")
        start = block_start(lines, at)
        line = marker(e)
        above = inserts.get(start, [])
        k = start - 1
        while k >= 0 and lines[k].startswith(MARK):
            above = [lines[k], *above]
            k -= 1
        if line in above:
            results.append((e, "present"))
            continue
        inserts.setdefault(start, []).append(line)
        results.append((e, "applied"))
    out: list[str] = []
    src: list[int] = []
    for i, x in enumerate(lines):
        for m in inserts.get(i, []):
            out.append(m)
            src.append(i)
        out.append(x)
        src.append(i)
    if any(r == "applied" for _, r in results) and HEADER not in lines:
        at = 1 if lines and lines[0].startswith("# ") else 0
        out.insert(at, HEADER)
        src.insert(at, 0)
    return out, src, results


def as_entry(value: object) -> Entry | None:
    """Return value as an entry, or None when it lacks a string field."""
    d = cast("dict[str, object]", value) if isinstance(value, dict) else {}
    file, anchor, ruling, clause = (d.get(k) for k in KEYS)
    if not (
        isinstance(file, str)
        and isinstance(anchor, str)
        and isinstance(ruling, str)
        and isinstance(clause, str)
    ):
        return None
    return Entry(file=file, anchor=anchor, ruling=ruling, clause=clause)


def read_entries(markers_json: str) -> list[Entry] | None:
    """Return the markers list, or None (the reason printed) when it is malformed."""
    try:
        parsed = cast("object", json.loads(pathlib.Path(markers_json).read_text()))
    except (OSError, ValueError) as err:
        print(f"cannot read {markers_json}: {err}")
        return None
    if not isinstance(parsed, list):
        print(f"cannot read {markers_json}: not a list of entries")
        return None
    entries: list[Entry] = []
    for n, value in enumerate(cast("list[object]", parsed), 1):
        e = as_entry(value)
        if e is None:
            print(
                f"cannot read {markers_json}: entry {n} needs string "
                f"{', '.join(KEYS)}: {value!r}"
            )
            return None
        entries.append(e)
    return entries


def split_lines(raw: str) -> tuple[str, list[str], list[str]]:
    """Return a file's BOM, its lines without their endings, and each line's ending.

    Each line keeps its own ending; an inserted line takes the ending of the line it
    goes above, and the last line's when that one has none. A BOM stays first.
    """
    bom = "﻿" if raw.startswith("﻿") else ""
    parts = raw[len(bom) :].split("\n")
    last = len(parts) - 1
    lines = [
        x[:-1] if k < last and x.endswith("\r") else x for k, x in enumerate(parts)
    ]
    eol = [
        "\r\n" if k < last and x.endswith("\r") else "\n" for k, x in enumerate(parts)
    ]
    if last:
        eol[last] = eol[last - 1]
    return bom, lines, eol


def main() -> int:
    """Insert the listed markers and print a row per file; the exit status."""
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    _ = ap.add_argument("decisions_dir")
    _ = ap.add_argument("markers_json")
    _ = ap.add_argument("--check", action="store_true")
    a = ap.parse_args(namespace=_Args())
    base = pathlib.Path(a.decisions_dir)
    entries = read_entries(a.markers_json)
    if entries is None:
        return 2
    by_file: dict[str, list[Entry]] = {}
    for e in entries:
        by_file.setdefault(e["file"], []).append(e)
    refused = 0
    print(f"{'file':<34} {'listed':>6} {'applied':>7} {'present':>7} {'refused':>7}")
    for name, group in by_file.items():
        path = base / name
        try:
            # newline="": read and write the file's own line endings, never rewrite
            # them.
            with path.open(newline="") as f:
                raw = f.read()
        except OSError as err:
            print(f"cannot read {path}: {err}")
            return 2
        bom, lines, eol = split_lines(raw)
        out, src, results = apply(lines, group)
        new = (
            bom
            + "".join(x + eol[i] for x, i in zip(out[:-1], src[:-1], strict=True))
            + out[-1]
        )
        if new != raw and not a.check:
            with path.open("w", newline="") as f:
                _ = f.write(new)
        count = {
            k: sum(1 for _, r in results if r == k) for k in ("applied", "present")
        }
        bad = [(e, r) for e, r in results if r not in count]
        refused += len(bad)
        print(
            f"{name:<34} {len(group):>6} {count['applied']:>7} {count['present']:>7} "
            f"{len(bad):>7}"
        )
        for e, r in bad:
            print(f"  REFUSED {r}: {e['ruling']} anchor {e['anchor'][:70]!r}")
    total = len(entries)
    print(
        f"\n{total} markers listed in {len(by_file)} files; {refused} refused"
        + (" (--check: nothing written)" if a.check else "")
    )
    return 1 if refused else 0


if __name__ == "__main__":
    sys.exit(main())
