#!/usr/bin/env bash
# PreToolUse:Bash — while a decision-spec-plan route is active in a repository
# (<git-common-dir>/dsp-route.json, written by `route_state.py --activate`), a `git push` may only
# send commits the full gate passed: a gate log under <planning-dir>/lanes/ whose first `sha=` line,
# within its first 20 lines (codegen or a build may print first), is `sha=<that commit> dirty=0` and
# whose last `exit=` line is `exit=0`.
# At rung M or L (`--rung` in the marker) the push also needs a pre-push review that covers it: a
# verdict under <planning-dir>/reviews/ whose first 10 lines hold
# `reviewed=<sha> base=<sha> blocking=0` (full SHAs), the reviewed commit an ancestor of the pushed
# one, every commit between them on an `after=` line (fixes made after the review), and the base
# an ancestor of the remote-tracking ref when there is one (nothing older than the base is unsent).
#
# Why: on 2026-10-07 a lead pushed main twice without a gate and both CI runs went red; CI
# confirms a state already proven green locally, it never discovers one (failure-modes F56). A
# finished lane whose full gate was green still carried two new high defects a review found (F70).
# Every other command, and every repository without the marker, exits 0 at once.
#
# Bypass, only on the user's explicit word: DSP_SKIP_PUSH_GUARD=1 in the command skips both
# checks; DSP_SKIP_REVIEW=1 skips only the review.

set -uo pipefail

INPUT=$(cat)
CMD=$(jq -r '.tool_input.command // empty' <<<"$INPUT" 2>/dev/null)
case "$CMD" in *push*) ;; *) exit 0 ;; esac
case "$CMD" in *DSP_SKIP_PUSH_GUARD=1*) exit 0 ;; esac

# A command position: start, or after ; & | or a newline. Without it `grep "git push"` matches.
AT_CMD='(^|[;&|]|\n)[[:space:]]*([A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*[[:space:]]+)*'
GIT_PUSH='git([[:space:]]+-C[[:space:]]+[^[:space:];&|]+)?[[:space:]]+push'
grep -qE "${AT_CMD}${GIT_PUSH}([[:space:]]|$)" <<<"$CMD" || exit 0

CWD=$(jq -r '.cwd // empty' <<<"$INPUT" 2>/dev/null)
SEGMENT=$(grep -oE "${GIT_PUSH}[^;&|]*" <<<"$CMD" | sed -n '1p')
# The repository: the cwd, moved by each `cd <dir>` before the push, then by `git -C <dir>`. A
# target this cannot resolve (a variable, a missing directory) leaves the repository unknown: exit 0.
# Why: falling back to the cwd blocked an agent's push in its own throwaway repository, because its
# cwd was a lane worktree of an active route.
BEFORE=${CMD%%"$SEGMENT"*}
TARGETS=$(grep -oE "(^|[;&|(])[[:space:]]*cd[[:space:]]+(\"[^\"]*\"|'[^']*'|[^[:space:];&|)]+)" <<<"$BEFORE" |
	sed -E "s/^[;&|([:space:]]*cd[[:space:]]+//")
grep -qE '^git[[:space:]]+-C' <<<"$SEGMENT" && TARGETS+=$'\n'$(awk '{print $3}' <<<"$SEGMENT")
REPO=${CWD:-$PWD}
while IFS= read -r t; do
	[ -n "$t" ] || continue
	case "$t" in \"*\" | \'*\') t=${t:1:-1} ;; esac
	case "$t" in *'$'* | *'`'*) exit 0 ;; esac
	t=${t/#\~/$HOME}
	[ "${t:0:1}" = / ] || t=$REPO/$t
	[ -d "$t" ] || exit 0
	REPO=$t
done <<<"$TARGETS"

COMMON=$(git -C "$REPO" rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || exit 0
MARKER="$COMMON/dsp-route.json"
[ -f "$MARKER" ] || exit 0
PLANNING=$(jq -r '.planning_dir // empty' "$MARKER" 2>/dev/null)
[ -n "$PLANNING" ] || exit 0
RUNG=$(jq -r '.rung // empty' "$MARKER" 2>/dev/null)
REVIEW=
case "$RUNG" in M | L) REVIEW=1 ;; esac
case "$CMD" in *DSP_SKIP_REVIEW=1*) REVIEW= ;; esac

ARGS=$(sed -E "s/^${GIT_PUSH}//" <<<"$SEGMENT")
read -ra WORDS <<<"$ARGS"
POS=()
SKIP_NEXT=
for w in "${WORDS[@]}"; do
	if [ -n "$SKIP_NEXT" ]; then
		SKIP_NEXT=
		continue
	fi
	case "$w" in
	# A redirection, never a refspec; a bare operator's target is the next word.
	*'>' | *'<') SKIP_NEXT=1 ;;
	*'>'* | *'<'*) ;;
	# Sends nothing, or sends no commit.
	--dry-run | -n | --help | -h | --delete | -d) exit 0 ;;
	--all | --mirror | --tags | --branches) POS=(__ALL__) && break ;;
	# Options whose value is the next word.
	-o | --push-option | --repo | --receive-pack | --exec) SKIP_NEXT=1 ;;
	-*) ;;
	*) POS+=("$w") ;;
	esac
done

