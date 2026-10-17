# Seven-sins review — the lead's procedure (rungs M and L)

Seven `dsp-deep` reviewers, one sin and one domain each (`pride` architecture/API, `greed`
performance/cost, `lust` UX, `envy` prior art, `gluttony` deps/docs/config/CI/logs, `wrath`
security, `sloth` simplification), review independently, reproduce each other's high findings and
debate by message; you merge one verdict. `protocol.md` here is their contract — read it before the
first dispatch. You never review yourself: dispatch, open the debate, watch the pending lines,
merge, rule.

| Mode | When | Target | Verdict |
|---|---|---|---|
| **spec** | Stage 3, dispatched with the reconcilers (two messages — the 8-per-message limit) | the phase's spec sections, plus the code they change at the main branch's HEAD | `<planning-dir>/reviews/p<P>-spec-verdict.md` |
| **code** | Stage 5, before **every** push; `push_guard.sh` holds the push until a verdict covers it | a detached worktree at the gated commit to push; base = the remote's tip | `<planning-dir>/reviews/p<P>-push<n>-verdict.md` |

**Why both.** A finished lane whose full gate was ALL GREEN 25/25 still carried two new highs — a
crash on a crafted repository, a migration that left a view blank until a manual rescan — and the
debate struck the first-proposed fix of each, one of which would have crashed at every launch
(`failure-modes` F70). The second high was designed in: its spec section and its plan agreed with each other, so
reconciliation, which reads for consistency, could not see it (F71). Each push costs one review, so
fewer pushes cost fewer reviews; say so at the rung announcement.

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
  next wave's integrator moves the main branch.
- **spec**: the section list, the spec dir, the scope section, the arbiter, and the main branch's
  HEAD SHA, which the code side is read at.

Record the review in the handoff's *in flight* block. Its cost is in the rung announcement
(`costs.md`): no separate go. The push itself stays an outward action — yours and the user's.

## 2. Round 1 — seven dispatches in one message
`subagent_type: "dsp-deep"`, `name` = `<sin>-<name>` (`wrath-p4-push2`), `run_in_background:
true`. A bare sin name collides with an earlier review's idle reviewers: the tool renames the new
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
    Write your Round 1 report, return, and wait for `debate open` before Round 2.

As each returns, one line to the user: the sin and its counts by severity. A return without a
report file or without a `pending:` line: message that sin once, naming what is missing.

## 3. Round 2 — the debate
When all seven reports exist, read their Findings tables and assign every critical and high finding
to one sin other than its owner: a rival named in the owner's persona whose domain the evidence
touches, no sin more than two. Send `debate open` to all seven in one message (seven `SendMessage`
calls, one text): "debate open — the seven reports are in <run dir>; protocol.md Round 2 applies.
Reproductions: REPRODUCE <finding ID> → <sin>, …" (or "Reproductions: none").

Then watch. Keep each sin's latest pending line; every return replaces it. Never relay, summarise or
join the debate.
- All seven latest say `pending: none` → the debate is over; go to 4.
- Everyone idle but a line still awaits a sin whose latest is `pending: none` → message that sin
  once: "<sender> awaits your reply on <id> — protocol.md Round 2." Still stuck after its next
  return → record the exchange as unresolved.
- An assigned reproduction missing from its sin's Reproductions table at `pending: none` → message
  once. Still missing → the verdict marks the finding "not reproduced".

## 4. The verdict
Re-run the preflight's `git` commands first: a moved HEAD or a dirty tree means a sin wrote to the
target, and that leads the report. Read the seven reports. **Every exchange is recorded twice** —
the challenger's Outcome must match the owner's Verdict, a reproducer's Result the owner's Evidence
cell; a mismatch means one side recorded a reply it never received (`failure-modes` F72): read both
sides' cited evidence and rule it as unresolved. An exchange that ended in a REJECT against a
rebuttal: read the cited evidence and rule, or make it a question for the user.

    reviewed=<full SHA reviewed> base=<full base SHA> blocking=<n>        (code mode, line 1)
    after=                                                                (code mode, line 2)
    # Seven-sins verdict — <mode> · <repo> @ <short SHA> (base <short SHA> | no base)
    ## New highs — block this push   code: each standing new critical or high, its commit, its
                                     reproduction result, and its fix SHA or the user's waiver
    ## Standing findings             by severity: ID, owner, Age, final text, reproduction result,
                                     the challenges it survived
    ## Withdrawn or amended          finding, challenger, outcome, on what evidence
    ## Unresolved                    both sides' evidence, your ruling or the question
    ## Routed                        where each standing finding goes (below)
    ## Overlaps · Strengths · Scorecard   as protocol.md defines them; the scorecard per sin:
                                     findings, reproductions run, challenges won/lost

`blocking` counts the new criticals and highs neither fixed nor waived. Both stamp lines take full
40-character SHAs; `push_guard.sh` reads them within the first 10 lines.

## 5. Outcomes
**code mode:**
- **A new critical or high blocks the push.** The user may waive it — record a U-ruling with their
  words under New highs. Otherwise a fresh task group (`execution.md`; never you) in a worktree
  branched from the reviewed SHA: its tasks are the standing findings' **final, debate-amended**
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
