# Gates and their limits

What each mechanical check establishes, and what it does not. The checks target careless agents —
a log piped through `tail`, a test quietly skipped, a push before the gate — not an agent working
to deceive them; each limit below is a way through that a careless agent is unlikely to take and a
deliberate one could.

## The push gate

**Establishes**: every commit a push sends has a gate log under `<planning-dir>/lanes/` whose first
`sha=` line (within its first 20 lines) names that commit with `dirty=0`, and whose last `exit=`
line is `exit=0`; with `--ci-harness <label>`, a second such log names the harness (except a push
to a non-main branch, which starts the CI run); with `--sins on`, a seven-sins verdict with
`blocking=0` covers the commits since the remote's tip. The check runs in git's pre-push hook, on
the exact refs git sends, and `gate.py` writes the log itself.

**Does not establish**: that the logged command was the project's *full* gate (the `cmd=` line
records which command ran; nothing compares it with the CI's); that the log came from `gate.py` (a
log written another way with the same lines passes); that CI on another OS or database agrees,
unless the route named that suite with `--ci-harness`. A push from outside Claude Code (a
terminal) is never checked, and a repository with `core.hooksPath` set gets no hook: there the
Bash hook reads each push command instead, and holds the forms it cannot read.

## Hand-written gate logs

`route_state.py --hook` refuses an edit tool on a `lanes/*gate*.log`, `sed -i`/`perl -i` on one,
interpreter code that writes one, and `echo`/`printf`/heredoc text spelling `exit=`, `dirty=` or
`sha=` redirected into one. **Not caught**: a value built to hide the claim, a log named through a
glob or a computed path. It reads what a command says, not why.

## Stage checkers (the lead runs them at each gate)

| Script | Establishes | Does not establish |
|---|---|---|
| `decision_check.py` | Every SETTLED row cites a ruling or document, not only today's code; every requirement dimension has an owner or N/A; every review finding has a disposition | That a ruling is right |
| `criteria_check.py` | Every acceptance criterion in the spec has an id, and every id maps to a plan task and a test file | That the test exists, runs or checks the criterion |
| `plan_lint.py` | A plan has the structure an executor needs (it catches truncated plans) | That the plan is correct |
| `scope_check.py` | Every file a plan promises is created by some task; no two plans of one wave change the same file; every planned file cites an ask or a user ruling; a merged lane changed no file outside its plan | Exact coverage: the match is by path text, a heuristic (`failure-modes` F25) |
| `test_check.py` | The acceptance tests a commit range deleted, skipped, weakened or edited after they were written | That the remaining tests are meaningful; it lists, the lead rules |

## Hooks on the lead and its agents

| Hold | Limit |
|---|---|
| A Stage 5 wave's dispatches wait for a recorded budget and the user's answer | Headless (`claude -p`) has no user, so it holds nothing: cap the run with `--max-budget-usd` |
| `gh` writes (merge, close, release, repo, `gh api` writes) and remote branch deletes ask the user; agents may not run them | Only the commands it names |
| A push that names a bypass (`DSP_SKIP_PUSH_GUARD`, `DSP_SKIP_REVIEW`) asks the user; an agent's is blocked | Reads the command's words, quotes removed: a bypass exported by a file the command sources, or a name assembled from pieces, reaches git's hook unseen |
| An agent ending its turn while its own background job runs is sent back, twice per job at most | Reads the agent's transcript |
| A task group past 200k context is told to finish and return | Reads the agent's transcript |
| The lead's `exec-` dispatches wait while `decision_check.py` fails | Only for a phase whose index did not exist at its first `--activate` |

## When a hook itself fails

Every check that throws lets the call through: a broken install must not stop every session's
tool calls, so no hook carries `onFailure: "block"`. The one exception is the push: while a route is
active, the Bash hook blocks a push-shaped command it failed to read, and the pre-push hook holds a
route's pushes when the guard it calls is gone (the plugin moved or was removed: re-run
`--activate`).

## What depends on Claude Code internals

The budget hold, the ETAs, the answer tally, the own-jobs wait, the context stop and
`usage_report.py` read the session transcripts (`~/.claude/projects/*/<session>.jsonl`), a format
Claude Code does not document. When it changes, those checks go quiet rather than wrong: each one
that cannot read a record lets the call through. The push gate, the gate runner and the stage
checkers read only git and the planning directory.
