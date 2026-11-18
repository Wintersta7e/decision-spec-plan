# The task-group brief — full text

Copy to `<planning-dir>/GROUP-BRIEF-p<P>.md` before the phase's first task group. Keep every
unmarked rule (SKILL.md, 'Adapt, don't trim'); fill every `‹ADAPT›` — `route_state.py --next`
prints no dispatch while one is left. Each dispatch it prints names this file, the lane's plan,
worktree, checkpoint and rulings file, and the group's tasks: the rules below reach every group
whole, never retyped. **Why:** a lead-written brief dropped one rule from 21 of 24 dispatches
(`failure-modes` F48); briefs that left out the repo's `type:` prefix led to rewords that voided a
gate (F90).

---

```markdown
# ‹ADAPT: Project› — phase-‹P› task-group brief

**Every task group of the phase gets this file, identical.** Your lane, worktree and tasks arrive in
your dispatch. `dsp-deep`'s own rules (one group, rulings, waits, no progress, heavy runs, the
user's machine) hold beside these.

## Read first, in this order

1. Your dispatch's checkpoint, when it names one: its orientation map names the files and symbols
   your tasks touch and the test commands that cover them — open those before you explore.
2. Your plan's tasks, the ones your dispatch names, and the plan's header and gate table.
3. The rulings file your dispatch names, whole, and from the archive only the ids it names.

## Each task

- Work only in your dispatch's worktree. Each task is one commit.
- **Commit rules:** ‹ADAPT: the subject convention the repo's `git log` shows (a `type:` prefix, a
  scope), subject length, body length, and the trailers — exactly these; add no trailer of your own
  (subagents default to adding one).›
- Run every gate into a file and read the file by its last `exit=` line, never through `tail` or
  `head`: the pipe's exit status turns a red gate green (groups that piped ran 17 gates in one
  wave, each refused by the project's own hook).
- ‹ADAPT: house rules — formatter hooks, the install or codegen step after a pull, test data,
  public-repo hygiene, and the project's rules on which suites run locally.›

## When your tasks include the plan's last

Run the plan's final gate task: the gates its table marks `group`, on the SHA you report, into
`‹planning-dir›/lanes/<plan-id>-gate.log` through `‹skill-dir›/scripts/gate.py`. A gate marked
`lead` or `CI` is not yours — the lead runs it; name it in your checkpoint.

## Before you reply

Commit, then **overwrite** `‹planning-dir›/lanes/<plan-id>-checkpoint.md` with the lane's state —
≤35 lines in all:
- ≤15 lines: the lane's tasks done with their SHAs, the gate state, what the next group must know;
- an **orientation map** for the next group's tasks: the files and symbols to open, with file:line,
  and the exact test commands that cover them;
- a line `Next task: <n>` — the first task of the plan no group has finished, or `Next task: none`;
- last, a line `Final SHA: <sha>`.

`route_state.py` reads those two lines: the SHA it checks the lane at, the task the next dispatch
starts from. Reply with the exact SHA you finished on.
```
