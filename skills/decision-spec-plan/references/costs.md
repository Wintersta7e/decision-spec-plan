# Costs — for the rung announcement and every gate

The announcement's expected cost is per role from this table, summed, from the newest run set that
measured the role. Each stage's wall-clock comes
from the last recorded run in the handoff — none recorded: run set B's one MR-review round at rung
L, all deep (harvest 44–63 min, framing review 17 min, decision agents 17–34 min), or "unknown" —
never an estimate.

| Role — median cost per agent | Run set A: 4 runs, 2026-09-24..10-01 | Run set B: 20 runs, 2026-09-24..10-03 | Run set F: 2 runs' Stage 5, 2026-10-14 |
|---|---|---|---|
| Harvester · decision agent | 1.1M · 1.5M | 3.4M · 2.1M (mechanical 0.5M · 0.6M) | — |
| Framing · seam or S review, as an agent (the second model costs no Claude usage) | — · 2.2M | 1.5M · 2.0M | — |
| Supersede markers · register folder | 4.1M · 1.2M | — | — |
| Spec author · reconciler · plan author | 1.7M · 1.3M · 3.2M | 1.9M · 2.0M · 2.2M | — |
| Execution: a whole-lane agent · one task group · a wave integrator (`execution.md`) | 7.2M (up to 37M) · — · — | 13–46M · 5.2M · — | — · 1.0M (49 groups, 0.1–4.4M; a group that compacted 2.4–4.4M) · 0.3M |
| Lead, one rung M or L run | 5–96M (96M ran three phases in one session) | 7–50M | Stage 5: 0.3–0.6M per task group dispatched |

**Stage 5**, per wave: its task groups × the group median, plus the lead per group, plus one
seven-sins review per push at M and L. Run set F's groups had orientation maps (`failure-modes` F67);
B's 5.2M predates them — about five times run set F's median. Record each wave's figure with
`route_state.py --budget` (`execution.md`).

**Rung S**: two MR reviews cost 11M and 13M (B) — review only, no execution. One S round with
execution cost 28.8M (run set D, `failure-modes` F68): lead 21.8M, five agents 7.0M, with the lead
executing post-lane work itself. Announce an S build as the lead's writing plus its execution
priced per task group from the row above.

**Seven-sins review** (`sins/lead.md`; M and L: one spec review per phase, one code review per
push). Code mode, measured twice at rung M with reproductions (run set F): 9 commits cost 8.4M in
~15 min (agents 6.6M, lead ~1.8M), 31 commits 13.2M in ~45 min (agents 10.4M, lead ~2.8M) — announce
~8M up to 10 commits and ~13M up to 30, more above. A whole 1,328-file repository with no focus, before
reproductions were added, cost 17.6M in 40 min (run set E: agents 16.7M at 1.8–3.1M per sin, lead
0.8M). Spec mode is unmeasured: announce 17.6M and 40 min until one is recorded. Record each
review's `usage_report.py` figures in the handoff.

Units are Opus-input-equivalent tokens: cache read ×0.1, cache write ×1.25, output ×5, mechanical
(Sonnet) ×0.6. Cache reads are 68–90% of a role's cost — every turn re-sends the agent's whole
context — so cost follows turns × context size, not the number of steps. `scripts/usage_report.py`
prints a running round's actual figures; quote them at each gate.
