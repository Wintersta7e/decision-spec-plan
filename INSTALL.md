# decision-spec-plan — install

**From the marketplace** (the README's two commands) the plugin installs as
`decision-spec-plan@decision-spec-plan`; skip to the settings below (agent teams, auto-compact
window, headless). Install one copy only: a marketplace copy beside a skills-directory copy loads
the plugin and its hooks twice. The rest of this section is the manual install from a clone.

`skills/decision-spec-plan/` is a Claude Code plugin that lives in the skills directory: the skill,
its two agents (`decision-spec-plan:dsp-deep`, `decision-spec-plan:dsp-mechanical`) and its hooks
(`hooks/hooks.json`) load together, as `decision-spec-plan@skills-dir`, in every session started
after it is in place:

    git archive HEAD skills/decision-spec-plan | tar -x --strip-components=1 -C ~/.claude/skills

`claude plugin list` then shows it under "Skills-directory plugins". Hooks load when a session
starts: a session already running keeps the hooks it started with. Without the hooks the route's
state hook (`route_state.py --hook`) and push guard (`push_guard.py`) stay off, and SKILL.md's claims
about them are false. Both act only for a session that ran `route_state.py --activate`; any other
session pays ~0.02 s per call. Turn it off with `claude plugin disable decision-spec-plan@skills-dir`.

**Upgrading**: the copy overwrites `agents/dsp-*.md`, so save each file's `tools:` line first if you
edited it, and put it back after. A file this package no longer ships stays behind: compare
`ls -R ~/.claude/skills/decision-spec-plan` with the package. Then run the hook suite (last
paragraph).

**From an install before the plugin** (hooks merged into `~/.claude/settings.json`, agents in
`~/.claude/agents/`), once, after copying: the old hook entries would run every hook twice, and the
old agents would stay dispatchable under their bare names. Remove the settings entries — back the
file up first:

    cp ~/.claude/settings.json ~/.claude/settings.json.bak
    jq '.hooks |= (with_entries(.value |= (map(.hooks |= map(select(.command | test("skills/decision-spec-plan/scripts") | not))) | map(select(.hooks | length > 0)))) | with_entries(select(.value | length > 0)))' ~/.claude/settings.json.bak > ~/.claude/settings.json

and delete `~/.claude/agents/dsp-deep.md`, `~/.claude/agents/dsp-mechanical.md` and
`~/.claude/skills/decision-spec-plan-workspace/`.

Agent teams are required: set `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` under `env` in
`~/.claude/settings.json`.

Set an auto-compact window of about 300000 for the lead's model, e.g.
`"modelSettings": {"claude-opus-5-5": {"autoCompactWindow": 300000}}` (or
`CLAUDE_CODE_AUTO_COMPACT_WINDOW`): without it leads grew to ~965k context, where every turn costs
~0.1M (SKILL.md, The route runs unattended). `dsp-deep` runs on the lead's model.

Headless (`claude -p`): set `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0`. Otherwise background agents
are stopped 10 minutes after the lead's last turn, and the lead ends its turn to wait for them.
A headless run has no user to answer the budget hold, so the hold lets dispatches through: cap the
spend with `claude -p --max-budget-usd <USD>` (it counts subagents; past the cap no new agent
starts and running background agents are stopped — a client-side estimate, and it can overshoot).

Requires Python 3.11+, bash, jq and git. `dsp-deep`'s memory cap uses `systemd-run --user`; without it
the agent falls back to `timeout` + `setsid`.

`agents/dsp-*.md` list no MCP tools — add any you want the route's agents to have (a documentation
server, say) to their `tools:` line.

Before editing the skill, and after: `bash ~/.claude/skills/decision-spec-plan/tests/hooks_test.sh`
(it tests the copy it sits in; throwaway repos only; fails if SKILL.md grows past 19,000 characters
— a compaction cuts it at 20,000).
