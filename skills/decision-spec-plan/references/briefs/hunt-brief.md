# The hunt brief — full text

Copy to `<planning-dir>/HUNT-BRIEF-p<P>.md`. Keep every unmarked rule (SKILL.md, 'Adapt, don't
trim'); fill every `‹ADAPT›`. Each hunter's dispatch (`prompts.md` §8) names this file, its seat,
its area and the run id: the rules reach every seat whole, never retyped. **Why:** this is the
winning arm of a measured hunt benchmark — the environment and variant seats took recall from 0.54
to 0.88 at the same precision, and the file-first returns lost no report (`failure-modes` F108).

---

```markdown
# ‹ADAPT: Project› — bug hunt brief

You are one of the hunt's ‹ADAPT: 4–6› hunters. Your seat, its area and the run id `<run>` arrive
in your dispatch. The seats: ‹ADAPT: n› area hunters, each reading its area in full, one
**environment seat** and one **variant seat** (below)‹ADAPT: optional — and a property-based seat
for pure logic (parsers, arithmetic, state machines): generate inputs, check an invariant›.

| Seat | Area |
|---|---|
| ‹ADAPT: seat name› | ‹ADAPT: the directories or modules it reads in full› |
| environment | the whole product, run as the environment seat says |
| variant | the repository's fix history, then the whole code |

## The target

‹ADAPT: what the target is — its languages, layers and storage — its repository, and the hunt's
SHA `<sha>`›. Read its README first.

A defect is behaviour a user or the system would hit that is wrong: a crash, data loss, a wrong
result, a hang, a race, a leak of local data, a security hole, a broken contract between two
layers, a published claim (README, UI text) the code makes false. Not a defect: style, naming,
"could be cleaner", hardening against inputs that cannot occur.

## Your clone

Work only in your own clone of the target at the hunt's SHA, outside the repository:
`git clone -q file://‹ADAPT: repo› ‹ADAPT: <scratch>/hunt/<run>/<seat>›`, then check out `<sha>`
in it. The clone sits on the Linux disk when the repository sits on a Windows mount; only the
environment seat also runs a copy from the Windows-mounted drive. ‹ADAPT: the shared caches to
link into the clone, read-only (dependency directories, module and build caches)›.

Build and test: ‹ADAPT: the build and test commands, and how to run one package or file›. Run a
long command to a log and read the log, never through `| tail` or `| head`. You may build and run
the product in your clone for a probe.

## Find-only

- No commit, no push, no git config change, no inline alias (`git -c alias.<name>=…`), no edit
  outside your clone, the findings dir `<planning-dir>/hunt/<run>/findings/` and your scratchpad.
- Read only inside your clone, the findings dir and ‹ADAPT: the caches the build needs›: no
  `find ~`, no listing or search of the home directory or the filesystem outside them.
- No network beyond what the cached dependencies need.
- Where bubblewrap runs, the route's hook runs each of your Bash calls with the route's repository
  and its git directory read-only in the kernel (the planning dir stays writable): any write there
  — `sed -i`, `cp`, a build's `target/`, `git stash` — fails with "Read-only file system". Clone
  first and work in your clone; your clone's own git, `git stash` included, stays free. Each call
  starts in the same directory: a `cd` lasts that call only, and a shell function or alias of the
  session does not reach it. The hook also refuses a commit anywhere, a git config write, an inline
  alias or config include, and an edit-tool write into the repository outside its planning dir or
  into the global git config. Without bubblewrap your Bash runs unwrapped: only those refusals
  hold, and the lead compares a fingerprint of the repository before and after the hunt. Inside
  the wrap you still share the host's processes and your session bus, so a command can reach the
  repository around it (`/proc/<pid>/root/…`, `systemd-run --user`); the wrap keeps both on
  purpose, so a server you start with `&` outlives its call and a `systemd-run --user` load window
  still works. A backstop against a slip, not a sandbox against a hunter set on escaping (the
  fingerprint shows one): this rule binds where the hook cannot see. **Why:** hunters under a find-only brief
  committed, changed the hooks path and wrote outside their tree (F109).

## Ports and processes

Every server you start binds port 0 (read the port it got from its output) or a port you first
proved free and hold for the probe's whole life. Stop every process you started: `ps` before you
finish shows none of them. **Why:** two hunters' servers collided on one port for ~25 s (F108).

## Prove it or drop it

Each finding is *measured* — a failing probe or test in your clone: its path and the failing
output, quoted — or *by reading* — a trace with every hop at `file:line`. Mark each. A suspicion
neither proves goes to `<planning-dir>/hunt/<run>/findings/suspects-<seat>.md`: its location, the
suspected failure, and the missing oracle (the probe that would settle it) — never into the
findings table, never silently dropped. Read code outside your area when a path crosses into it;
report a defect there, naming its area.

## Anchors

Every location is `file:line` **and** the enclosing function or symbol name
(`parse.py:88 read_header`), read from the file at the hunt's SHA — never from memory or a search
hit's line alone. **Why:** reports cited lines past the file's end (F108); the name still finds the
code when a line number is off.

## File first

Before you read any code, write `<planning-dir>/hunt/<run>/findings/<seat>.md` with line 1
`findings: in progress` and your seat's scope. Add each finding the moment it is proved. When you
finish, set line 1 to `findings: critical=<n> high=<n> medium=<n> low=<n>`. If you are cut off,
the file is your report.

## The report

One table row per finding: ID `<SEAT>-<n>` · severity · `file:line` and function · the failure
scenario (the input or state → the wrong result) · the evidence with its label (*measured*: the
probe's path and quoted output; *by reading*: the hop chain) · the smallest fix you would make.
Then "Checked, no defect": what you examined and found sound, one line each.

Severity: critical — data loss, a leak of local data, a crash, remote code execution; high — a
core feature broken on a normal user path, or a security weakness reachable without local admin;
medium — wrong behaviour on a plausible but less common path; low — a rare edge, or cosmetic but
user-visible.

## The environment seat

Hunt the defects that show only outside a quiet run on a local disk — where earlier hunts missed:
- the Windows-mounted drive: copy your clone to ‹ADAPT: a directory on the Windows mount — the
  only place outside your clone you may write› and run the tests and the product from there (file
  names, modes, locking, the database);
- port reuse and restarts: start, stop and restart the product on one port, run two instances,
  kill one mid-request;
- a loaded machine: run the tests and the product while `nproc` busy loops
  (`nice -n 0 python3 -c 'while 1: pass'`) run, in short windows, each killed after — `ps` shows
  none left;
- timing: clocks, time zones, day boundaries, timeouts and retries under that load.

## The variant seat

Start from the repository's own fix history: `git log`, and each fix commit's diff. For each fixed
defect, hunt the same mistake elsewhere — the same pattern, sibling functions, the other layer.
Then hunt the variants of each defect you prove yourself.

## Your reply

The findings file's path and its line 1, and the suspects file's path and its count. Nothing else.
```
