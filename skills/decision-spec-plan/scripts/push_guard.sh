#!/usr/bin/env bash
# PreToolUse:Bash — while a decision-spec-plan route is active in a repository
# (<git-common-dir>/dsp-route-<id>.json, written by `route_state.py --activate`), a `git push` may only
# send commits the full gate passed: a gate log under <planning-dir>/lanes/ whose first `sha=` line,
# within its first 20 lines (codegen or a build may print first), is `sha=<that commit> dirty=0` and
# whose last `exit=` line is `exit=0`.
# At rung M or L (`--rung` in the marker) the push also needs a pre-push review that covers it: a
# verdict under <planning-dir>/reviews/ whose first 10 lines hold
# `reviewed=<sha> base=<sha> blocking=0` (full SHAs), the reviewed commit an ancestor of the pushed
# one, every commit between them on an `after=` line (fixes made after the review), and the base
# an ancestor of the remote-tracking ref when there is one (nothing older than the base is unsent).
# With a CI harness in the marker (`--ci-harness <label>`: a suite CI runs that the local gate does
# not) the push also needs a passing gate log for that commit whose first 20 lines hold
# `harness=<label>`.
# Every `git push` in the command is checked, each in the repository its preceding `cd`s reach. A
# push with no refspec, with git options before `push` other than `-C <dir>`, after a GIT_*
# variable is set or a `pushd`/`popd` in the command is held: what it would send cannot be read
# from the command. The last three are held wherever they run while any route on the account is
# active, since they can point at a route's repository from outside it.
#
# Why: on 2026-10-07 a lead pushed main twice without a gate and both CI runs went red; CI
# confirms a state already proven green locally, it never discovers one (failure-modes F56). A
# finished lane whose full gate was green still carried two new high defects a review found (F70).
# Only the first push of a command was checked until 2026-10-17: `git push --dry-run … && git push …`
# went through. Every other command, and every repository without the marker, exits 0 at once.
#
# Bypass, only on the user's explicit word: DSP_SKIP_PUSH_GUARD=1 in the command skips both
# checks; DSP_SKIP_REVIEW=1 skips only the review.

set -uo pipefail

INPUT=$(cat)
CMD=$(jq -r '.tool_input.command // empty' <<<"$INPUT" 2>/dev/null)
case "$CMD" in *push*) ;; *) exit 0 ;; esac
case "$CMD" in *DSP_SKIP_PUSH_GUARD=1*) exit 0 ;; esac

# A command position: start, or after ; & | or a newline. Without it `grep "git push"` matches.
# A push run through a wrapper (`bash -c`, `env`, `xargs`) is not seen.
AT_CMD='(^|[;&|]|\n)[[:space:]]*([A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*[[:space:]]+)*'
# git's own options before `push`, each with at most one value word (`-C <dir>`, `-c k=v`, `--no-pager`).
GIT_PUSH='git([[:space:]]+-[^[:space:];&|]*([[:space:]]+[^-[:space:];&|][^[:space:];&|]*)?)*[[:space:]]+push'
PUSHES=$(grep -oE "${AT_CMD}${GIT_PUSH}([[:space:]][^;&|]*|$)" <<<"$CMD") || exit 0

CWD=$(jq -r '.cwd // empty' <<<"$INPUT" 2>/dev/null)
SESSION=$(jq -r '.session_id // empty' <<<"$INPUT" 2>/dev/null)
REVIEW_SKIP=
case "$CMD" in *DSP_SKIP_REVIEW=1*) REVIEW_SKIP=1 ;; esac

