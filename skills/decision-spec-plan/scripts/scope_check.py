#!/usr/bin/env python3
"""Find plans that promise files no task creates.

A plan opens with a File structure section listing the files it will create. A plan whose author
ran out of output before the last task keeps that table and loses the tasks — the table still names
the file, so the gap is invisible unless the two are compared. That is how ten of 21 plans in one
project came to be missing their entire UI.

A promised file is UNIMPLEMENTED when its path appears at most once in its plan (only in the table)
and no other plan mentions it more than once.

Bare filenames are resolved against the nearest preceding sub-heading that names a directory in
backticks, because plans group them that way:

    ### Rust — `core/src/session/`
    | `segment.rs` | The segment state machine |

The File structure section ends at the first `## Task`, `## Tasks`, `## Global` or `## Interfaces`
heading (either `##` or `###` depth).

Usage:
    scope_check.py <plans-dir> [--list] [--glob 'p4-*.md'] [--ext rs,ts,tsx,py,go,sql,...]

Exit 0 when nothing is unimplemented, 1 otherwise (a File structure section that lists no file
counts), 2 when no plan matched or no plan has a File structure section.
"""

import argparse
import pathlib
import re
import sys

DEFAULT_EXT = "rs,ts,tsx,js,jsx,mjs,cjs,css,scss,json,sql,yml,yaml,toml,py,go,java,kt,swift,c,h,cpp,hpp,cs,rb,sh,md,html"
SECTION_RE = re.compile(
    r"^#{2,3} File structure\s*$(.*?)^#{2,3} (Task|Tasks|Global|Interfaces)",
    re.MULTILINE | re.DOTALL | re.IGNORECASE,
)
DIR_RE = re.compile(r"`([A-Za-z0-9_./-]*/)`")


def promised(section, file_re):
    out, cur = set(), ""
    for line in section.split("\n"):
        if line.startswith("#"):
            m = DIR_RE.search(line)
            cur = m.group(1) if m else ""
            continue
        for f in file_re.findall(line):
            out.add(f if "/" in f else cur + f)
    return sorted(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("plans_dir")
    ap.add_argument("--glob", default="*.md")
    ap.add_argument("--ext", default=DEFAULT_EXT)
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    exts = "|".join(re.escape(e.strip()) for e in args.ext.split(",") if e.strip())
    file_re = re.compile(rf"`([A-Za-z0-9_./-]+\.(?:{exts}))`")

    plans = {
        f.name: f.read_text(errors="replace")
        for f in sorted(pathlib.Path(args.plans_dir).glob(args.glob))
        if not re.match(r"(p\d+-)?00-", f.name)
    }
    if not plans:
        print(f"no plans matched {args.glob} in {args.plans_dir}")
        return 2

    def elsewhere(path, owner):
        tail = path.split("/")[-1]
        return any(
            text.count(path) > 1 or text.count(tail) > 1
            for name, text in plans.items()
            if name != owner
        )

    print(f"{'plan':<40} {'tasks':>5} {'promised':>8} {'UNIMPL':>7}")
    print("-" * 66)
    total, detail, empty = 0, {}, []
    for name, text in plans.items():
        tasks = len(re.findall(r"^#{2,3} Task ", text, re.MULTILINE))
        m = SECTION_RE.search(text)
        if not m:
            print(
                f"{name:<40} {tasks:>5} {'—':>8} {'—':>7}   (no File structure section)"
            )
            continue
        files = promised(m.group(1), file_re)
        bad = [
            x
            for x in files
            if text.count(x) <= 1
            and text.count(x.split("/")[-1]) <= 1
            and not elsewhere(x, name)
        ]
        detail[name] = bad
        total += len(bad)
        if not files:
            empty.append(name)
        print(
            f"{name:<40} {tasks:>5} {len(files):>8} {len(bad):>7}{'   <-- half-scoped' if bad else ''}"
            f"{'' if files else '   <-- lists no file'}"
        )

    if not detail:
        print(f"\n0 of {len(plans)} plans have a File structure section")
        return 2
    print(f"\n{total} promised files that no task in any plan creates")
    if empty:
        print(f"{len(empty)} File structure sections list no file: {', '.join(empty)}")
    if args.list:
        for name, bad in detail.items():
            if bad:
                print(f"\n## {name}  ({len(bad)})")
                for x in bad:
                    print(f"   {x}")
    return 1 if total or empty else 0


if __name__ == "__main__":
    sys.exit(main())
