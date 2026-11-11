#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""One screen of a decision-spec-plan round's state, for the lead's in-flight block.

Reports, never rules. Expected files come from the round's own indexes: the decision
index's `D<n>` rows and the plan index's plan ids; one not written yet is listed as
pending. For each file that exists it flags the ends a lead must not misread (F38):
empty, an unpaired code fence, written in the last two minutes. With --repo it also
reads git: each lane checkpoint's `Final SHA:` line, whether the main branch contains it
(by ancestry, or by patch for a rebased lane), and a lane branch that moved past a
merged checkpoint (F41); each lane not merged gets a line with its commits since the
main branch, the gate log at its SHA, their trailers and what its worktree left
uncommitted — the check of a group's return (F80). A lane is any `lanes/*-checkpoint.md`
but another phase's `p<Q>-…`. Every gate log's last `exit=` line is reported; a log
without one is still running or was piped. A HANDOFF.md (or SESSION-HANDOFF.md) over 40
KB and an unmerged lane's checkpoint over 35 lines are flagged (F76), and its rulings
file over 12 KB (F67). With --repo, the decision index's
`> **Base**: `<ref>` at `<sha>`` and `> **Assumes**: `<ref>` at `<sha>`` lines are
checked against the refs as of the last fetch: a base that moved, an assumed ref that
moved or merged into the base, a ref gone (F91).

Usage:
    route_state.py <planning-dir> --phase P [--repo DIR] [--main BRANCH]
        [--sections 38-48 | 38-] [--spec-dir DIR] [--all]
        [--activate [--rung S|M|L] [--ci-harness LABEL] [--sins on|off]]
    route_state.py --budget LABEL --estimate M [--groups N --tasks T] [--phase P]
        [--repo R] [--base pin|catch-up|merge]

--main defaults to the repository's default branch. --sections `38-` counts every
section from §38 on (a phase whose last section is not known yet). --all lists every
file with its size, age and last line. Exit 0 on a report, 2 when the planning dir does
not exist. The report keeps whether main holds each lane's patches, for main's current
tip, in <git-common-dir>/dsp-cherry.json: a cache, safe to delete.

--activate also writes the arguments to <git-common-dir>/dsp-route-<id>.json, one per
planning dir, which marks the repository as running that route (push_guard.py then holds
pushes to gated commits; two routes in one repository keep separate phases, budgets and
spend, F93), and registers this session in ~/.claude/dsp-routes/<session-id>.json, which
`route_state.py --hook` reads: after the lead's tool calls (PostToolUse, at most every
20 s) and on an agent's return as a prompt (UserPromptSubmit) it puts what changed in
the report into the lead's context, with the skill's files changed since the session
read them (F78), and after a compaction or a resume (SessionStart) the whole report and
what to re-read. Re-run with --activate at each phase and in each new lead session;
delete the marker to end the route. When the session's transcript lacks a record shape
the hooks read (Claude Code changed its format), it prints a line naming the checks that
are off: each lets every call through on a shape it cannot find. `--ci-harness <label>`
names a suite CI runs that the local full gate does not; push_guard.py then also wants,
per pushed commit, a gate log whose first 20 lines hold `harness=<label>` (F90).

--budget records the route's estimate in M units (costs.md) — the lead, every review and
agent of the stages left — in <planning-dir>/route-budget.json, one budget a route
(execution.md). As a PreToolUse hook (Registration, below), it then holds the lead's
dispatch of an `exec-` agent until the phase has a budget and the user has answered
after it in the lead session that recorded it — or answered an AskUserQuestion earlier
in the turn that records it, so ask, then record, and the one answer is enough (F93); at
rung S a recorded figure is enough. The answer is kept with the record, so a new lead
session of the route asks nothing again. It holds again once the spend since the record
— the route's leads, their agents but those naming another phase, and hook sessions —
passes 125% of the estimate (F74), and holds an `exec-` agent whose name names another
phase, which that spend leaves out. A session whose transcript holds no prompt the user
typed (headless `claude -p`) has no answer to wait for, so the hold lets its own
dispatches through, never another session's, and keeps no answer: record the budget
anyway and report it at the end. While something moved under the round since its
decision index recorded it — commits the Base's upstream has that the local Base lacks,
a Base with no upstream past its SHA, an Assumes ref moved, merged or gone, as of the
last fetch — it holds the dispatch until a budget records the user's choice with
`--base`: pin and merge cover any move, catch-up the moves seen when it was recorded
(F91). Inside an `exec-` agent it tells a group past 200k tokens of context to finish
its task and return (F75), and holds a `git commit` while its own lane's rulings file
changed after the agent last read it (F59). In a session with no active route it holds a
`dsp-deep` or `dsp-mechanical` dispatch until the route is activated (F79). On a route
activated with `--rung S` it refuses the lead's dispatch of an agent whose name or
description says harvest: at S the lead harvests itself (F87). While a route is active
it asks the user before the lead's publish to a package or image registry
(`npm publish`, `cargo publish`, `twine upload`, `docker push` and the like),
`gh pr close|merge`, `gh issue close|delete`, `gh release create|delete|edit|upload`,
`gh repo delete|archive|rename`, a `gh api` write, `--delete-branch` or a remote branch
delete by `git push`, and refuses them inside a route agent (F81). It refuses a
hand-written gate log (`lanes/*gate*.log`) to the lead and its agents alike: Write or
Edit on one, `sed -i` on one, `echo`/`printf`/heredoc text or a literal `exit=<n>`
redirected into one (F97). A check that fails lets the call through. Registered for
SubagentStop and TeammateIdle, it sends an agent that ends its turn while its own
background shell or monitor runs back to wait on it, twice at most per job: nothing
wakes it when the job ends (F92). It holds the lead's `exec-` dispatch while
`decision_check.py` fails on the phase — one whose index did not exist at its first
--activate — and a `verify-` agent whose prompt is not the file
`decision_check.py --verifier` wrote.

Registration: the plugin's `hooks/hooks.json` runs `route_state.py --hook` under
SessionStart matcher `compact|resume`, PostToolUse matcher `*`, UserPromptSubmit,
PreToolUse matcher `Agent|Bash|Write|Edit|MultiEdit|NotebookEdit`, SubagentStop,
TeammateIdle.
"""

import sys

# loaded on every path, the hook's too
from dsp_route.common import RouteArgs, default_branch, parser


def main() -> int:
    """Run the hook, the budget mode or the report (and --activate); the exit status."""
    # Each mode imports only its own modules: the hook runs on every tool call of every
    # session.
    argv = sys.argv[1:]
    if "--hook" in argv:
        from dsp_route.hook import hook

        return hook()
    if "--budget" in argv:
        from dsp_route.budget import budget

        return budget(argv)
    from dsp_route.activate import activate
    from dsp_route.report import report

    ap = parser(__doc__)
    a = ap.parse_args(namespace=RouteArgs())
    flags = {"--rung": a.rung, "--sins": a.sins, "--ci-harness": a.ci_harness}
    if (given := [f for f, v in flags.items() if v]) and not a.activate:
        # dropped in silence, a lead believed the route had them (live)
        ap.error(f"{', '.join(given)} take effect only with --activate")
    code = report(a)
    if code == 0 and a.activate:
        code = activate(a, a.main or (default_branch(a.repo) if a.repo else "main"))
    return code


if __name__ == "__main__":
    sys.exit(main())