# $1 the pushed commit; $2 a CI harness label the log must name, or empty.
gated() {
	local log
	for log in "$PLANNING"/lanes/*-gate*.log; do
		[ -f "$log" ] || continue
		[ "$(head -n20 "$log" | grep -m1 '^sha=' | tr -d '\r')" = "sha=$1 dirty=0" ] || continue
		[ -z "${2:-}" ] || head -n20 "$log" | tr -d '\r' | grep -qxF "harness=$2" || continue
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

# The marker of any route registered on this account (route_state.py --activate) that is still active.
active_route() {
	local f m
	for f in "$HOME"/.claude/dsp-routes/*.json; do
		m=$(jq -r '.marker // empty' "$f" 2>/dev/null)
		[ -n "$m" ] && [ -f "$m" ] && echo "$m" && return 0
	done
	return 1
}

# The tags `git tag` earlier in the command ($BEFORE) creates, as `<name> <commit>` lines. Only
# `git tag [-a|-s] [-m <msg>|-F <file>|-u <key>] <new name> [<rev>]` is read, and a listing passes;
# any other `git tag` (a move, a delete, clustered flags, git options) fails, which holds the push.
# Why: `git tag v1 <sha> && git push origin v1` was held because v1 did not exist yet.
new_tags() {
	local seg w words name rev skip seen=' '
	while IFS= read -r seg; do
		[ -n "$seg" ] || continue
		[[ "$seg" =~ git[[:space:]]+tag([[:space:]]|$) ]] || return 1
		read -ra words <<<"$(sed -E "s/\"[^\"]*\"|'[^']*'/Q/g; s/^.*git[[:space:]]+tag//" <<<"$seg")"
		name='' rev='' skip=''
		for w in "${words[@]}"; do
			if [ -n "$skip" ]; then
				skip=
				continue
			fi
			case "$w" in
			-l | --list | -n* | --points-at* | --contains* | --no-contains* | --merged* | --no-merged*) continue 2 ;;
			-a | -s | --annotate | --sign) ;;
			-m | -F | -u | --message | --file | --local-user) skip=1 ;;
			*'>'* | *'<'*) ;;
			-*) return 1 ;;
			*) if [ -z "$name" ]; then name=$w; elif [ -z "$rev" ]; then rev=$w; else return 1; fi ;;
			esac
		done
		# `git tag` alone lists; a name that exists already or twice is a move or a refusal.
		[ -n "$name" ] || continue
		[[ "$seen" != *" $name "* ]] || return 1
		! git -C "$REPO" rev-parse -q --verify "refs/tags/$name" >/dev/null || return 1
		seen+="$name "
		echo "$name $(git -C "$REPO" rev-parse --verify -q "${rev:-HEAD}^{commit}" 2>/dev/null)"
	done < <(grep -oE "${AT_CMD}git([[:space:]]+-[^[:space:];&|]*([[:space:]]+[^-[:space:];&|][^[:space:];&|]*)?)*[[:space:]]+tag([[:space:]][^;&|]*)?" <<<"$BEFORE")
}

MISSING=()
NO_HARNESS=()
UNREVIEWED=()
BLOCKED_HARNESS=

# One push: $1 the segment from `git` on, $2 the command text before it, $3 the separator and
# variable assignments in front of it.
check() {
	local SEGMENT=$1 BEFORE=$2 PREFIX=$3 TARGETS t COMMON ARGS OPTS FORM MOVED TAGS WORDS POS SKIP_NEXT w BRANCH REMOTE SPECS spec src sha shas dst onto
	local had=$((${#MISSING[@]} + ${#NO_HARNESS[@]} + ${#UNREVIEWED[@]}))
	ARGS=$(sed -E "s/^${GIT_PUSH}//" <<<"$SEGMENT")
	OPTS=${SEGMENT%"$ARGS"}
	OPTS=${OPTS#git}
	read -ra WORDS <<<"${OPTS%push}"
	# Only the plain form is checked: git's options or GIT_* variables can change which repository,
	# config or refs a push uses, so with them the push is held.
	FORM=
	if [ "${#WORDS[@]}" -eq 2 ] && [ "${WORDS[0]}" = -C ]; then
		:
	elif [ "${#WORDS[@]}" -gt 0 ]; then
		FORM="git options before push (${WORDS[*]})"
	fi
	[[ "$BEFORE$PREFIX" =~ (^|[^A-Za-z0-9_])GIT_[A-Za-z0-9_]*= ]] && FORM="a GIT_* variable set before the push"
	grep -qE "(^|[;&|(])[[:space:]]*(pushd|popd)([[:space:]]|$)" <<<"$BEFORE" && FORM="pushd/popd before the push"
	# A ref read now is not what the push sends once a commit, merge or checkout earlier in the command
	# has moved it: `git commit -am x && git push origin main` was checked as the old main.
	MOVED=
	grep -qE "${AT_CMD}git([[:space:]]+-[^[:space:];&|]*([[:space:]]+[^-[:space:];&|][^[:space:];&|]*)?)*[[:space:]]+(commit|merge|rebase|reset|cherry-pick|revert|am|pull|checkout|switch|update-ref|branch)([[:space:]]|$)" <<<"$BEFORE" &&
		MOVED="a git command that moves refs earlier in the command — push in a command of its own"
	# The repository: the cwd, moved by each `cd <dir>` before the push, then by `git -C <dir>`. A
	# target this cannot resolve (a variable, a missing directory) leaves the repository unknown until
	# an absolute one follows; unknown at the push: skip it.
	# Why: falling back to the cwd blocked an agent's push in its own throwaway repository, because its
	# cwd was a lane worktree of an active route.
	TARGETS=$(grep -oE "(^|[;&|(])[[:space:]]*cd[[:space:]]+(\"[^\"]*\"|'[^']*'|[^[:space:];&|)]+)" <<<"$BEFORE" |
		sed -E "s/^[;&|([:space:]]*cd[[:space:]]+//")
	[ -z "$FORM" ] && [ "${#WORDS[@]}" -eq 2 ] && TARGETS+=$'\n'${WORDS[1]}
	REPO=${CWD:-$PWD}
	local unknown=
	while IFS= read -r t; do
		[ -n "$t" ] || continue
		case "$t" in \"*\" | \'*\') t=${t:1:-1} ;; esac
		case "$t" in *'$'* | *'`'*)
			unknown=1
			continue
			;;
		esac
		t=${t/#\~/$HOME}
		if [ "${t:0:1}" != / ]; then
			[ -z "$unknown" ] || continue
			t=$REPO/$t
		fi
		if [ -d "$t" ]; then
			REPO=$t
			unknown=
		else
			unknown=1
		fi
	done <<<"$TARGETS"
	TAGS=$(new_tags) || MOVED="a \`git tag\` other than creating a new tag earlier in the command — push in a command of its own"

	# The pushing session's own route when it runs in this repository, else the newest route here:
	# two routes in one repository each have a marker (route_state.py --activate, F93).
	MARKER=
	if [ -z "$unknown" ] && COMMON=$(git -C "$REPO" rev-parse --path-format=absolute --git-common-dir 2>/dev/null); then
		MARKER=$(jq -r '.marker // empty' "$HOME/.claude/dsp-routes/$SESSION.json" 2>/dev/null)
		[ -n "$MARKER" ] && [ -f "$MARKER" ] && [ "${MARKER%/*}" = "$COMMON" ] ||
			MARKER=$(find "$COMMON" -maxdepth 1 -name 'dsp-route*.json' -printf '%T@ %p\n' 2>/dev/null | sort -rn | sed -n '1s/^[^ ]* //p')
	fi
	# A held form may push a route's repository from anywhere (`--git-dir=`, `GIT_DIR=`, `pushd`).
	[ -z "$MARKER" ] && [ -n "$FORM" ] && MARKER=$(active_route)
	FORM=${FORM:-$MOVED}
	[ -n "$MARKER" ] || return 0
	PLANNING=$(jq -r '.planning_dir // empty' "$MARKER" 2>/dev/null)
	[ -n "$PLANNING" ] || return 0
	RUNG=$(jq -r '.rung // empty' "$MARKER" 2>/dev/null)
	HARNESS=$(jq -r '.ci_harness // empty' "$MARKER" 2>/dev/null)
	REVIEW=
	case "$RUNG" in M | L) REVIEW=1 ;; esac
	[ -z "$REVIEW_SKIP" ] || REVIEW=
	if [ -n "$FORM" ]; then
		MISSING+=("$FORM — push with plain \`git [-C <dir>] push <remote> <refs>\`")
		BLOCKED_MARKER=$MARKER BLOCKED_PLANNING=$PLANNING BLOCKED_RUNG=$RUNG
		return 0
	fi

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
		--dry-run | -n | --help | -h | --delete | -d) return 0 ;;
		--all | --mirror | --tags | --branches) POS=(__ALL__) && break ;;
		# Options whose value is the next word.
		-o | --push-option | --repo | --receive-pack | --exec) SKIP_NEXT=1 ;;
		-*) ;;
		*) POS+=("$w") ;;
		esac
	done

	BRANCH=$(git -C "$REPO" symbolic-ref -q --short HEAD)
	REMOTE=${POS[0]:-}
	SPECS=()
	if [ "${POS[0]:-}" = "__ALL__" ]; then
		MISSING+=("every ref (--all/--mirror/--tags/--branches) — push explicit refs")
	else
		SPECS=("${POS[@]:1}")
		# Without a refspec, what goes out depends on push.default, push refspecs, mirror and
		# pushRemote config: never guessed.
		[ "${#SPECS[@]}" -gt 0 ] || MISSING+=("a push with no refspec — name the remote and the refs: git push <remote> <ref>")
	fi
	for spec in "${SPECS[@]}"; do
		src=${spec%%:*}
		src=${src#+}
		# `:ref` deletes a remote ref and sends no commit.
		[ -z "$src" ] && continue
		# A new tag made earlier in the command, and whatever the name resolves to now: each may be sent.
		shas=$({
			awk -v n="${src#refs/tags/}" '$1 == n { print $2 }' <<<"$TAGS"
			git -C "$REPO" rev-parse --verify -q "${src}^{commit}" 2>/dev/null
		} | grep . | sort -u)
		[ -n "$shas" ] || MISSING+=("$src (does not resolve to a commit in $REPO)")
		for sha in $shas; do
			if ! gated "$sha"; then
				MISSING+=("$src = ${sha:0:12}")
			elif [ -n "$HARNESS" ] && ! gated "$sha" "$HARNESS"; then
				NO_HARNESS+=("$src = ${sha:0:12}")
			elif [ -n "$REVIEW" ]; then
				dst=$src
				case "$spec" in *:*) dst=${spec#*:} ;; esac
				[ "$dst" = HEAD ] && dst=$BRANCH
				dst=${dst#refs/heads/}
				onto=$(git -C "$REPO" rev-parse -q --verify "refs/remotes/$REMOTE/$dst^{commit}" 2>/dev/null)
				reviewed "$sha" "$onto" || UNREVIEWED+=("$src = ${sha:0:12}${onto:+ (remote-tracking $REMOTE/$dst = ${onto:0:12})}")
			fi
		done
	done
	[ $((${#MISSING[@]} + ${#NO_HARNESS[@]} + ${#UNREVIEWED[@]})) -gt "$had" ] || return 0
	# The message names the route of the push that failed.
	BLOCKED_MARKER=$MARKER BLOCKED_PLANNING=$PLANNING BLOCKED_RUNG=$RUNG BLOCKED_HARNESS=$HARNESS
}

# Each push with the whole command text before it, so a `cd` anywhere earlier counts.
DONE=
REST=$CMD
while IFS= read -r m; do
	[ -n "$m" ] || continue
	BEFORE=$DONE${REST%%"$m"*}
	DONE=$BEFORE$m
	REST=${REST#*"$m"}
	seg=$(sed -E "s/^[;&|]?[[:space:]]*([A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*[[:space:]]+)*//" <<<"$m")
	check "$seg" "$BEFORE" "${m%"$seg"}"
done <<<"$PUSHES"
[ "${#MISSING[@]}" -eq 0 ] && [ "${#NO_HARNESS[@]}" -eq 0 ] && [ "${#UNREVIEWED[@]}" -eq 0 ] && exit 0
MARKER=$BLOCKED_MARKER PLANNING=$BLOCKED_PLANNING RUNG=$BLOCKED_RUNG HARNESS=$BLOCKED_HARNESS

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
	if [ "${#NO_HARNESS[@]}" -gt 0 ]; then
		echo "[push_guard] \`git push\` of a commit the CI harness \`$HARNESS\` has not passed — BLOCKED (route: $MARKER)."
		echo
		printf '  not passed by the CI harness: %s\n' "${NO_HARNESS[@]}"
		cat <<EOF

CI runs a suite the local full gate does not (route_state.py --ci-harness), and a commit green
locally went red there four times in one round. Run that suite on the exact commit, on a clean
tree, into a log that names it:

  { echo "sha=\$(git rev-parse HEAD) dirty=\$(git status --porcelain --untracked-files=no | grep -c .)"; echo "harness=$HARNESS"; <the CI's command>; echo "exit=\$?"; } > $PLANNING/lanes/<name>-$HARNESS-gate.log 2>&1

The push goes through once such a log ends \`exit=0\`. If the suite cannot run here, tell the user;
bypass only on their explicit instruction: DSP_SKIP_PUSH_GUARD=1.
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
