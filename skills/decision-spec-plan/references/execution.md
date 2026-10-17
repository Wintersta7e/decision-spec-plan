# Stage 5 — executing the plans in waves

The plan index's wave order is the schedule. One agent per plan, one worktree per lane, merged into
the main branch between waves. (At S the one plan is the schedule and there is no register lane: you
run `criteria_check.py` on the one spec file.)

## Before wave 1
- **Lane 0 first**: the arbiter's list of shipped defects and false published claims lands before
  any new feature builds on them. It may be planned and executed while the rest of the plan round is
  still running.
- Record the **baseline gate with its SHA**: every suite's count, and the failing-test *identities*
  if any are red.
- **Price each wave before its first dispatch** (`costs.md`, Stage 5) and record it:
  `python3 <skill-dir>/scripts/route_state.py --budget "<wave>" --estimate <M> --groups <n>`, `<n>`
  the `exec-` agents it covers (task groups, fix groups, the integrator). Tell the user the figure
  and wait for their answer. The hook holds every `exec-` dispatch until the user has answered
  after the record, and again once the dispatches since pass 125% of `<n>` or the spend 125% of
  the estimate: record the remaining work's figure, say what ran over and why, and wait again.
  **Why:** one run quoted its Stage 5 figure half a minute after its first dispatches, from the
  older group median five times too high; in another, a wave ran 42% over and the headcount rule
  never fired (`failure-modes` F74).

## A lane
- `git worktree add ../<repo>-<plan-id> -b <plan-id> <main-sha>`; symlink in whatever gitignored
  directories the agents need (planning dir, agent config, local instructions) and run the project's
  install/codegen sequence **inside** the worktree.
- Dispatch the lane's execution agents **one task group at a time**, sequentially in the lane's
  worktree: a group is about 100 turns — **size it by what its tasks run, not by their count**: up to
  ~5 consecutive tasks that stay on one side of the stack, **2** when a task's steps run an
  end-to-end or GUI suite or change both sides of a process boundary (`failure-modes` F60). A ruling
  that adds work counts as a task: a group already at size gets it in the next group's dispatch.
  **The lane's last group runs the plan's final gate task**: the lane's full gate on the SHA it
  reports, into `<planning-dir>/lanes/<plan-id>-gate.log` (the format under *Push only gated
  commits*), a red fixed under `dsp-deep`'s no-progress rule; the integrator refuses a lane SHA
  without it (`prompts.md` §5). Each agent gets the plan path, its task numbers, the
  previous group's checkpoint, the lane's rulings file, the brief's house rules, the
  commit-message rules (subject length, body length, trailers — **state them; subagents default to
  adding their own trailers**), and "commit, **overwrite** `<planning-dir>/lanes/<plan-id>-checkpoint.md`
  with the lane's current state — ≤15 lines: the lane's tasks done with SHAs, gate state, what the
  next group must know; then an **orientation map** for the next group's tasks — the files and
  symbols to open, with file:line, and the exact test commands that cover them; last a line
  `Final SHA: <sha>`; ≤35 lines in all — and report the exact SHA you finished on" —
  `route_state.py` takes the lane's SHA from that line and flags a longer file. The next group opens
  what the map names before it explores. **Why:** fresh groups reached 120–245k tokens of context
  before their first edit, mostly reading code the previous group had already read (`failure-modes`
  F67); with the map they reached a median ~85k, but checkpoints that kept every earlier group's
  part grew to 91 lines and each group re-read the stack (F76). On its return, dispatch the next
  group as a **new agent** — no user step. **Name every Stage 5 agent `exec-<plan-id>-<group>`** (a
  fix group `exec-<review>-fixes`, an integrator `exec-wave<w>`): `route_state.py`'s hooks find
  them by that prefix — they tell a group past 200k tokens of context to finish its task and
  return, and hold its `git commit` while its rulings file has an entry it has not read.
  Never hand a finished agent its next group by `SendMessage`, and never write a lane brief whose
  "groups" are checkpoints inside one agent; a merge point other lanes wait for is a group
  boundary, not a pause. `SendMessage` only resumes a group a limit interrupted or answers an
  agent's question.
  **Why:** a turn re-sends the agent's whole context; whole-lane agents of 150–550 turns
  averaged 230–630k tokens per turn and cost 4–37M each here, 13–30M on another machine, and lanes kept alive
  across groups by message ran 314–719 turns and cost 23–46M each (`failure-modes` F46). `dsp-deep`
  enforces the one-group limit itself, and ends its group at the first task boundary after a
  compaction or once its context passes 200k tokens (the hook tells it; F75) — a group that does
  either has outgrown its size: size the lane's next groups smaller, and when that raises the lane's
  group count, re-record its wave's budget. Tier deep (`dsp-deep`), unless the user
  moved lanes at the rung announcement (`prompts.md` header).
