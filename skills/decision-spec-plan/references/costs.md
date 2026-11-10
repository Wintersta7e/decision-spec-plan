# Costs — for the rung announcement and every gate

The announcement's expected cost is per role, summed: the project's own medians first, measured on
its last route by `usage_report.py` (`--groups` for task groups); for a role it has not run, the
table below. Each stage's wall-clock comes from the last recorded run in the handoff — none
recorded: run set B's one MR-review round at rung L, all deep (harvest 44–63 min, framing review
17 min, decision agents 17–34 min), or "unknown" — never an estimate.

**Units and dollars.** `usage_report.py` and `route_state.py --budget` count M units (Opus 5.5 input
tokens). **1M units ≈ $4 at API prices** (read 2026-10-17), so $ = M × 4; quote both. Rates and
the conversion from older figures: Sources, below.

## The table — median cost per agent or per route (newest measurement of each)

| Item | M units | ≈ USD | Measured |
|---|---|---|---|
| Harvester | 0.9M | $3.60 | J, 2026-10-21..27 |
| Decision agent | 0.8M | $3.20 | J |
| Harvester or decision agent on the mechanical tier (Sonnet) | 0.3M | $1.20 | B, 2026-09-24..10-03 |
| Framing, seam or S review, as an agent (the second model costs no Claude usage) | 0.6M | $2.40 | J (35 agents); H's S review agent the same |
| Supersede markers · register folder | 0.2M · 0.4M | $0.80 · $1.60 | J |
| Spec author · reconciler · plan author | 1.2M · 1.1M · 1.5M | $4.80 · $4.40 · $6.00 | J |
| Stage 5 task group (`execution.md`) | 1.0M (p90 1.8M, max 3.2M) | $4.00 (p90 $7.20) | J, 210 groups |
| Wave integrator | 0.6M | $2.40 | J |
| Lead, Stage 5 | 0.2–0.4M per task group dispatched | $0.80–1.60 | F, 2026-10-14 |
| Lead, one rung M or L run | 5–35M; ≈0.5M per agent dispatched, 32% of all cost | $20–140 | B; J |
| Claim-only verifier (`prompts.md` §1f) | ~0.6M as a `dsp-deep` agent; 0 on the second model | ~$2.40 | unmeasured: the S review agent's figure |
| Rung S review of a merge request, no harvester | ≈2.6M (0.9–5.8M) | ≈$10.40 | J |
| Rung S review, all | 4.2M (1.6–10.8M); with a harvester 4.9–8.0M (`failure-modes` F87) | $16.80 | I, 2026-10-07..20 |
| **Rung S build, with execution** | **5.0M in 72 min** — lead 1.8M, 7 agents 3.1M | **$20.32** | **r5 clean room, 2026-11-02** |
| Rung S build, earlier clean room | 5.7M in 1 h 45 (lead 2.8M, S review 0.6M, six groups 2.3M); 6.7M in 1 h 54 (lead 3.8M, five groups) | $22.80; $26.80 | H, 2026-10-17 (`failure-modes` F85) |
| The same S build task, plain Claude Code (no skill) | ≈1.8M ($7.29 ÷ 4) in 19 min | $7.29 | r5 clean room, 2026-11-02 |
| Seven-sins code review | ~5M up to 10 commits; ~8.5M a slice of up to 30 | ~$20; ~$34 | F (with since-removed debate) |
| Seven-sins spec review | ~11M, 40 min | ~$44 | unmeasured: E's whole-repository figure |
| Seven-sins review with its fix round | 56.7M in ~7 h | $227 | G (`failure-modes` F79) |

## Pricing a stage