gated() {
	local log
	for log in "$PLANNING"/lanes/*-gate.log; do
		[ -f "$log" ] || continue
		[ "$(head -n20 "$log" | grep -m1 '^sha=' | tr -d '\r')" = "sha=$1 dirty=0" ] || continue
		[ "$(grep -E '^exit=[0-9]+[[:space:]]*$' "$log" | tail -n1 | tr -d '[:space:]')" = "exit=0" ] && return 0
	done
	return 1
}

# $1 the pushed commit; $2 the remote-tracking commit, or empty when there is none.
reviewed() {
	local v head line r b after
	for v in "$PLANNING"/reviews/*-verdict.md; do
		[ -f "$v" ] || continue
		head=$(head -n10 "$v" | tr -d '\r')
		line=$(grep -m1 -E '^reviewed=[0-9a-f]{40} base=[0-9a-f]{40} blocking=0[[:space:]]*$' <<<"$head") || continue
		r=${line#reviewed=}
		r=${r%% *}
		b=${line#* base=}
		b=${b%% *}
		git -C "$REPO" merge-base --is-ancestor "$r" "$1" 2>/dev/null || continue
		after=$(grep -m1 '^after=' <<<"$head" | cut -d= -f2- | tr -s ' ,' '\n')
		[ -z "$(git -C "$REPO" rev-list "$r..$1" | grep -vxF -f <(printf '%s\n' "$after"))" ] || continue
		[ -z "$2" ] || git -C "$REPO" merge-base --is-ancestor "$b" "$2" 2>/dev/null || continue
		return 0
	done
	return 1
}

BRANCH=$(git -C "$REPO" symbolic-ref -q --short HEAD)
REMOTE=${POS[0]:-}
[ -n "$REMOTE" ] || REMOTE=$(git -C "$REPO" config "branch.$BRANCH.remote" 2>/dev/null || echo origin)

MISSING=()
UNREVIEWED=()
if [ "${POS[0]:-}" = "__ALL__" ]; then
	MISSING+=("every ref (--all/--mirror/--tags/--branches) — push explicit refs")
else
	SPECS=("${POS[@]:1}")
	[ "${#SPECS[@]}" -eq 0 ] && SPECS=(HEAD)
	for spec in "${SPECS[@]}"; do
		src=${spec%%:*}
		src=${src#+}
		# `:ref` deletes a remote ref and sends no commit.
		[ -z "$src" ] && continue
		sha=$(git -C "$REPO" rev-parse --verify -q "${src}^{commit}" 2>/dev/null)
		if [ -z "$sha" ]; then
			MISSING+=("$src (does not resolve to a commit in $REPO)")
		elif ! gated "$sha"; then
			MISSING+=("$src = ${sha:0:12}")
		elif [ -n "$REVIEW" ]; then
			dst=$src
			case "$spec" in *:*) dst=${spec#*:} ;; esac
			[ "$dst" = HEAD ] && dst=$BRANCH
			dst=${dst#refs/heads/}
			onto=$(git -C "$REPO" rev-parse -q --verify "refs/remotes/$REMOTE/$dst^{commit}" 2>/dev/null)
			reviewed "$sha" "$onto" || UNREVIEWED+=("$src = ${sha:0:12}${onto:+ (remote-tracking $REMOTE/$dst = ${onto:0:12})}")
		fi
	done
fi
[ "${#MISSING[@]}" -eq 0 ] && [ "${#UNREVIEWED[@]}" -eq 0 ] && exit 0

{
	if [ "${#MISSING[@]}" -gt 0 ]; then
		echo "[push_guard] \`git push\` of a commit no full gate has passed — BLOCKED (decision-spec-plan route active: $MARKER)."
		echo
		printf '  not gated: %s\n' "${MISSING[@]}"
		cat <<EOF

CI confirms a state already proven green here; it never discovers one. Check out that exact commit
on a clean tree and run the full gate into a log under the planning dir:

  { echo "sha=\$(git rev-parse HEAD) dirty=\$(git status --porcelain --untracked-files=no | grep -c .)"; <full gate>; echo "exit=\$?"; } > $PLANNING/lanes/<name>-gate.log 2>&1

The push goes through once a log there starts with \`sha=<the commit> dirty=0\` and ends \`exit=0\`.
Bypass only on the user's explicit instruction: prefix the push with DSP_SKIP_PUSH_GUARD=1.
EOF
	fi
	if [ "${#UNREVIEWED[@]}" -gt 0 ]; then
		echo "[push_guard] \`git push\` of a commit no pre-push review covers — BLOCKED (rung $RUNG route: $MARKER)."
		echo
		printf '  not reviewed: %s\n' "${UNREVIEWED[@]}"
		cat <<EOF

At rung M and L every push first gets the seven-sins pre-push review of what it sends
(references/sins/lead.md, base = the remote's tip after a \`git fetch\`). Its verdict,
$PLANNING/reviews/<name>-verdict.md, opens with

  reviewed=<full SHA reviewed> base=<full SHA of the base> blocking=<new criticals and highs neither fixed nor waived>
  after=<full SHA of each fix committed after the review, space-separated>

The push goes through once blocking=0, the reviewed commit is an ancestor of the pushed one, every
commit between them is on the after= line, and the base is an ancestor of the remote-tracking ref.
Bypass only on the user's explicit instruction: DSP_SKIP_REVIEW=1 (the gate check still applies).
EOF
	fi
} >&2
exit 2
