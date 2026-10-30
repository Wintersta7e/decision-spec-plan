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
- **Lanes that run at once share no file.** `scope_check.py <plans-dir> --waves <index>` lists every
  file two plans of one wave change while neither waits for the other: move one to a later wave, or
  give the change to one plan. At S, with no plans per lane, list each lane's files before its
  dispatch; lanes sharing one run one after the other. **Why:** three lanes of one wave edited the
  same four UI files; of the seam defects that left, the integrator fixed four and three stayed open
  (`failure-modes` F82).
- **Price each wave before its first dispatch** (`costs.md`, Stage 5) and record it:
  `python3 <skill-dir>/scripts/route_state.py --budget "<wave>" --estimate <M> --groups <n>`, `<n>`
  the `exec-` agents it covers (task groups, fix groups, the integrator). Tell the user the figure
  and wait for their answer — one question: an AskUserQuestion answered earlier in the turn that
  records the figure counts (F93). The hook holds every `exec-` dispatch until the user has answered
  after the record in the session that made it — a new lead session records its own — and again once the dispatches since pass 125% of `<n>` or the spend 125% of
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
  end-to-end or GUI suite or change both sides of a process boundary (`failure-modes` F60). Once the
  lane or an earlier route of the project has groups, **size by their measure instead**:
  `usage_report.py --groups` prints each group's context at its first edit and per commit, and how
  many commits fit between the median first edit and the 200k stop — that many tasks a group (one
  fix round's groups first edited at a median 122k and fit 2; another route's added 67k a commit and
  fit 1, F60). A ruling that adds work counts as a task: a group already at size gets it in the next
  group's dispatch.
  **The lane's last group runs the plan's final gate task**: the lane's full gate on the SHA it
  reports, into `<planning-dir>/lanes/<plan-id>-gate.log` (the format under *Push only gated
  commits*), a red fixed under `dsp-deep`'s no-progress rule; the integrator refuses a lane SHA
  without it (`prompts.md` §5). Each agent gets the plan path, its task numbers, the
  previous group's checkpoint, the lane's rulings file and any archived ruling ids its tasks need,
  the brief's house rules, the
  commit-message rules (the subject convention the repo's `git log` shows — a `type:` prefix, a
  scope — subject length, body length, trailers — **state them; subagents default to adding their
  own trailers**; one route's briefs left out the repo's `type:` prefix, the lead's rewords collided
  with the agents' own and voided a gate), and "commit, **overwrite** `<planning-dir>/lanes/<plan-id>-checkpoint.md`
  with the lane's current state — ≤15 lines: the lane's tasks done with SHAs, gate state, what the
  next group must know; then an **orientation map** for the next group's tasks — the files and
  symbols to open, with file:line, and the exact test commands that cover them; last a line
  `Final SHA: <sha>`; ≤35 lines in all — and report the exact SHA you finished on" —
  `route_state.py` takes the lane's SHA from that line and flags a longer file. The next group opens
  what the map names before it explores. **Why:** fresh groups reached 120–245k tokens of context
  before their first edit, mostly reading code the previous group had already read (`failure-modes`
  F67); with the map they reached a median ~85k, but checkpoints that kept every earlier group's
  part grew to 91 lines and each group re-read the stack (F76). **On its return, the hook's line
  for the lane is the check** — its SHA, commits since the main branch, the gate at that SHA, the
  commits' trailers, uncommitted work — never a hand probe of the tree (one lead spent 74% of its
  cost hand-checking 18 returns, F80); then dispatch the next group as a **new agent** — no user step.
  **Tell the user the ETA the hook answers each `exec-` dispatch with** — the median minutes of the
  route's finished groups, the lane's first — and the lane's, that × its groups left: one wave ran
  3 h 37 m with no ETA in any report until the user paused it (`failure-modes` F83).
  **Name every Stage 5 agent `exec-<plan-id>-<group>`** (a
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
  group count, re-record its wave's budget. `dsp-deep` with the model and effort announced for task
  groups (`prompts.md` header).
- **Rulings reach a running lane through its file, never by message alone.** Append each ruling,
  verbatim with its id, to `<planning-dir>/lanes/<plan-id>-rulings.md` — append-only; a correction is
  a new entry naming the one it replaces — then `SendMessage` one line naming the id **to a group
  still running**, never to a finished one: it wakes to answer (seven pointers to finished groups
  cost 0.33M in one run). The agent re-reads the file before each task and before each commit, and
  the hook holds an `exec-` agent's `git commit` while the file changed after its last read.
  Between groups, with none of the lane's running, move each ruling the lane has applied and no
  later task depends on, verbatim, to `<plan-id>-rulings-archive.md`; the dispatch names any
  archived id a task still needs, and the agent reads only those entries (`grep -n -A<n> '<id>'`).
  `route_state.py` flags an open lane's file over 12 KB. **Why:** every group read the whole file
  before its first edit — one lane's 38 KB of mostly applied entries cost its route's groups
  471 KB of reading (`failure-modes` F67).
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
- **An idle notice that says the agent waits** on its own gate, build or run is a stall, not a
  return: nothing wakes it when that job ends (`failure-modes` F92). Message it at once to wait in
  the foreground (`dsp-deep`); one that waits on anything else has returned — rule it like a return.
- **Work after a lane closes is a fresh group's, never yours** — a post-merge bug, a real-data run,
  an install, a decompile or any other investigation gets a group with its own checkpoint. At S
  too: a plan never names the lead as a task's executor. **Why:** an S lead that ran a plan task
  and the post-lane debugging itself spent 21.8M of the run's 28.8M; at another rung a lead spent
  10.9M running end-to-end suites, CI and fixes itself (`failure-modes` F68).

## Merging — one integrator agent per wave
Once every lane of a wave has reported, dispatch one fresh `dsp-deep` **wave integrator**
(`prompts.md` §5). It merges into the main branch locally, lane by lane in the index's order:
1. **Merge the exact SHA the lane reported**, never the branch name — after
   `scope_check.py <plans-dir> --glob '<plan-id>-*.md' --diff <wave base>..<SHA> --repo <repo>`
   exits 0: a file outside the lane's plan stops that lane's merge and is recorded; **you** revert it
   or ask the user (F89).
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

**Push only gated commits.** While the route is active, `scripts/push_guard.py` (a PreToolUse hook)
blocks a `git push` of any commit without a gate log in `<planning-dir>/lanes/` whose first `sha=`
line (within its first 20 lines) is `sha=<that commit> dirty=0` and whose last `exit=` line is
`exit=0` — the integrator's last log covers the main it returns; a commit you add after it needs
its own full gate first:
`{ echo "sha=$(git rev-parse HEAD) dirty=$(git status --porcelain --untracked-files=no | grep -c .)"; <full gate>; echo "exit=$?"; } > <planning-dir>/lanes/<name>-gate.log 2>&1`.
On a route activated with `--ci-harness <label>` the commit also needs a log of the CI's own suite,
`echo "harness=<label>"` after the `sha=` line — never a local stand-in for it (a stub in place of
the CI's database harness passed four times locally and failed four CI runs; F90).
Push as `git [-C <dir>] push <remote> <ref>…`: a push with no refspec, other git options before
`push`, a `GIT_*` variable, a `pushd`, `sudo`/`xargs`, a script, stdin or computed string fed to a
shell, a computed command name, or a `cd` to a directory the command computes (`cd "$(…)"`, a
variable it does not set) is held, since what it would send cannot be read from it.
**Every gate run — yours included — goes to such a log**, read by its last `exit=` line and a grep
for failing tests, never piped through `tail` or `head` (`failure-modes` F31): one lead piped 22
gates through `tail`, and one hid the lint error of a red commit. A gate log is never edited — a
log the guard refuses is rerun. **Why:** a lead pushed main twice ungated and both CI runs went
red, unnoticed for hours (`failure-modes` F56) — CI confirms a state proven green here; it never
discovers one.

**At L, review before the phase's last push; at any rung, before a push the user asks a review of**
(`sins/lead.md`, code mode; `route_state.py --activate --sins on` first, `--sins off` once it is
out): once the commit to push is gated, seven reviewers read what it sends against the remote's
tip — over 30 commits, one review per slice of at most 30, cut at lane merges — and reproduce each
other's highs; a claim a reproduction fails goes to a verifier that writes a test. Its verdict,
`<planning-dir>/reviews/p<P>-push<n>-verdict.md`, opens with `reviewed=<SHA> base=<SHA>
blocking=<n>`, `after=<fix SHAs>` and, when sliced, `slices=<from>..<to> …`; `push_guard.py` holds
the push until `blocking=0`, every commit after the reviewed one is on `after=`, the base is an
ancestor of the remote-tracking ref, and the slices cover every commit.
A new high is fixed by a fresh task group from the amended recommendation, or waived by the
user as a U-ruling; pre-existing highs go to the next phase's Lane 0. **Why:** a finished lane
whose full gate was ALL GREEN 25/25 still carried two new highs, and the review's second round struck a
first-proposed fix that would have crashed at every launch (`failure-modes` F70).

**Outward actions are the user's, each time.** A push, a PR closed or merged, a branch deleted, an
issue closed, a release: ask for each when it happens — an earlier answer authorizes only what its
option named. While a route is active the hook asks the user before your `gh pr close|merge`,
`gh issue close|delete`, `gh release create|delete|edit|upload`, `gh repo delete|archive|rename`, a
`gh api` write, `--delete-branch` or a remote branch delete by `git push`, and refuses them to every
route agent. **Why:** a lead closed nine
dependency-update PRs with `--delete-branch`, unasked, 16 minutes after the user's last answer
(`failure-modes` F81).

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