- **Rulings reach a running lane through its file, never by message alone.** Append each ruling,
  verbatim with its id, to `<planning-dir>/lanes/<plan-id>-rulings.md` — append-only; a correction is
  a new entry naming the one it replaces — then `SendMessage` one line naming the id **to a group
  still running**, never to a finished one: it wakes to answer (seven pointers to finished groups
  cost 0.33M in one run). The agent re-reads the file before each task and before each commit, and
  the hook holds an `exec-` agent's `git commit` while the file changed after its last read.
  **Why:** a message reaches a busy agent only when it goes idle — a correction sent 52 s after a
  dispatch arrived 119 min later, and the group had built on the superseded text; in a later run
  every pointer still arrived 5–14 min late (`failure-modes` F59). A ruling that cannot wait for
  the next task boundary (the agent is doing harm now): `TaskStop` it, check `ps` for processes it
  started, append the ruling, and dispatch a fresh group from its last commit — the dispatch names
  what `git status` shows the stopped agent left uncommitted, and whether to keep it.
- A lane the user hands to the second model instead cannot commit if its sandbox mounts `.git`
  read-only — commit on its behalf and re-run any red it reports yourself.
- **Two lanes never share a worktree.** Before editing a worktree yourself, confirm its agent is
  idle and has no message pending — quiet is not idle.
- **A group that stops on no progress** (`dsp-deep`: the same failing tests after two fix attempts)
  returns a checkpoint naming the failing tests and the hypotheses it ruled out. You rule: a fresh
  agent told what is already ruled out, a plan fix, or a question to the user (`failure-modes` F58).
- **Work after a lane closes is a fresh group's, never yours** — a post-merge bug, a real-data run,
  an install, a decompile or any other investigation gets a group with its own checkpoint. At S
  too: a plan never names the lead as a task's executor. **Why:** an S lead that ran a plan task
  and the post-lane debugging itself spent 21.8M of the run's 28.8M; at another rung a lead spent
  10.9M running end-to-end suites, CI and fixes itself (`failure-modes` F68).

## Merging — one integrator agent per wave
Once every lane of a wave has reported, dispatch one fresh `dsp-deep` **wave integrator**
(`prompts.md` §5). It merges into the main branch locally, lane by lane in the index's order:
1. **Merge the exact SHA the lane reported**, never the branch name.
2. Resolve conflicts; **regenerate** every derived file and count (codegen, locks) — never
   hand-merge them.
3. **Run the full gate after every cross-lane merge**, its whole output to
   `<planning-dir>/lanes/<name>-gate.log`, opening with `sha=<HEAD> dirty=<tracked changes>` and
   ending in `exit=<status>`, and hand-check any file both sides touched. A merge that compiles is
   not a merge that carries the values. Red: it stops and records; **you** rule the fix (a fresh
   agent on that lane, or a revert).
4. Re-check `git merge-base --is-ancestor <sha> HEAD` (a lane can move past its reported SHA).
5. Clean build caches that accumulate stale artefacts.

