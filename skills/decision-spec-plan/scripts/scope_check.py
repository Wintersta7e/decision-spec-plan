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

With `--waves <plan-index>` it checks the wave order instead: every file two plans of one wave
both list in their File structure sections. Their lanes run in parallel worktrees, so each edits the
file without the other's change and the integrator meets the collision — three lanes of one wave
edited the same four UI files, and of the seven seam defects that left, the integrator fixed four.
Plans sharing a file go in different waves.

With `--asks <decision-index> [<arbiter>]` it checks the scope fence: every file row of every File
structure section must cite an ask (`Ask<n>`, a row of the index's asks table) or a user ruling
(`U<n>`) that one of those files defines, and none may list a file the index's `Do not touch`
section names. Unasked changes were the largest class of user corrections in one project's
review-fix rounds: a version bump, files the reviewer had said to leave alone, other tickets' work.

With `--diff <base>..<head>` (in `--repo`, default `.`) it lists every file the range changed that
no plan's File structure section lists: what a task group added beyond its plan.

Usage:
    scope_check.py <plans-dir> [--list] [--glob 'p4-*.md'] [--ext rs,ts,tsx,py,go,sql,...]
    scope_check.py <plans-dir> --waves <plans-dir>/p<P>-00-index.md [--glob ...]
    scope_check.py <plans-dir> --asks <decisions-dir>/00-index.md [<decisions-dir>/00-arbiter.md]
    scope_check.py <plans-dir> --diff <base>..<head> [--repo <repo>] [--glob ...]

Exit 0 when nothing is unimplemented, 1 otherwise (a File structure section that lists no file
counts), 2 when no plan matched or no plan has a File structure section. With `--waves`: 0 when
no wave shares a file, 1 when one does or a plan is missing from the index's plan set, 2 when the
index has no table with `Plan` and `Wave` columns. With `--asks`: 0 when every row cites an ask,
1 when one does not or lists a file not to touch, 2 when the plans list no file. With `--diff`: 0
when every changed file is planned, 1 when one is not, 2 when the range changed nothing or git
failed.
"""

import argparse
import pathlib
import re
import subprocess
import sys

DEFAULT_EXT = "rs,ts,tsx,js,jsx,mjs,cjs,css,scss,json,sql,yml,yaml,toml,py,go,java,kt,swift,c,h,cpp,hpp,cs,rb,sh,md,html,xml,properties,gradle,kts"
SECTION_RE = re.compile(
    r"^#{2,3} File structure\s*$(.*?)^#{2,3} (Task|Tasks|Global|Interfaces)",
    re.MULTILINE | re.DOTALL | re.IGNORECASE,
)
DIR_RE = re.compile(r"`([A-Za-z0-9_./-]*/)`")
PLAN_ID = re.compile(r"p\d+-\d+[a-z]?(?=-|$)")
ASK_RE = re.compile(r"\b((?:Ask|U)\d+)\b")
# an id is defined where a line, heading or table row opens with it
DEFINED_RE = re.compile(r"^[#>*|\s-]*\**((?:Ask|U)\d+)\b", re.MULTILINE)
FENCE_RE = re.compile(
    r"^#{2,4} Do not touch\s*$(.*?)(?=^#{1,4} |\Z)", re.MULTILINE | re.DOTALL
)


def rows(section, file_re):
    """(file, its line) for every file the section lists."""
    cur = ""
    for line in section.split("\n"):
        if line.startswith("#"):
            m = DIR_RE.search(line)
            cur = m.group(1) if m else ""
            continue
        for f in file_re.findall(line):
            yield (f if "/" in f else cur + f), line


def promised(section, file_re):
    return sorted({f for f, _ in rows(section, file_re)})


def unasked(plans, sources, file_re):
    """Plan rows that cite no ask the index defines, or list a file under its Do not touch."""
    text = "\n".join(pathlib.Path(s).read_text(errors="replace") for s in sources)
    known = set(DEFINED_RE.findall(text))
    m = FENCE_RE.search(text)
    fenced = set(file_re.findall(m.group(1))) if m else set()
    print(
        f"{len(known)} asks and user rulings defined; {len(fenced)} files not to touch"
    )
    print(f"{'plan':<40} {'files':>5} {'UNASKED':>7}")
    print("-" * 54)
    total, bad = 0, []
    for name, text in plans.items():
        m = SECTION_RE.search(text)
        found = list(rows(m.group(1), file_re)) if m else []
        total += len(found)
        miss = [
            (
                f,
                "do not touch"
                if f in fenced or f.split("/")[-1] in fenced
                else "no ask",
            )
            for f, line in found
            if f in fenced
            or f.split("/")[-1] in fenced
            or not set(ASK_RE.findall(line)) & known
        ]
        bad += [(name, f, why) for f, why in miss]
        print(f"{name:<40} {len(found):>5} {len(miss):>7}")
    for name, f, why in bad:
        print(f"   {name}  {f}  ({why})")
    print(
        f"\n{len(bad)} of {total} planned files cite no ask (Ask<n> or U<n>) or are not to be touched"
    )
    return 2 if not total else 1 if bad else 0


def unplanned(plans, rev_range, repo, file_re):
    """Files a commit range changed that no plan's File structure section lists."""
    out = subprocess.run(
        ["git", "-C", repo, "diff", "--name-only", rev_range],
        capture_output=True,
        text=True,
        check=False,
    )
    if out.returncode:
        print(out.stderr.strip())
        return 2
    changed = out.stdout.split()
    planned = set()
    for text in plans.values():
        m = SECTION_RE.search(text)
        planned.update(promised(m.group(1), file_re) if m else ())
    extra = [
        c for c in changed if not any(c == p or c.endswith("/" + p) for p in planned)
    ]
    for c in extra:
        print(f"   {c}")
    print(
        f"{len(extra)} of {len(changed)} changed files are in no plan's File structure"
    )
    return 2 if not changed else 1 if extra else 0


def plan_table(index):
    """{plan stem: (wave, its `Depends on` text)} from the plan index's plan-set table: the one
    with `Plan` and `Wave` columns."""
    rows, cols = {}, None
    for line in pathlib.Path(index).read_text(errors="replace").splitlines():
        if not line.startswith("|"):
            cols = None
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cols is None:
            names = [c.lower() for c in cells]
            if "plan" in names and "wave" in names:
                deps = names.index("depends on") if "depends on" in names else None
                cols = names.index("plan"), names.index("wave"), deps
        elif not set("".join(cells)) <= set("-: "):
            plan, wave, deps = cols
            rows[cells[plan].strip("`").removesuffix(".md")] = (
                cells[wave],
                cells[deps] if deps is not None and deps < len(cells) else "",
            )
    return rows


def depends(rows):
    """{plan stem: every plan it waits for}, directly or through others; `all` waits for all."""
    ident = {s: m.group(0) if (m := PLAN_ID.match(s)) else s for s in rows}
    direct = {
        s: set(rows) - {s}
        if text.strip().lower().startswith("all")
        else {
            o
            for o in rows
            if o != s and re.search(rf"(?<![\w-]){re.escape(ident[o])}(?!\w)", text)
        }
        for s, (_, text) in rows.items()
    }
    reach = {}
    for s in rows:
        stack, seen = list(direct[s]), set()
        while stack:
            if (o := stack.pop()) not in seen:
                seen.add(o)
                stack.extend(direct[o])
        reach[s] = seen
    return reach


def overlaps(plans, index, file_re):
    """Files that two plans of one wave, neither waiting for the other, both change: their lanes
    run in parallel worktrees, and each edits the file without the other's change until the
    integrator merges them."""
    rows = plan_table(index)
    if not rows:
        print(f"no plan-set table with Plan and Wave columns in {index}")
        return 2
    reach = depends(rows)
    owners, unlisted = {}, []
    for name, text in plans.items():
        stem = name.removesuffix(".md")
        if stem not in rows:
            unlisted.append(name)
            continue
        m = SECTION_RE.search(text)
        for f in promised(m.group(1), file_re) if m else ():
            owners.setdefault((rows[stem][0], f), []).append(stem)
    shared = []
    for (wave, f), stems in sorted(owners.items()):
        both = sorted(
            {
                s
                for a in stems
                for b in stems
                if a != b and b not in reach[a] and a not in reach[b]
                for s in (a, b)
            }
        )
        if both:
            shared.append(f)
            print(f"wave {wave:<4} {f}  {', '.join(both)}")
    print(
        f"{len(shared)} files changed by two or more plans of one wave that run at once"
    )
    if unlisted:
        print(f"not in the index's plan set: {', '.join(unlisted)}")
    return 1 if shared or unlisted else 0


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("plans_dir")
    ap.add_argument("--glob", default="*.md")
    ap.add_argument("--ext", default=DEFAULT_EXT)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--waves", metavar="PLAN_INDEX")
    ap.add_argument("--asks", nargs="+", metavar="INDEX")
    ap.add_argument("--diff", metavar="RANGE")
    ap.add_argument("--repo", default=".")
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
    if args.waves:
        return overlaps(plans, args.waves, file_re)
    if args.asks:
        return unasked(plans, args.asks, file_re)
    if args.diff:
        return unplanned(plans, args.diff, args.repo, file_re)

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
