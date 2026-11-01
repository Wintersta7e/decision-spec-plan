#!/usr/bin/env python3
"""Insert supersede markers into a decision round's files from a JSON list the markers agent wrote.

The agent judges what each ruling overrides; this script does the inserting. Each entry is
{"file": "D3-x.md", "anchor": "<verbatim text unique in that file>", "ruling": "A7",
"clause": "<what now holds>"}. The marker goes on its own line directly above the first line of
the block holding the anchor -- the paragraph, bullet, table row or code block:

    > **SUPERSEDED BY A7** — <clause>.

and every marked file gets `> **Read 00-arbiter.md first.**` under its title, once. Text is never
deleted or rewritten, and every line keeps its line ending (CRLF stays CRLF). An anchor that is
missing, or found more than once, is refused and named; a marker already above its block is
skipped, so a fixed list can be re-run. Each file is written once.

Usage:
    apply_markers.py <decisions-dir> <markers.json> [--check]

--check reports without writing. Exit 0 when every entry applied or was already present, 1 when any
was refused, 2 when the list, an entry of it (each needs string file, anchor, ruling and clause) or
a named file cannot be read; a malformed list writes nothing.
"""

import argparse
import json
import pathlib
import re
import sys

HEADER = "> **Read 00-arbiter.md first.**"
KEYS = ("file", "anchor", "ruling", "clause")
BLOCK_START = re.compile(r"^\s*(\||#|>|[-*+]\s|\d+[.)]\s)")
FENCE = re.compile(r"^\s*(```|~~~)")
MARK = "> **SUPERSEDED BY"


def marker(entry):
    clause = entry["clause"].strip()
    end = "" if clause.rstrip("\"')]`*”’»").endswith((".", "!", "?")) else "."
    return f"> **SUPERSEDED BY {entry['ruling'].strip()}** — {clause}{end}"


def block_start(lines, i):
    """The first line of the paragraph, bullet or table row that line i belongs to, or the opening
    fence of the code block holding it. A heading, table row or quote line above (an earlier
    marker is a quote line) ends the walk."""
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


def apply(lines, entries):
    """Takes the file's lines without their endings. Returns the new lines, the original line each
    new line takes its line ending from, and one (entry, outcome) per entry: applied, present,
    missing or ambiguous (n)."""
    # Marker lines are blanked for the search, so a clause that repeats its anchor does not make
    # a re-run ambiguous.
    text = "\n".join(" " * len(x) if x.startswith(MARK) else x for x in lines)
    results, inserts = [], {}
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
    out, src = [], []
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


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
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
    if not isinstance(entries, list):
        print(f"cannot read {a.markers_json}: not a list of entries")
        return 2
    for n, e in enumerate(entries, 1):
        if not (isinstance(e, dict) and all(isinstance(e.get(k), str) for k in KEYS)):
            print(
                f"cannot read {a.markers_json}: entry {n} needs string {', '.join(KEYS)}: {e!r}"
            )
            return 2
    by_file = {}
    for e in entries:
        by_file.setdefault(e["file"], []).append(e)
    refused = 0
    print(f"{'file':<34} {'listed':>6} {'applied':>7} {'present':>7} {'refused':>7}")
    for name, group in by_file.items():
        path = base / name
        try:
            # newline="": read and write the file's own line endings, never rewrite them.
            with open(path, newline="") as f:
                raw = f.read()
        except OSError as err:
            print(f"cannot read {path}: {err}")
            return 2
        # Each line keeps its own ending; an inserted line takes the ending of the line it goes
        # above, and the last line's when that one has none. A BOM stays first.
        bom = "\ufeff" if raw.startswith("\ufeff") else ""
        parts = raw[len(bom) :].split("\n")
        last = len(parts) - 1
        lines = [
            x[:-1] if k < last and x.endswith("\r") else x for k, x in enumerate(parts)
        ]
        eol = [
            "\r\n" if k < last and x.endswith("\r") else "\n"
            for k, x in enumerate(parts)
        ]
        if last:
            eol[last] = eol[last - 1]
        out, src, results = apply(lines, group)
        new = bom + "".join(x + eol[i] for x, i in zip(out[:-1], src[:-1])) + out[-1]
        if new != raw and not a.check:
            with open(path, "w", newline="") as f:
                f.write(new)
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
