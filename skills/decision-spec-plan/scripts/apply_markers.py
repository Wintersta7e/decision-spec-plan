#!/usr/bin/env python3
"""Insert supersede markers into a decision round's files from a JSON list the markers agent wrote.

The agent judges what each ruling overrides; this script does the inserting. Each entry is
{"file": "D3-x.md", "anchor": "<verbatim text unique in that file>", "ruling": "A7",
"clause": "<what now holds>"}. The marker goes on its own line directly above the first line of
the block holding the anchor -- the paragraph, bullet or table row:

    > **SUPERSEDED BY A7** — <clause>.

and every marked file gets `> **Read 00-arbiter.md first.**` under its title, once. Text is never
deleted or rewritten. An anchor that is missing, or found more than once, is refused and named; a
marker already above its block is skipped, so a fixed list can be re-run. Each file is written once.

Usage:
    apply_markers.py <decisions-dir> <markers.json> [--check]

--check reports without writing. Exit 0 when every entry applied or was already present, 1 when any
was refused, 2 when the list or a named file cannot be read.
"""

import argparse
import json
import pathlib
import re
import sys

HEADER = "> **Read 00-arbiter.md first.**"
BLOCK_START = re.compile(r"^\s*(\||#|>|[-*+]\s|\d+[.)]\s)")


def marker(entry):
    clause = entry["clause"].strip()
    end = "" if clause.rstrip("\"')]`*”’»").endswith((".", "!", "?")) else "."
    return f"> **SUPERSEDED BY {entry['ruling'].strip()}** — {clause}{end}"


def block_start(lines, i):
    """The first line of the paragraph, bullet or table row that line i belongs to. A heading,
    table row or quote line above (an earlier marker is a quote line) ends the walk."""
    while i > 0 and not BLOCK_START.match(lines[i]) and lines[i - 1].strip():
        if re.match(r"^\s*(#|\||>)", lines[i - 1]):
            break
        i -= 1
    return i


def apply(text, entries):
    """Returns the new text and one (entry, outcome) per entry: applied, present, missing or
    ambiguous (n)."""
    results, inserts = [], {}
    for e in entries:
        n = text.count(e["anchor"])
        if n != 1:
            results.append((e, "missing" if n == 0 else f"ambiguous ({n})"))
            continue
        lines = text.split("\n")
        at = text[: text.index(e["anchor"])].count("\n")
        start = block_start(lines, at)
        line = marker(e)
        above = inserts.get(start, [])
        k = start - 1
        while k >= 0 and lines[k].startswith("> **SUPERSEDED BY"):
            above = [lines[k], *above]
            k -= 1
        if line in above:
            results.append((e, "present"))
            continue
        inserts.setdefault(start, []).append(line)
        results.append((e, "applied"))
    lines = text.split("\n")
    for start in sorted(inserts, reverse=True):
        lines[start:start] = inserts[start]
    if any(r == "applied" for _, r in results) and HEADER not in lines:
        lines.insert(1 if lines and lines[0].startswith("# ") else 0, HEADER)
    return "\n".join(lines), results


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("decisions_dir")
    ap.add_argument("markers_json")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    base = pathlib.Path(a.decisions_dir)
    try:
        entries = json.loads(pathlib.Path(a.markers_json).read_text())
    except (OSError, ValueError) as err:
        print(f"cannot read {a.markers_json}: {err}")
        return 2
    by_file = {}
    for e in entries:
        by_file.setdefault(e["file"], []).append(e)
    refused = 0
    print(f"{'file':<34} {'listed':>6} {'applied':>7} {'present':>7} {'refused':>7}")
    for name, group in by_file.items():
        path = base / name
        try:
            text = path.read_text()
        except OSError as err:
            print(f"cannot read {path}: {err}")
            return 2
        new, results = apply(text, group)
        if new != text and not a.check:
            path.write_text(new)
        count = {
            k: sum(1 for _, r in results if r == k) for k in ("applied", "present")
        }
        bad = [(e, r) for e, r in results if r not in count]
        refused += len(bad)
        print(
            f"{name:<34} {len(group):>6} {count['applied']:>7} {count['present']:>7} {len(bad):>7}"
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
