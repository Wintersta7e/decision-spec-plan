#!/usr/bin/env bash
# Tests for the route's hooks on throwaway repositories: push_guard.sh (PreToolUse:Bash) and
# `route_state.py --hook` (PostToolUse, UserPromptSubmit, SessionStart). Never touches a live
# project; HOME points at a temp dir so the session registry is a throwaway too.
# Usage: hooks_test.sh   — prints one line per case and exits non-zero on any failure.
#        SCRIPTS=<dir> hooks_test.sh — test a staged copy.

set -uo pipefail
SCRIPTS=${SCRIPTS:-~/.claude/skills/decision-spec-plan/scripts}
SCRIPTS=$(eval echo "$SCRIPTS")
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
FAIL=0
export HOME=$T/home
mkdir -p "$HOME"
G=(-c user.name=t -c user.email=t@t)

R=$T/repo
git init -q -b main "$R"
git -C "$R" "${G[@]}" commit -q --allow-empty -m one
git -C "$R" "${G[@]}" commit -q --allow-empty -m two
git -C "$R" branch feature HEAD~1
git -C "$R" worktree add -q "$T/wt" feature
P=$R/.plan
mkdir -p "$P/lanes" "$P/plans" "$P/decisions/phase1" "$P/spec"
MAIN=$(git -C "$R" rev-parse main)

ok() { echo "ok    $*"; }
bad() {
	echo "FAIL  $*"
	FAIL=1
}

guard() { # expected-exit cwd command
	local out code
	out=$(jq -n --arg c "$3" --arg d "$2" '{tool_input: {command: $c}, cwd: $d}' | bash "$SCRIPTS/push_guard.sh" 2>&1)
	code=$?
	if [ "$code" = "$1" ]; then ok "guard $1  $3"; else
		bad "guard want $1 got $code  $3"
		echo "$out" | sed -n '1,3p'
	fi
}