It writes `<planning-dir>/lanes/wave<w>-integration.md` and returns the new main SHA. **On its return
you check first-hand, with no gate output in your context**: the route-state hook's next injection
(or one `route_state.py <planning-dir> --phase <P> --repo <repo>` run) shows every lane's checkpoint SHA merged —
by ancestry, by patch, or by its `Merged` line in the integration file when the lane was squashed
or rebased — no lane moved past its merged SHA, and every gate log's last `exit=` line; one `git rev-parse` of the main branch confirms the SHA it reported. On
red, grep the failing tests' names from the log, never read it whole. Then **delete each merged lane's branch and worktree** — leave no scaffolding
behind — and branch the next wave from the new SHA. **Why:** in two runs the lead ran tests and gates
(14–15% of its cost) and polled CI (3–11%) itself, at a ~530k mean context (`failure-modes` F56).

**Push only gated commits.** While the route is active, `scripts/push_guard.sh` (a PreToolUse hook)
blocks a `git push` of any commit without a gate log in `<planning-dir>/lanes/` whose first `sha=`
line (within its first 20 lines) is `sha=<that commit> dirty=0` and whose last `exit=` line is
`exit=0` — the integrator's last log covers the main it returns; a commit you add after it needs
its own full gate first:
`{ echo "sha=$(git rev-parse HEAD) dirty=$(git status --porcelain --untracked-files=no | grep -c .)"; <full gate>; echo "exit=$?"; } > <planning-dir>/lanes/<name>-gate.log 2>&1`.
**Every gate run — yours included — goes to such a log**, read by its last `exit=` line and a grep
for failing tests, never piped through `tail` or `head` (`failure-modes` F31): one lead piped 22
gates through `tail`, and one hid the lint error of a red commit. A gate log is never edited — a
log the guard refuses is rerun. **Why:** a lead pushed main twice ungated and both CI runs went
red, unnoticed for hours (`failure-modes` F56) — CI confirms a state proven green here; it never
discovers one.

**At M and L, review before every push** (`sins/lead.md`, code mode): once the commit to push is
gated, seven reviewers read what it sends against the remote's tip, reproduce each other's highs
and debate the fixes. Its verdict, `<planning-dir>/reviews/p<P>-push<n>-verdict.md`, opens with
`reviewed=<SHA> base=<SHA> blocking=<n>` and `after=<fix SHAs>`; `push_guard.sh` holds the push
until `blocking=0`, every commit after the reviewed one is on `after=`, and the base is an ancestor
of the remote-tracking ref (activated with `--rung M|L`; an older marker without a rung skips it).
A new high is fixed by a fresh task group from the debate-amended recommendation, or waived by the
user as a U-ruling; pre-existing highs go to the next phase's Lane 0. **Why:** a finished lane
whose full gate was ALL GREEN 25/25 still carried two new highs, and the debate struck a
first-proposed fix that would have crashed at every launch (`failure-modes` F70).

**CI**, after you push (an outward action — yours and the user's): one background blocking watch
(`gh run watch <run-id> --exit-status`, or the CI's equivalent) — one notification, no polling loop;
on red read only the failed job's log (`gh run view <run-id> --log-failed`).

## Registering the phase
- Run an **unwired-producer audit** (every new public producer has a production caller) before the
  register lane — green suites have hidden six uncalled producers in one phase. The last feature
  wave's integrator runs it.
- The **register lane runs last**: it folds every section's criteria into the machine-readable bar
  and proves each maps to a test that runs. **Never untag a test to go green**; a tag that is a false
  claim is renamed with the reason in the commit body.
- Drive the real product once (not only the suites) before calling the phase done — the integrator
  after the register lane does it and records what it ran and saw; open the screenshots you need, not
  all of them.

## Report
Status leads with the user's priority track: what merged (SHAs), the gate figures with the SHA they
were measured on, what is still in flight, and what is known-unfixed with an owner.
