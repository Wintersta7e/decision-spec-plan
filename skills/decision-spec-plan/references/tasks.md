# Any task the user hands you

The route is a shape for the work. Run the task the user named, at the rung its open decisions
need, and never swap in the skill's nearest stage. Where the user names one step ("hunt bugs",
"just review it", "no spec"), do that step, and offer the rest without running it. **Why:** asked
for a bug hunt, a lead recommended a ~5M review panel instead; the user: "Scratch 7 sins run".

| The user hands you | Stage 0 | The decision round | Then |
|---|---|---|---|
| **A bug** ("X is broken") | Reproduce it yourself: a test that fails at the reported SHA, and the root cause at file:line | S: the fix's options and the one you rule; the failing test is the first acceptance check | One plan, executed by fresh groups; the reproduction passing and the full gate green close it |
| **A bug hunt** ("find what's wrong in Y") | Hunters per `briefs/hunt-brief.md` (`prompts.md` §8): a failing reproduction per defect, measured, never argued; then the suspects check (§8c) | The user triages the reproduced findings and the checked suspects: keep or `backlog` (`user-questions.md`) | One S fix round of task groups for the kept findings, grouped by the files they touch, closed by the fix-regression check (§8b) |
| **A question, an investigation, a comparison** | Harvest plus probes that measure the answer | The decision document is the deliverable: options, evidence at file:line or by measurement, a recommendation | A spec and plan only when the user asks to build it |
| **A feature, a refactor, a phase** | As SKILL.md | As the rung table | As SKILL.md |
| **A review** (a PR/MR, a design, a review-fix round) | Rung S, always (`failure-modes` F50) | The steps below | |

A hunt runs at rung S. Its seats are `hunt-` agents: find-only and held so by the hook (F109), and
never harvesters. Price the whole hunt — its hunters and the suspects check — from `costs.md` and
record it with `route_state.py --budget` before the hunters go out: the gate checks the spend at
each dispatch and reserves nothing. The lead fixes nothing; each kept finding goes to a task group
(F68).

A review of a change, at S, rests its verdict on what it read and ran (F104):
1. Fetch the change and record its range in the index's header, `> **Review**: `<base-sha>..<head-sha>``
   (`templates.md` §1): the review covers every file `git diff --name-only` of that range lists.
2. Probe in a tree of the review's own — `git worktree add --detach <scratch-dir> <head-sha>` — never
   the lead's checkout or the branch under review: a test, a reproduction, the code run on the input
   a finding says breaks it. Record each probe in the Coverage section with its exit code.
3. Label each changed file in the Coverage section as you go: `Read in full`, `Diff read` or
   `Not read`. Tests, recordings, documentation and lockfiles are exempt.
4. The verdict says unfinished while any file is Not read or no probe has run;
   `decision_check.py` fails the index otherwise, and the hook refuses posting the review's
   comments while it fails.
5. Post the review as one structured comment, never several.

**Text the user's team reads** — a review, an MR description, a ticket, a note — follows that
project's rules, not the route's: its template or contributing file, the format the user named, and
the team's own terms, kept in the language the team writes them in, in a plain register. Before
drafting, find those rules or the user's earlier posts of that kind; write the text to a file, then
post it. **Why:** in five sessions users corrected posted text five times — several comments for
one review, a table they had asked for, a ticket in the wrong format, a translated term, a tone
that read as generated (F106).

Every shape keeps the route's verification:
- each code claim is re-verified before a ruling;
- each number carries its SHA;
- gate logs come from the gate itself;
- `test_check.py` runs at each merge;
- the lead never executes a plan task.

A small task stays small: rung S, with no harvester and no arbiter. It still runs the gates.