**Stage 5**: its task groups × the group median (the project's own, from
`usage_report.py --groups` on its last route, before the table's), plus the lead per group, plus at
L one seven-sins review before the phase's last push (and any review the user asks for). The
route's figure — every stage's agents and reviews, the lead, and Stage 5 — is recorded once, in M,
at the go-ahead with `route_state.py --budget` (`execution.md`).

**Rung S**: announce an S build as the lead's writing plus its execution priced per task group. A
review-fix round is the review, plus its findings' task groups — findings ÷ the tasks a group fits
(`execution.md`) — at the group median, plus the lead ~0.3M a group. An S round whose lead executed
post-lane work itself cost ~19M (D, `failure-modes` F68): the lead never executes.

**Seven-sins review** (`sins/lead.md`; at L one spec review in Stage 3 and one code review before
the phase's last push; other reviews only when the user asks): over 30 commits, one review per
slice, so announce the slices × ~8.5M; one claim-only verifier per expected dispute.

In these units the turn is the cost: a lead's read turn measured ~25k units — 27% re-reading the
context, 40% cache write, 33% output — so one turn fewer saves far more than a shorter resident
text. `scripts/usage_report.py` prints a running round's actual figures; quote them at each gate,
and record each review's in the handoff.

## Sources

**Rates.** Units are Opus 5.5 input tokens: cache read ×0.05, 5-minute cache write ×1.25, 1-hour ×2,
output ×5; Sonnet 5.5 ×0.5 of that, Haiku 5.5 ×0.025 (`usage_report.py`). Every run set below was
measured in the older units (cache read ×0.1, Sonnet ×0.6) and is converted by its role's ratio of
new to old units, measured on 324 local route agents and 17 leads (2026-10-17): task group 0.59,
integrator 0.60, harvester 0.62, sin reviewer 0.64, decision agent 0.65, plan author 0.66, spec
author and register folder 0.68, lead 0.69, reconciler 0.72, framing or seam review 0.74, markers
0.93; a mechanical (Sonnet) role ×0.83 more. The `failure-modes` evidence stays in the older units.
Run sets H, G and the r5 clean room were measured in today's units.

**Run sets, per role** (converted):

| Role — median cost per agent | A: 4 runs, 2026-09-24..10-01 | B: 20 runs, 2026-09-24..10-03 | F: 2 runs' Stage 5, 2026-10-14 | J: 20 runs on one project, 2026-10-21..27 |
|---|---|---|---|---|
| Harvester · decision agent | 0.7M · 1.0M | 2.1M · 1.4M (mechanical 0.3M · 0.3M) | — | 0.9M · 0.8M |
| Framing · seam or S review, as an agent | — · 1.6M | 1.1M · 1.5M | — | 0.6M (both, 35 agents) |
| Supersede markers · register folder | 3.8M · 0.8M | — | — | 0.2M · 0.4M |
| Spec author · reconciler · plan author | 1.2M · 0.9M · 2.1M | 1.3M · 1.4M · 1.5M | — | 1.2M · 1.1M · 1.5M |
| Execution: a whole-lane agent · one task group · a wave integrator | 4.2M (up to 22M) · — · — | 8–27M · 3.1M · — | — · 0.6M (49 groups, 0.06–2.6M; a group that compacted 1.4–2.6M) · 0.2M | — · 1.0M (210 groups, p90 1.8M, max 3.2M) · 0.6M |
| Lead, one rung M or L run | 3–66M (66M ran three phases in one session) | 5–35M | Stage 5: 0.2–0.4M per task group dispatched | 0.5M per agent dispatched; 32% of all cost |

Run sets F and J had orientation maps (`failure-modes` F67); B's 3.1M per task group predates them.
J's 1.0M over 210 groups replaces F's 0.6M over 49.

**Whole routes.** Rung S: two MR reviews cost ~8M and ~9M (B) — review only, no execution; 15
reviews of another developer's MR (I) a median 4.2M (1.6–10.8M), the five with no harvester 1.6–2.6M
against 4.9–8.0M for the four with one; with no harvester dispatched, J's a median ≈2.6M
(0.9–5.8M). D's S round with execution: lead ~15M, five agents ~4M, the lead executing post-lane
work itself. H: two S builds of one task, median task group 0.4M and 11 min (first) and 0.5M
(second). The r5 clean room (2026-11-02, at the skill's commit 8b72c97): one S build, $20.32 /
5.0M / 72 min, lead 1.8M and 7 agents 3.1M; plain Claude Code on the same task $7.29 in 19 min. A
second build of the same task with the same skill text (r8, 2026-11-02): $18.05 in 68 min. G:
a seven-sins review with its fix round (the lead never loaded the skill) — lead 7.8M, seven sin
reviewers 11.2M, 27 task groups 30.6M (median 1.1M, 0.2–1.9M; 78 commits), three integrators 3.7M,
hook sessions 1.6M.

**Seven-sins review.** Code mode, measured twice at rung M with reproductions and the since-removed
debate (F): 9 commits cost ~5.4M in ~15 min (agents ~4.2M, lead ~1.2M), 31 commits ~8.5M in ~45 min
(agents ~6.6M, lead ~1.9M). A whole 1,328-file repository with no focus, before reproductions were
added, cost ~11M in 40 min (E: agents ~10.6M at 1.1–2.0M per sin, lead ~0.6M). Spec mode is
unmeasured: ~11M and 40 min until one is recorded.
