# Seven-sins review — the lead's procedure (rung L's phase end, or when the user asks)

**Asked for on its own** ("summon the sins team"): read `SKILL.md` first and run it as a route —
a review and its fix round are rung S (its rung table): announce the headcount and cost, then
`route_state.py <planning-dir> --phase <P> --repo <repo> --activate --rung S`. The hook refuses a
`dsp-deep` dispatch from a session with no active route (`failure-modes` F79).

Seven `dsp-deep` reviewers, one sin and one domain each (`pride` architecture/API, `greed`
performance/cost, `lust` UX, `envy` prior art, `gluttony` deps/docs/config/CI/logs, `wrath`
security, `sloth` simplification), review independently and reproduce each other's high findings;
a claim a reproduction fails, or one you would not act on, goes to a claim-only verifier that writes
a test (`prompts.md` §1f) — never a debate, never a vote: the verdict is the union of what stands.
`protocol.md` here is their contract — read it before the first dispatch. You never review
yourself: dispatch, assign reproductions, send disputed claims to verifiers, merge, rule.

| Mode | When | Target | Verdict |
|---|---|---|---|
| **spec** | At L, Stage 3, dispatched with the reconcilers (two messages — the 8-per-message limit); at any rung when the user asks | the phase's spec sections, plus the code they change at the main branch's HEAD | `<planning-dir>/reviews/p<P>-spec-verdict.md` |
| **code** | At L before the phase's last push; at any rung before a push the user asks a review of. With `--sins on`, `push_guard.sh` holds the push until a verdict covers it | a detached worktree at the gated commit to push; base = the remote's tip; over 30 commits, one review per slice | `<planning-dir>/reviews/p<P>-push<n>-verdict.md` |

**Why both.** A finished lane whose full gate was ALL GREEN 25/25 still carried two new highs — a
crash on a crafted repository, a migration that left a view blank until a manual rescan — and the
second round struck the first-proposed fix of each, one of which would have crashed at every launch
(`failure-modes` F70). The second high was designed in: its spec section and its plan agreed with each other, so
reconciliation, which reads for consistency, could not see it (F71). **Why slices and no debate.**
Review recall collapses as a diff grows (a published benchmark: F1 0.657 under 10 changed lines,
0.043 over 150), so a phase's push is reviewed slice by slice; debate gains less than independent
passes at equal budget, and one executed test settles what argument cannot (F95).

## 1. Preflight — one Bash call, stop at the first failure
- `[ "$CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS" = 1 ]` — the sins message each other by name. Unset →
  stop and tell the user to set it in `settings.json` `env`.
- `protocol.md` and the seven persona files (`pride.md` … `sloth.md`) exist in this directory.
- `mkdir -p <planning-dir>/reviews/<name>/probes/{pride,greed,lust,envy,gluttony,wrath,sloth}`
  (`<name>` = `p<P>-spec` or `p<P>-push<n>`); keep its absolute path.
- **code**: the SHA is the commit to push, already gated (`execution.md`). `git fetch <remote>`; the
  base is `git merge-base <remote>/<branch> <SHA>` (a branch not yet on the remote: its merge-base
  with `<remote>/<main>`), with `git rev-list --count <base>..<SHA>` commits.
  `git worktree add --detach <repo>-review-<short SHA> <SHA>` is the target: it stays put while the
  next wave's integrator moves the main branch. **Over 30 commits, cut slices**: walk
  `git rev-list --first-parent --reverse <base>..<SHA>` and end a slice at each lane's merge, or
  where the next step would pass 30 commits; a single merge of more than 30 splits along its lane's
  own history (`<merge>^1..<merge>^2~<k>`, `<merge>^2~<k>..<merge>^2`). Each slice is
  `<from>..<to>`, at most 30 commits, and together they hold every commit — merges aside, both
  counts — and `push_guard.sh` checks both.
- **spec**: the section list, the spec dir, the scope section, the arbiter, and the main branch's
  HEAD SHA, which the code side is read at.

Record the review in the handoff's *in flight* block. Its cost is in the rung announcement
(`costs.md`): no separate go. The push itself stays an outward action — yours and the user's.

## 2. Round 1 — seven dispatches in one message, per slice
`subagent_type: "decision-spec-plan:dsp-deep"`, `name` = `<sin>-<name>` (`wrath-p4-push2`; sliced, `<name>` ends
`-s<k>` and the run dir is `<run dir>/s<k>`), `run_in_background: true`. Sliced, each slice is its
own review with its own seven, dispatched once the previous slice's seven have returned; Base and
Focus are the slice's range. A bare sin name collides with an earlier review's idle reviewers: the tool renames the new
one, and a message to the bare name wakes the old one, which wrote into its closed report
(`failure-modes` F73). The prompt does not end with `prompts.md`'s closing lines — the protocol
carries the skeleton, the one reply and the probe location:

    Role: seven-sins reviewer, <mode> mode. Read <skill-dir>/references/sins/<sin>.md, your persona,
    and <skill-dir>/references/sins/protocol.md, your contract, before anything else.
    Target: <code: <worktree path>, HEAD <SHA>, clean | spec: sections <list> in <spec dir>; scope
    section <path>, arbiter <path>; code at <repo> HEAD <SHA>>.
    Base: <SHA> (<remote>/<branch>), <n> commits in <base>..<SHA> | none — Age is `—`.
    Reviewers: pride-<name>, greed-<name>, lust-<name>, envy-<name>, gluttony-<name>,
    wrath-<name>, sloth-<name>.
    Run dir: <run dir>. Focus: <code: the commits in <base>..<SHA> and the code they touch, then
    your whole domain where they reach | spec: these sections as the design about to be built>.
    Write your Round 1 report, return, and wait for `reproduce` before Round 2.