LAST=""
RS=$SCRIPTS/route_state.py
hook() { # expect(silent | report | delta | /regex/ | deny:regex) json
	local out want=$1
	out=$(echo "$2" | python3 "$RS" --hook 2>&1)
	LAST=$out
	case "$want" in
	silent) [ -z "$out" ] ;;
	report) jq -e '.hookSpecificOutput.additionalContext | test("route state ·")' <<<"$out" >/dev/null ;;
	delta) jq -e '.hookSpecificOutput.additionalContext | test("changed between")' <<<"$out" >/dev/null ;;
	/*/) jq -e --arg r "${want:1:-1}" '.hookSpecificOutput.additionalContext | test($r)' <<<"$out" >/dev/null ;;
	deny:*) jq -e --arg r "${want:5}" '.hookSpecificOutput | .permissionDecision == "deny" and (.permissionDecisionReason | test($r))' <<<"$out" >/dev/null ;;
	esac
	if [ $? = 0 ]; then ok "hook  $want  $2"; else
		bad "hook want $want  $2"
		echo "$out" | sed -n '1,4p'
	fi
}
unthrottle() { rm -f "$HOME/.claude/dsp-routes/"*.checked; }
ev() { # event session [extra json fields]
	echo "{\"hook_event_name\":\"$1\",\"session_id\":\"$2\",\"cwd\":\"/tmp\"${3:+,$3}}"
}

# --- no route active: everything passes, the hook is silent
guard 0 "$R" "git push origin main"
hook silent "$(ev PostToolUse s1 '"tool_name":"Agent"')"

out=$(cd "$R" && env -u CLAUDE_CODE_SESSION_ID python3 "$SCRIPTS/route_state.py" "$P" --phase 1 --repo "$R" --activate)
[ $? = 1 ] && [ -f "$R/.git/dsp-route.json" ] && grep -q "CLAUDE_CODE_SESSION_ID is unset" <<<"$out" &&
	ok "activate without a session id: marker written, exit 1, says so" || bad "activate without a session id: $out"
hook silent "$(ev PostToolUse s1 '"tool_name":"Read"')"

out=$(CLAUDE_CODE_SESSION_ID=s1 python3 "$SCRIPTS/route_state.py" "$P" --phase 1 --repo "$R" --sections 1- --activate)
[ -f "$HOME/.claude/dsp-routes/s1.json" ] && grep -q '"--main", "main"' "$R/.git/dsp-route.json" &&
	ok "activate registered s1, --main resolved to main" || bad "activate s1: $out"

# --- route active, no gate log
guard 0 "$R" "ls -la"
guard 0 "$R" 'grep -rn "git push" .'
guard 2 "$R" "git push origin main"
guard 2 "$R" "git push"
guard 2 "/tmp" "cd $R && git push origin main"
guard 2 "/tmp" "git -C $R push origin main"
guard 2 "$T/wt" "git push origin feature"
guard 2 "$R" "git push --tags"
guard 0 "$R" "git push --dry-run origin main"
guard 0 "$R" "git push origin --delete old"
guard 0 "$R" "git push origin :old"
guard 0 "$R" "DSP_SKIP_PUSH_GUARD=1 git push origin main"
# where the push runs: relative, chained and quoted `cd`s resolve from the cwd; an unresolvable
# one is skipped, never replaced by the cwd (that blocked an agent's push in its throwaway repo)
guard 2 "$T" "cd repo && git push origin main"
guard 2 "/tmp" "cd $T && cd repo && git push origin main"
guard 2 "/tmp" "cd \"$R\" && git push origin main"
guard 2 "$R" "echo abcd /tmp; git push origin main"
guard 0 "$R" 'S=/tmp/x && cd $S && git push origin main'
guard 0 "$R" "cd /no-such-dir-dsp && git push origin main"

# --- gate logs: red, dirty, then green for main only
printf 'sha=%s dirty=0\n...\nexit=1\n' "$MAIN" >"$P/lanes/red-gate.log"
guard 2 "$R" "git push origin main"
printf 'sha=%s dirty=3\n...\nexit=0\n' "$MAIN" >"$P/lanes/dirty-gate.log"
guard 2 "$R" "git push origin main"
printf 'sha=%s dirty=0\nok\nexit=0\n' "$MAIN" >"$P/lanes/wave1-int-gate.log"
guard 0 "$R" "git push origin main"
guard 0 "$R" "git push origin HEAD:main"
guard 0 "$R" "git push -u origin main 2>&1"
guard 0 "$R" "git push -o ci.skip origin main"
guard 0 "/tmp" "cd $R && git push origin main"
guard 2 "$R" "git push origin main feature"
guard 2 "$T/wt" "git push origin feature"
# a gate whose codegen/build steps print before the sha= line (one measured at line 6)
FEAT=$(git -C "$R" rev-parse feature)
{
	printf 'build %s\n' $(seq 20)
	printf 'sha=%s dirty=0\nok\nexit=0\n' "$FEAT"
} >"$P/lanes/late-gate.log"
guard 2 "$T/wt" "git push origin feature"
{
	printf 'build %s\n' $(seq 5)
	printf 'sha=%s dirty=0\nok\nexit=0\n' "$FEAT"
} >"$P/lanes/late-gate.log"
guard 0 "$T/wt" "git push origin feature"
rm "$P/lanes/late-gate.log"

# --- rung M: a gated push also needs a pre-push review's verdict (failure-modes F70)
out=$(CLAUDE_CODE_SESSION_ID=s1 python3 "$SCRIPTS/route_state.py" "$P" --phase 1 --repo "$R" --sections 1- --activate --rung M)
grep -q '"rung": "M"' "$R/.git/dsp-route.json" && grep -q "rung M: push_guard.sh" <<<"$out" &&
	ok "activate --rung M: rung in the marker, announced" || bad "activate --rung M: $out"
mkdir -p "$P/reviews"
verdict() { printf '# pre-push review\n%s\n' "$@" >"$P/reviews/w2-verdict.md"; }
ONE=$(git -C "$R" rev-parse main~1)
TREE=$(git -C "$R" rev-parse "main^{tree}")
REV=$(git -C "$R" "${G[@]}" commit-tree "$TREE" -p "$MAIN" -m reviewed)
FIX=$(git -C "$R" "${G[@]}" commit-tree "$TREE" -p "$REV" -m fix)
UNG=$(git -C "$R" "${G[@]}" commit-tree "$TREE" -p "$MAIN" -m ungated)
git -C "$R" update-ref refs/heads/rel "$FIX"
git -C "$R" update-ref refs/heads/ung "$UNG"
printf 'sha=%s dirty=0\nok\nexit=0\n' "$FIX" >"$P/lanes/rel-gate.log"
guard 2 "$R" "git push origin main"
verdict "reviewed=$MAIN base=$ONE blocking=1"
guard 2 "$R" "git push origin main"
verdict "reviewed=$MAIN base=$ONE blocking=0"
guard 0 "$R" "git push origin main"
guard 0 "$R" "git push origin HEAD:main"
verdict "reviewed=${MAIN:0:12} base=${ONE:0:12} blocking=0"
guard 2 "$R" "git push origin main"
# a fix committed after the review: covered only when listed on after=
verdict "reviewed=$REV base=$MAIN blocking=0"
guard 2 "$R" "git push origin rel"
verdict "reviewed=$REV base=$MAIN blocking=0" "after=$FIX"
guard 0 "$R" "git push origin rel"
verdict "reviewed=$MAIN base=$ONE blocking=0" "after=$REV,$FIX"
guard 0 "$R" "git push origin rel"
# the remote's tip behind the base: commits older than the base would go out unreviewed
git -C "$R" update-ref refs/remotes/origin/rel "$ONE"
verdict "reviewed=$REV base=$ONE blocking=0" "after=$FIX"
guard 0 "$R" "git push origin rel"
verdict "reviewed=$REV base=$MAIN blocking=0" "after=$FIX"
guard 2 "$R" "git push origin rel"
guard 2 "$R" "git push origin rel:rel"
guard 0 "$R" "git push origin rel:other"
git -C "$R" update-ref -d refs/remotes/origin/rel
rm "$P/reviews/w2-verdict.md"
guard 0 "$R" "DSP_SKIP_REVIEW=1 git push origin main"
guard 2 "$R" "DSP_SKIP_REVIEW=1 git push origin ung"
guard 0 "$R" "DSP_SKIP_PUSH_GUARD=1 git push origin ung"
CLAUDE_CODE_SESSION_ID=s1 python3 "$SCRIPTS/route_state.py" "$P" --phase 1 --repo "$R" --sections 1- --activate --rung S >/dev/null
guard 0 "$R" "git push origin main"
CLAUDE_CODE_SESSION_ID=s1 python3 "$SCRIPTS/route_state.py" "$P" --phase 1 --repo "$R" --sections 1- --activate >/dev/null
guard 0 "$R" "git push origin main"
grep -q rung "$R/.git/dsp-route.json" && bad "a marker without --rung keeps a rung" || ok "a marker without --rung has none"
git -C "$R" update-ref -d refs/heads/rel
git -C "$R" update-ref -d refs/heads/ung
rm -r "$P/reviews" "$P/lanes/rel-gate.log"

# --- the state hook: who it speaks to
hook report "$(ev PostToolUse s1 '"tool_name":"Agent"')"
hook silent "$(ev PostToolUse s1 '"tool_name":"Read"')" # throttled
unthrottle
hook silent "$(ev PostToolUse s1 '"tool_name":"Read"')" # nothing changed
hook silent "$(ev PostToolUse s1 '"tool_name":"Read","agent_id":"a1"')"
hook silent "$(ev PostToolUse s2 '"tool_name":"Read"')" # a session that never activated
hook silent "$(ev UserPromptSubmit s1 '"prompt":"what is left on the todo?"')"
hook silent "$(ev UserPromptSubmit s1 '"prompt":"<task-notification>\n<task-id>x</task-id>"')"

# --- pending, not missing: index rows without files
printf '| D1 | a |\n| D2 | b |\n' >"$P/decisions/phase1/00-index.md"
echo "ruling" >"$P/decisions/phase1/D1-a.md"
unthrottle
hook '/decisions  1 D files \(2 in the index; pending D2\)/' "$(ev PostToolUse s1 '"tool_name":"Agent"')"
jq -e '.hookSpecificOutput.additionalContext | test("missing|written [0-9]+s ago") | not' <<<"$LAST" >/dev/null &&
	ok "no missing / freshness flags in a hook report" || bad "missing or freshness flag in: $LAST"

# --- deltas on an agent's return, by prompt or by the next tool call
echo "- [x] done" >"$P/lanes/p1-01-checkpoint.md"
echo "Final SHA: $MAIN" >>"$P/lanes/p1-01-checkpoint.md"
hook '/lanes      1 checkpoints/' "$(ev UserPromptSubmit s1 '"prompt":"<teammate-message teammate_id=\"g1\">done</teammate-message>"')"
hook silent "$(ev UserPromptSubmit s1 '"prompt":"<agent-message from=\"a1\">\n[Subagent hand-back] done"')"
echo "ruling" >"$P/decisions/phase1/D2-b.md"
unthrottle
hook '/changed between .*\n.*2 D files \(2 in the index\)/' "$(ev PostToolUse s1 '"tool_name":"Bash"')"

# --- SessionStart after a compaction and a resume
hook '/Re-read .*HANDOFF.md[\s\S]*\nroute state ·/' "$(ev SessionStart s1 '"source":"compact"')"
hook '/Read .*SKILL.md in full/' "$(ev SessionStart s1 '"source":"resume"')"
hook silent "$(ev SessionStart s1 '"source":"startup"')"
hook silent "$(ev SessionStart s2 '"source":"compact"')"

# --- lanes: Final SHA, merged by ancestry, by patch, by the integrator's record
F1=$(git -C "$T/wt" "${G[@]}" commit -q --allow-empty -m lane-a && git -C "$T/wt" rev-parse HEAD)
echo "x" >"$T/wt/f.txt"
git -C "$T/wt" add f.txt && git -C "$T/wt" "${G[@]}" commit -q -m lane-b
F2=$(git -C "$T/wt" rev-parse HEAD)
git -C "$R" "${G[@]}" cherry-pick "$F2" >/dev/null
printf 'Final SHA: %s\nnote: older commit %s\n' "$F2" "${MAIN:0:7}" >"$P/lanes/p1-02-checkpoint.md"
out=$(python3 "$SCRIPTS/route_state.py" "$P" --phase 1 --repo "$R" --all)
grep -q "p1-02 .*${F2:0:7}[0-9a-f]* merged (by patch)" <<<"$out" && ok "Final SHA used, rebased lane merged by patch" ||
	bad "by patch: $(grep p1-02 <<<"$out")"
grep -q "p1-01 .*merged" <<<"$out" && grep -q "1 lane worktrees" <<<"$out" &&
	ok "ancestor lane merged; main's worktree not counted" || bad "lanes line: $(grep -E 'p1-01|^lanes' <<<"$out")"
echo "fixup" >"$T/wt/g.txt"
git -C "$T/wt" add g.txt && git -C "$T/wt" "${G[@]}" commit -q -m 'fixup! lane-b'
F3=$(git -C "$T/wt" rev-parse HEAD)
echo "squashed" >"$R/g.txt"
git -C "$R" add g.txt && git -C "$R" "${G[@]}" commit -q -m squashed
SQ=$(git -C "$R" rev-parse HEAD)
printf 'Final SHA: %s\n' "$F3" >"$P/lanes/p1-03-checkpoint.md"
out=$(python3 "$SCRIPTS/route_state.py" "$P" --phase 1 --repo "$R" --all)
grep -q "p1-03 .*not merged" <<<"$out" && ok "squashed lane without a record: not merged" || bad "squash: $(grep p1-03 <<<"$out")"
printf '# wave 1\nMerged p1-03 `%s` → `%s`\n' "${F3:0:9}" "${SQ:0:9}" >"$P/lanes/wave1-integration.md"
out=$(python3 "$SCRIPTS/route_state.py" "$P" --phase 1 --repo "$R" --all)
grep -q "p1-03 .*merged as ${SQ:0:9} (wave1-integration.md)" <<<"$out" && ok "squashed lane merged per the integrator's record" ||
	bad "record: $(grep p1-03 <<<"$out")"
grep -q "no \`Final SHA:\` line" <<<"$out" && bad "Final SHA flag on checkpoints that have one" || ok "no Final SHA flag when present"
# a merged lane's long checkpoint: no next group reads it, so no length flag (F76)
{
	printf 'Final SHA: %s\n' "$MAIN"
	seq 40
} >"$P/lanes/p1-05-checkpoint.md"
out=$(python3 "$SCRIPTS/route_state.py" "$P" --phase 1 --repo "$R" --all)
grep -q "p1-05 .*merged" <<<"$out" && ! grep -q "checkpoint over 35 lines *lanes/p1-05" <<<"$out" &&
	ok "no length flag on a merged lane's checkpoint" || bad "merged lane length flag: $(grep p1-05 <<<"$out")"
rm "$P/lanes/p1-05-checkpoint.md"

# --- --main: the default branch of a master repo, and a wrong --main in an old marker
M=$T/mrepo
git init -q -b master "$M"
git -C "$M" "${G[@]}" commit -q --allow-empty -m one
mkdir -p "$M/.plan"
# The route of s1 restarted as s9: listed once, active as of s9's transcript (5 min ago).
cp "$HOME/.claude/dsp-routes/s1.json" "$HOME/.claude/dsp-routes/s9.json"
mkdir -p "$HOME/.claude/projects/p"
touch -d '5 minutes ago' "$HOME/.claude/projects/p/s9.jsonl"
touch -d '3 days ago' "$R/.git/dsp-route.json"
out=$(CLAUDE_CODE_SESSION_ID=s3 python3 "$SCRIPTS/route_state.py" "$M/.plan" --phase 1 --repo "$M" --activate)
grep -q '"--main", "master"' "$M/.git/dsp-route.json" && ok "--main defaults to master" || bad "--main default: $(cat "$M/.git/dsp-route.json")"
[ "$(grep -c "other route on this account: $P (lead last active 5m ago)" <<<"$out")" = 1 ] &&
	ok "activate lists the other route once, active as of its lead's transcript" || bad "other routes: $out"
out=$(python3 "$SCRIPTS/route_state.py" "$M/.plan" --phase 1 --repo "$M" --main main)
grep -q -- "--main main does not exist .*using master" <<<"$out" && ok "a wrong --main falls back with a flag" || bad "wrong --main: $out"

# --- sections: closed range with pending, open range
echo "x" >"$P/spec/01-scope.md"
echo "x" >"$P/spec/02-core.md"
grep -q "spec       2 sections from §1" <<<"$(python3 "$SCRIPTS/route_state.py" "$P" --phase 1 --sections 1-)" &&
	ok "--sections 1- counts every section from §1" || bad "open sections"
grep -q "spec       2/3 sections (pending §3)" <<<"$(python3 "$SCRIPTS/route_state.py" "$P" --phase 1 --sections 1-3)" &&
	ok "--sections 1-3 lists the pending one" || bad "closed sections"

# --- Stage 5 budget: the lead's exec- dispatches wait for a recorded, answered budget (F74)
ts() { python3 -c 'import datetime as d, sys; print((d.datetime.now(d.UTC) + d.timedelta(seconds=int(sys.argv[1]))).isoformat(timespec="milliseconds").replace("+00:00", "Z"))' "$1"; }
human() { jq -nc --arg t "$(ts "$1")" '{type:"user",timestamp:$t,origin:{kind:"human"},message:{role:"user",content:"go"}}'; }
peer() { jq -nc --arg t "$(ts "$1")" '{type:"user",timestamp:$t,origin:{kind:"peer"},message:{role:"user",content:"Another Claude session sent a message: done"}}'; }
sent() { jq -nc --arg t "$(ts "$1")" --arg id "$2" --arg n "$3" '{type:"assistant",timestamp:$t,message:{id:$id,content:[{type:"tool_use",id:$id,name:"Agent",input:{name:$n}}]}}'; }
used() { jq -nc --arg t "$(ts "$1")" --arg id "$2" --argjson n "$3" '{type:"assistant",timestamp:$t,requestId:$id,message:{id:$id,model:"claude-opus-5-5",content:[],usage:{input_tokens:$n,output_tokens:0}}}'; }
LEAD=$HOME/.claude/projects/p/s1.jsonl
human -3600 >"$LEAD"
dispatch() { ev PreToolUse s1 "\"tool_name\":\"Agent\",\"tool_input\":{\"name\":\"$1\"},\"tool_use_id\":\"$2\",\"transcript_path\":\"$LEAD\""; }
hook 'deny:phase 1 has no Stage 5 budget' "$(dispatch exec-p1-01-a t1)"
hook silent "$(dispatch plan-p1-01 t1)"
hook silent "$(ev PreToolUse s2 '"tool_name":"Agent","tool_input":{"name":"exec-p1-01-a"}')"
out=$(CLAUDE_CODE_SESSION_ID=s2 python3 "$SCRIPTS/route_state.py" --budget w1 --estimate 10 --groups 4)
[ $? = 2 ] && ok "--budget without a registered session: exit 2" || bad "--budget unregistered: $out"
out=$(CLAUDE_CODE_SESSION_ID=s1 python3 "$SCRIPTS/route_state.py" --budget w1 --estimate 10 --groups 4)
[ $? = 0 ] && jq -e '.budgets[-1] | .label == "w1" and .groups == 4 and .phase == "1"' "$R/.git/dsp-route.json" >/dev/null &&
	grep -q "past 12.5M spent or 5 exec- dispatches" <<<"$out" && ok "--budget records the wave in the marker" || bad "--budget: $out"
hook 'deny:has not answered' "$(dispatch exec-p1-01-a t1)"
peer 1 >>"$LEAD"
hook 'deny:has not answered' "$(dispatch exec-p1-01-a t1)"
human 1 >>"$LEAD"
hook silent "$(dispatch exec-p1-01-a t1)"
CLAUDE_CODE_SESSION_ID=s1 python3 "$SCRIPTS/route_state.py" "$P" --phase 1 --repo "$R" --sections 1- --activate >/dev/null
jq -e '.budgets | length == 1' "$R/.git/dsp-route.json" >/dev/null && ok "a re-activation keeps the budgets" || bad "re-activation dropped the budgets"
unthrottle
hook '/budget     w1 · 10M · 4 exec- agents/' "$(ev PostToolUse s1 '"tool_name":"Agent"')"
for i in 1 2 3 4; do sent 2 "t$i" "exec-p1-0$i-a" >>"$LEAD"; done
hook silent "$(dispatch exec-p1-04-a t4)" # its own call is not counted twice
hook silent "$(dispatch exec-p1-05-a t5)" # 5 = 4 × 1.25
sent 2 t5 exec-p1-05-a >>"$LEAD"
hook 'deny:this would be exec- dispatch 6 since — more than 25% over' "$(dispatch exec-p1-06-a t6)"
CLAUDE_CODE_SESSION_ID=s1 python3 "$SCRIPTS/route_state.py" --budget w2 --estimate 0.01 --groups 9 >/dev/null
human 1 >>"$LEAD"
used 2 u1 11000 >>"$LEAD"
hook silent "$(dispatch exec-p1-06-a t6)"
used 2 u2 2000 >>"$LEAD"
hook 'deny:budget .w2. .*0.0M spent since — more than 25% over' "$(dispatch exec-p1-06-a t6)" # the spend

# --- usage_report.py: without --since, and a --since in another zone than the transcripts' UTC
UR=(python3 "$SCRIPTS/usage_report.py" s1 --project-dir "$HOME/.claude/projects/p")
out=$("${UR[@]}" 2>&1)
[ $? = 0 ] && grep -q '^lead .*turns=   2' <<<"$out" && ok "usage_report without --since" || bad "usage_report without --since: $(head -3 <<<"$out")"
z=$(ts -600)
o=$(python3 -c 'import datetime as d, sys; print(d.datetime.fromisoformat(sys.argv[1]).astimezone(d.timezone(d.timedelta(hours=2))).isoformat())' "$z")
a=$("${UR[@]}" --since "$z" | grep '^lead')
b=$("${UR[@]}" --since "$o" | grep '^lead')
[ "$a" = "$b" ] && grep -q 'turns=   2' <<<"$a" && ok "usage_report --since $o counts as $z" || bad "usage_report --since $z: $a | $o: $b"
out=$("${UR[@]}" --since yesterday 2>&1)
[ $? = 2 ] && grep -q 'argument --since' <<<"$out" && ok "usage_report refuses an unparseable --since" || bad "usage_report --since yesterday: $(head -3 <<<"$out")"

# --- inside an exec- agent: the context stop (F75) and a commit held for an unread ruling (F59)
SUB=$HOME/.claude/projects/p/s1/subagents
mkdir -p "$SUB"
echo '{"name":"exec-p1-01-b","agentType":"dsp-deep"}' >"$SUB/agent-x1.meta.json"
echo '{"name":"pride-p1-push1","agentType":"dsp-deep"}' >"$SUB/agent-y1.meta.json"
jq -nc --arg t "$(ts -60)" --arg f "$P/lanes/p1-01-rulings.md" '{type:"user",timestamp:$t,message:{role:"user",content:("Rulings file: " + $f)}}' >"$SUB/agent-x1.jsonl"
used -50 a1 150000 >>"$SUB/agent-x1.jsonl"
cp "$SUB/agent-x1.jsonl" "$SUB/agent-y1.jsonl"
inagent() { ev PreToolUse s1 "\"agent_id\":\"$1\",\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"$2\"},\"transcript_path\":\"$LEAD\""; }
hook silent "$(inagent x1 'ls')"
used -40 a2 210000 >>"$SUB/agent-x1.jsonl"
used -40 a2 210000 >>"$SUB/agent-y1.jsonl"
hook '/your context is 210k tokens. Finish the task/' "$(inagent x1 'ls')"
hook silent "$(inagent x1 'ls')"              # told once
hook silent "$(inagent y1 'ls')"              # not an exec- agent
hook silent "$(inagent x1 'git commit -m x')" # no rulings file yet
echo "R1 use the old API" >"$P/lanes/p1-01-rulings.md"
hook 'deny:re-read .*p1-01-rulings.md before you commit' "$(inagent x1 'git -C /w commit -m x')"
hook silent "$(inagent x1 'git status')"
hook silent "$(inagent y1 'git commit -m x')"
jq -nc --arg t "$(ts 30)" --arg f "$P/lanes/p1-01-rulings.md" '{type:"assistant",timestamp:$t,message:{id:"r1",content:[{type:"tool_use",id:"r1",name:"Read",input:{file_path:$f}}]}}' >>"$SUB/agent-x1.jsonl"
hook silent "$(inagent x1 'git commit -m x')"
# the transcript repeats a tool_use in an untimestamped api-request-blob record; the read still counts
jq -nc --arg f "$P/lanes/p1-01-rulings.md" '{type:"api-request-blob",agentId:"x1",hash:"h1",sessionId:"s1",message:{id:"r1",content:[{type:"tool_use",id:"r1",name:"Read",input:{file_path:$f}}]}}' >>"$SUB/agent-x1.jsonl"
hook silent "$(inagent x1 'git commit -m x')"
touch -d '+2 minutes' "$P/lanes/p1-01-rulings.md"
hook 'deny:re-read .*p1-01-rulings.md' "$(inagent x1 'git commit -m x')"
rm "$P/lanes/p1-01-rulings.md"

# --- the lead's files grow past one read (F76); the skill changes under a running lead (F78)
head -c 41000 /dev/zero | tr '\0' x >"$P/HANDOFF.md"
seq 40 >"$P/lanes/p1-04-checkpoint.md"
unthrottle
hook '/HANDOFF.md over 40 KB[\s\S]*checkpoint over 35 lines +lanes\/p1-04-checkpoint.md \(40/' "$(ev PostToolUse s1 '"tool_name":"Read"')"
rm "$P/HANDOFF.md" "$P/lanes/p1-04-checkpoint.md"
hook '/Re-read .*HANDOFF.md and, for Stage 5 \(going by the planning dir\) references\/execution.md,/' "$(ev SessionStart s1 '"source":"compact"')"
cp -rp "$SCRIPTS/.." "$T/skill"
RS=$T/skill/scripts/route_state.py
touch "$T/skill/references/execution.md"
unthrottle
hook '/changed since this session read it: references\/execution.md \(in /' "$(ev PostToolUse s1 '"tool_name":"Read"')"
unthrottle
hook silent "$(ev PostToolUse s1 '"tool_name":"Read"')" # told once
RS=$SCRIPTS/route_state.py

# --- SKILL.md fits what a compaction re-attaches (cut at 20,000 characters; failure-modes F61)
n=$(python3 -c 'import sys; print(len(open(sys.argv[1], encoding="utf-8").read()))' "$SCRIPTS/../SKILL.md")
[ "$n" -le 19000 ] && ok "SKILL.md is $n characters (limit 19000)" || bad "SKILL.md is $n characters — over 19000; move detail to a reference"

[ "$FAIL" = 0 ] && echo "ALL PASS" || echo "FAILURES"
exit "$FAIL"