As each returns, one line to the user: the sin and its counts by severity. A return without a
report file or without a `pending:` line: message that sin once, naming what is missing.

## 3. Round 2 — reproductions, then verifiers
When all seven reports exist, read their Findings tables and assign every critical and high finding
to one sin other than its owner: a rival named in the owner's persona whose domain the evidence
touches, no sin more than two. Send `reproduce` to all seven in one message (seven `SendMessage`
calls, one text): "reproduce — the seven reports are in <run dir>; protocol.md Round 2 applies.
Reproductions: REPRODUCE <finding ID> → <sin>, …" (or "Reproductions: none"). Never relay or
summarise between sins. An assigned reproduction missing from its sin's table at `pending: none`:
message once; still missing → the verdict marks the finding "not reproduced".

**A disputed finding** — a FAILED or PARTIAL reproduction the owner did not amend, or a finding you
would not act on — goes to a claim-only verifier: `decision_check.py <run dir> --verifier <ID> --sha
<reviewed SHA> --from <run dir>/<sin>.md` writes the prompt (`prompts.md` §1f); send it unchanged.
REFUTED withdraws the finding; UPHELD keeps it standing; NO-TEST stands too and goes to the user
with both sides' evidence when it would block. Nothing is withdrawn by count or by argument.

## 4. The verdict
Re-run the preflight's `git` commands first: a moved HEAD or a dirty tree means a sin wrote to the
target, and that leads the report. Read the seven reports (sliced: every slice's). **A reproduction
is recorded twice** — the reproducer's Result must match the owner's Evidence cell; a mismatch means
one side recorded a reply it never received (`failure-modes` F72): send that claim to a verifier.
The verdict is the union of every slice's standing findings.

    reviewed=<full SHA reviewed> base=<full base SHA> blocking=<n>        (code mode, line 1)
    after=                                                                (code mode, line 2)
    slices=<from>..<to> …                                                 (code mode over 30 commits)
    # Seven-sins verdict — <mode> · <repo> @ <short SHA> (base <short SHA> | no base)
    ## New highs — block this push   code: each standing new critical or high, its commit, its
                                     reproduction result, and its fix SHA or the user's waiver
    ## Standing findings             by severity: ID, owner, Age, final text, reproduction and
                                     verifier result
    ## Withdrawn or amended          finding, on which reproduction or REFUTED verdict
    ## Unresolved                    NO-TEST findings: both sides' evidence, your ruling or the question
    ## Routed                        where each standing finding goes (below)
    ## Strengths · Scorecard         the reports' Strengths; the scorecard per sin: findings,
                                     reproductions run, findings upheld and refuted

`blocking` counts the new criticals and highs neither fixed nor waived. The stamp lines take full
40-character SHAs; `push_guard.sh` reads them within the first 10 lines.

## 5. Outcomes
**code mode:**
- **A new critical or high blocks the push.** The user may waive it — record a U-ruling with their
  words under New highs. Otherwise a fresh task group (`execution.md`; never you) in a worktree
  branched from the reviewed SHA: its tasks are the standing findings' **final, reproduction-amended**
  recommendations, each with the test that fails today; it re-runs each finding's probe and records
  that it no longer reproduces, then runs the full gate into a log. Merge it, then set `after=` to
  every commit in `<reviewed>..<new SHA>` and lower `blocking`. **`after=` lists only fixes for this
  verdict's findings** — the guard cannot tell a fix from a feature, so a later wave's commits on
  that line would push unreviewed code; they need the next review.
- A pre-existing critical or high → the next phase's Lane 0 (the handoff's carry list); one that
  loses or exposes data goes to the user now, with a proposed fix (Stage 0's rule).
- Medium and low → the handoff's known-unfixed list, each with an owner — **except** one that makes
  a claim this push publishes false (README, changelog, help text, a test name stating behaviour)
  or leaks local-only material into it (planning-dir paths, spec section numbers, local paths): it
  joins the fix group, because once pushed it is public.
- Remove the review worktree (`git worktree remove`); the run dir stays.

**Both modes:** once the verdict is written, `TaskStop` the seven reviewers — an idle reviewer
still answers to its name (F73).

**spec mode:** rule the verdict **together with the reconcilers' findings**, as numbered rulings in
the plan index (`templates.md` §4): the finding, the ruling, which plan carries it; the reading map's
reconcile column names it. A finding against a U-ruling, or one whose fix changes what gets built,
is a question for the user — at most four per `AskUserQuestion`, ranked, each option stating its
consequence (SKILL.md Stage 1 step 5).

**Then report to the user**: the verdict path, the new highs (code) or the rulings made (spec),
standing counts by severity, the open questions, and anything that broke protocol (a write to the
target, a finding without evidence, a measured number without its probe, more than four messages in
one exchange).
