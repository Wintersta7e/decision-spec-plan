# SPDX-License-Identifier: MIT
"""Outward actions on the hosted repository.

The lead's `route_state.py --hook` asks the user each time, read as bash reads the
command (F81).
"""

import pathlib
import tempfile
import unittest

from typing_extensions import override

import support
from support import decision_index, ev, jstr


def leadbash(session: str, command: str) -> str:
    """A lead's Bash call, the command put into the JSON text as is."""
    return ev(
        "PreToolUse",
        session,
        f'"tool_name":"Bash","tool_input":{{"command":"{command}"}}',
    )


class OutwardActions(support.Route):
    """The lead's Bash calls on the route of support.Route."""

    @override
    @classmethod
    def setUpClass(cls) -> None:
        """Write the sourced script a command below runs."""
        super().setUpClass()
        # the sourced script section 152 left in T/scripts
        _ = cls.write(
            cls.T / "scripts/env.sh",
            'export NVM_DIR=x\nnvm_ls() { git -C "$NVM_DIR" fetch; }\n',
        )

    def test_outward_actions(self) -> None:
        """Each outward action asks; reads and local work pass."""
        self._gh_and_push()
        self._publishes()
        self._read_as_bash()

    def _gh_and_push(self) -> None:
        """PR, release and remote-branch actions in their plain and other forms."""
        # nine PRs were closed with --delete-branch unasked
        _ = self.hook(
            "ask:gh pr close 5.*the user approves it here",
            leadbash("s1", "gh pr close 5 --delete-branch"),
        )
        _ = self.hook(
            "ask:gh -R o/r pr merge", leadbash("s1", "gh -R o/r pr merge 7 --squash")
        )
        _ = self.hook(
            "ask:--delete-branch",
            leadbash("s1", "git fetch && gh pr merge 7 --delete-branch"),
        )
        _ = self.hook(
            "ask:gh release create",
            leadbash("s1", "gh release create v1.0 dist/app.zip"),
        )
        _ = self.hook("silent", leadbash("s1", "gh pr view 5 --json title"))
        _ = self.hook("silent", leadbash("s1", "gh run watch 12 --exit-status"))
        _ = self.hook(
            "silent", leadbash("s1", "gh pr list; git log --oneline -1 | grep merge")
        )
        # the same actions in other forms: options between gh's words, `gh api` writes,
        # remote deletes
        _ = self.hook(
            "ask:gh pr -R o/r close 5", leadbash("s1", "gh pr -R o/r close 5")
        )
        _ = self.hook(
            "ask:gh api -X PATCH",
            leadbash("s1", "gh api -X PATCH repos/o/r/pulls/5 -f state=closed"),
        )
        _ = self.hook(
            "ask:--method DELETE",
            leadbash("s1", "gh api repos/o/r/git/refs/heads/x --method DELETE"),
        )
        _ = self.hook(
            "ask:gh api repos/o/r/issues/5/comments -f",
            leadbash("s1", "gh api repos/o/r/issues/5/comments -f body=x"),
        )
        _ = self.hook(
            "ask:git push origin --delete old",
            leadbash("s1", "git push origin --delete old"),
        )
        _ = self.hook(
            "ask:git push origin :old", leadbash("s1", "git push origin :old")
        )
        _ = self.hook(
            "ask:-fbody=x",
            leadbash("s1", "gh api repos/o/r/issues/5/comments -fbody=x"),
        )
        _ = self.hook(
            "ask:--prune",
            leadbash("s1", "git push --prune origin 'refs/heads/*:refs/heads/*'"),
        )
        _ = self.hook("ask:git push -fd", leadbash("s1", "git push -fd origin old"))
        _ = self.hook(
            "ask:git push origin ':old'", leadbash("s1", "git push origin ':old'")
        )
        _ = self.hook("silent", leadbash("s1", "gh api repos/o/r/pulls/5"))
        _ = self.hook(
            "silent",
            leadbash("s1", "git push origin main && git push origin HEAD:refs/heads/x"),
        )
        _ = self.hook(
            "silent", leadbash("s1", "git push --dry-run -u origin main --follow-tags")
        )

    def _publishes(self) -> None:
        """Publishes to a package or image registry, in their plain and other forms."""
        # a publish to a package or image registry cannot be taken back: one lead
        # published five immutable packages on a bare "go"
        _ = self.hook(
            "ask:npm publish --access public.*or a registry",
            leadbash("s1", "npm run build && npm publish --access public"),
        )
        _ = self.hook(
            "ask:twine upload", leadbash("s1", "python -m twine upload dist/*")
        )
        _ = self.hook(
            "ask:docker image push", leadbash("s1", "docker image push reg/app:1")
        )
        _ = self.hook(
            "ask:cargo publish", leadbash("s1", "cd core && cargo publish -p core")
        )
        _ = self.hook(
            "silent",
            leadbash("s1", "npm run build; npm pack; docker build -t x .; cargo build"),
        )
        # the verb past valued options, a computed verb, a --push flag, text eval runs
        _ = self.hook(
            "ask:npm --registry r --tag beta --otp 1 publish",
            leadbash("s1", "npm --registry r --tag beta --otp 1 publish"),
        )
        _ = self.hook("ask:npm \\$V", leadbash("s1", "V=publish; npm $V"))
        _ = self.hook(
            "ask:docker buildx build --push",
            leadbash("s1", "docker buildx build --push -t reg/app ."),
        )
        _ = self.hook("ask:eval", leadbash("s1", "X='npm publish'; eval $X"))
        _ = self.hook("ask:gradlew publish", leadbash("s1", "./gradlew publish"))
        _ = self.hook(
            "silent",
            leadbash("s1", "docker run -v $PWD:/app -e K=$K img npm test"),
        )
        # a push flag's value or a registry output, an `=` inside the expansion, a
        # gradle task abbreviated, and a publisher's name as a gh option's value in
        # text the reader fails on
        _ = self.hook(
            "ask:--push=true", leadbash("s1", "docker buildx build --push=true .")
        )
        _ = self.hook(
            "ask:type=registry",
            leadbash("s1", "docker buildx build -o type=registry,name=r/a ."),
        )
        _ = self.hook("ask:npm", leadbash("s1", "npm ${V:=publish}"))
        _ = self.hook("ask:gradlew pTML", leadbash("s1", "./gradlew pTML"))
        _ = self.hook("ask:gradlew :app:PTML", leadbash("s1", "./gradlew :app:PTML"))
        _ = self.hook(
            "ask:push=1", leadbash("s1", "docker buildx build -o TYPE=image,push=1 .")
        )
        _ = self.hook("silent", leadbash("s1", "./gradlew clean build test"))
        # a local read or a static script or tool: its computed word is an argument (F2)
        _ = self.hook(
            "silent",
            leadbash(
                "s1",
                "cargo tree $X; uv run pytest $X; npm run test:unit -- $X; "
                "docker inspect $C",
            ),
        )
        _ = self.hook(
            "ask:docker exec c \\$ACTION", leadbash("s1", "docker exec c $ACTION")
        )
        deep = "$(" * 1500 + "gh -R npm pr merge 5" + ")" * 1500
        _ = self.hook("ask:acts on the hosted repository", leadbash("s1", deep))

    def _read_as_bash(self) -> None:
        """The command read as bash reads it, and a script file it runs read too."""
        t = self.T
        # the text names the action it matched, past the excerpt of a long command
        # (live: the excerpt showed no gh at all)
        _ = self.hook(
            "ask:`gh pr close 9` in `echo",
            leadbash("s1", "echo x; " * 30 + "gh pr close 9"),
        )
        # read as bash reads the command: wrapped forms count, quoted text does not, and
        # a long line is read in linear time (a regex took 36 s on 1,000 repeats of
        # `gh pr x`)
        _ = self.hook(
            "ask:timeout 30 gh pr close 5", leadbash("s1", "timeout 30 gh pr close 5")
        )
        _ = self.hook(
            "ask:bash -c", leadbash("s1", "bash -c 'git push origin --delete old'")
        )
        _ = self.hook("silent", leadbash("s1", "echo 'gh pr close 5'"))
        # text a shell runs that the reader cannot follow, or one it fails on, asks when
        # it names gh or push
        _ = self.hook("ask:eval", leadbash("s1", "X='gh pr close 5'; eval $X"))
        _ = self.hook("ask:bash", leadbash("s1", "echo 'gh pr close 5' | bash"))
        deep = "$(" * 1500 + "gh pr close 5" + ")" * 1500
        _ = self.hook("ask:acts on the hosted repository", leadbash("s1", deep))
        # ...and only then: an unreadable command that names gh or push for anything
        # else passes (a stub gh, a JS .push(, a plain push held 5 agents' local work on
        # 2026-10-31)
        _ = self.hook(
            "silent",
            leadbash("s1", "echo ls | bash; node -e a.push(1); gh cache delete 5"),
        )
        _ = self.hook("silent", leadbash("s1", "source ./env.sh; git push origin main"))
        _ = self.hook(
            "silent",
            leadbash("s1", "echo ls | bash; gh pr view 5; git log --grep merge"),
        )
        # ...but a computed `eval` or `-c` body may be any command: it asks
        _ = self.hook(
            "ask:bash.*computed",
            leadbash("s1", "X=$(ls); bash -c $X; gh cache delete 5"),
        )
        _ = self.hook("ask:eval", leadbash("s1", "eval $X; gh pr view 5"))
        # a script file the command runs is read: an outward action in it asks
        _ = self.write(t / "scripts/merge.sh", "gh pr merge 7 --squash\n")
        _ = self.hook(
            "ask:acts on the hosted repository",
            leadbash("s1", f"bash {t}/scripts/merge.sh"),
        )
        _ = self.hook("silent", leadbash("s1", f"bash {t}/scripts/env.sh"))


def tool(name: str, command: str = "", agent: str = "") -> str:
    """A PreToolUse event of tool name: a Bash command, or an MCP tool's note."""
    inp = f'{{"command":{jstr(command)}}}' if command else '{"body":"looks fine"}'
    who = f',"agent_id":"{agent}"' if agent else ""
    return ev("PreToolUse", "s1", f'"tool_name":"{name}","tool_input":{inp}{who}')


# Each posts a review comment or note to GitHub or GitLab.
POSTS = (
    "gh pr comment 5 --body ok",
    "gh pr review 5 --approve",
    "gh -R o/r pr review 5 --comment -b ok",
    "glab mr note 5 -m ok",
    "glab api projects/1/merge_requests/5/notes -f body=ok",
    "glab api -X POST projects/1/merge_requests/5/discussions --raw-field body=ok",
    "gh api repos/o/r/issues/5/comments -f body=ok",
    "gh api --method POST repos/o/r/pulls/5/reviews -f event=APPROVE",
    "gh api graphql -f query='mutation { addPullRequestReview(input: {}) { id } }'",
    "C='gh pr comment 5 -b ok'; bash -c \"$C\"",
)
# Each submits a review, not a comment that may answer one: held with no review on
# record.
REVIEWS = (
    POSTS[1],
    POSTS[2],
    POSTS[7],
    POSTS[8],
    "gh api repos/o/r/pulls/5/reviews/9/events -f event=APPROVE",
    "gh api graphql -f query='mutation { submitPullRequestReview(input: {}) { id } }'",
    "C='gh pr review 5 --approve'; bash -c \"$C\"",
)
# ...and none of these does
READS = (
    "gh pr view 5 --comments",
    "glab mr view 5",
    "glab api projects/1/merge_requests/5/notes",
    "gh api repos/o/r/pulls/5/reviews",
    "gh api graphql -f query='query { viewer { login } }'",
    "echo 'gh pr comment 5'",
)


class ReviewPosts(support.Route):
    """A review comment posted while the review's decision document fails (F104)."""

    @override
    @classmethod
    def setUpClass(cls) -> None:
        """Branch mr of R, one commit past main, changes src/app.py."""
        super().setUpClass()
        _ = cls.git("-C", cls.R, "checkout", "-q", "-b", "mr")
        _ = cls.write(cls.R / "src/app.py", "x\n")
        _ = cls.git("-C", cls.R, "add", "src/app.py")
        _ = cls.git("-C", cls.R, "commit", "-q", "-m", "change")
        cls.HEAD: str = cls.rev(cls.R)
        _ = cls.git("-C", cls.R, "checkout", "-q", "main")

    def index(self, extra: str, phase_dir: str = "") -> None:
        """Phase 1's decision index (or a round's), a review of main..mr with extra."""
        head = f"> **Review**: `{self.MAIN}..{self.HEAD}` — a merge request\n"
        text = decision_index("| S1 | **x** | U2 |").replace(
            "# Phase 1\n", f"# Phase 1\n{head}"
        )
        d = self.P / "decisions/phase1" / phase_dir
        _ = self.write(d / "00-index.md", text + extra)

    def test_review_posts(self) -> None:
        """Every form of a post is held until the review's Coverage passes."""
        # a route that records no review holds no comment: it answers a ticket or a
        # reviewer; a review submitted there has no document behind it
        _ = self.write(
            self.P / "decisions/phase1/00-index.md",
            decision_index("| S1 | **x** | U2 |"),
        )
        for command in REVIEWS:
            _ = self.hook(
                r"deny:posts a review; no decision document of phase 1 records the "
                r"review.*\*\*Review\*\*.*templates.md §1.*F104",
                tool("Bash", command),
            )
        for command in (POSTS[0], POSTS[3]):
            _ = self.hook("silent", tool("Bash", command))
        # a computed `-c` body may be any command: it asks as an outward action
        _ = self.hook("ask:bash. running a computed string", tool("Bash", POSTS[9]))
        _ = self.hook("ask:gh api", tool("Bash", POSTS[6]))
        _ = self.hook(
            "ask:gh api", tool("Bash", "gh api repos/o/r/pulls/5/comments -f body=ok")
        )
        _ = self.hook("silent", tool("mcp__gitlab__create_note"))
        self.index("\n## Coverage\n| File | Read |\n|---|---|\n")
        for command in POSTS:
            _ = self.hook(
                r"deny:posts a review comment; the review's decision document fails"
                r"(.|\n)*src/app.py changed in",
                tool("Bash", command),
            )
        for command in READS:
            _ = self.hook("silent", tool("Bash", command))
        held = r"deny:`mcp__gitlab__create_note` posts a review comment"
        _ = self.hook(held, tool("mcp__gitlab__create_note"))
        _ = self.hook("silent", tool("mcp__gitlab__get_notes"))
        _ = self.hook(
            "deny:posts a review comment", tool("Bash", POSTS[0], "aexec-x-1")
        )
        # a review round in its own directory is checked by its own index
        _ = self.write(
            self.P / "decisions/phase1/00-index.md",
            decision_index("| S1 | **x** | U2 |"),
        )
        self.index("", "mr-review")
        _ = self.hook(
            "deny:mr-review(.|\n)*no Coverage section", tool("Bash", POSTS[3])
        )
        self.rm(self.P / "decisions/phase1/mr-review")
        # read in full and probed: the post goes ahead (gh api's write still asks, F81)
        self.index(
            "> **Verdict**: approve\n\n## Coverage\n| File | Read |\n|---|---|\n"
            "| `src/app.py` | Read in full |\n\n- `pytest -q` exit=0 — it imports\n"
        )
        for command in (POSTS[0], POSTS[3]):
            _ = self.hook("silent", tool("Bash", command))
        # a computed `-c` body may be any command: it asks as an outward action
        _ = self.hook("ask:bash. running a computed string", tool("Bash", POSTS[9]))
        _ = self.hook("ask:gh api", tool("Bash", POSTS[6]))
        _ = self.hook("silent", tool("mcp__gitlab__create_note"))


# A computed word after a publisher's inert subcommand is its argument, not a verb:
# a live hunt's test runs were held as publishes.
ARGUMENTS = (
    "cargo test --workspace --all-features --locked $1 -- --nocapture --exact $1",
    "cargo test --workspace --all-features --locked $t -- --nocapture --exact $t",
    "cargo test --workspace $1",
    "cargo nextest run $T",
    "cargo clippy $ARGS",
    "npm test $1",
    "pnpm test $1",
    # local reads and runs held as publishes in a usage analysis (F2): a cargo or
    # container read, a static package script, a static tool under uv
    "cargo tree $X",
    "cargo metadata --format-version $V",
    "uv run pytest $X",
    "uv run ruff check $X",
    "npm run test:unit -- $X",
    "pnpm run lint $X",
    "docker inspect $C",
    "docker ps $X",
    "docker logs -f $C",
    "docker images $X",
    "podman inspect $C",
    "podman logs $C",
    "docker compose ps $X",
    "docker compose logs $S",
    # a shell's static `-c` body is read as bash reads it
    "bash -c 'cargo test'",
)
ARGUMENT_FORMS = 22
# ...and still outward: a computed subcommand, the verb itself, a tool whose every word
# may be a task or goal, and a computed word after any subcommand off the inert list —
# one that runs another (`npm run $X`), opens a publish (`yarn npm $V`, `docker build
# --push`) or none the list knows — or after a word that may be an option's value or
# a toolchain
STILL_OUTWARD = (
    "cargo $X",
    "npm $V",
    "cargo publish",
    "npm publish $1",
    "docker push $IMG",
    "gradle build $T",
    "mvn clean $GOAL",
    "yarn npm $V",
    "dotnet nuget $V",
    "docker image $V",
    "docker build $F .",
    "pnpm --filter x $V",
    "cargo +nightly $X",
    "npm run $X",
    "npm exec $X",
    "pnpm exec $X",
    "yarn workspace w $V",
    "docker plugin $X",
    "helm chart $X",
    "cargo run $X",
    # ...and past the two-word inert forms: an option before the script or tool, a
    # tool that runs a computed command, a compose subcommand that runs one
    "npm run --silent $X",
    "uv run --with x $X",
    "uv run $T",
    "uv run python3.12 $X",
    "uv run /bin/sh $X",
    "uv run npx $X",
    "uv run timeout 5 $X",
    "uv run npm $V",
    "docker compose exec c $X",
    "docker compose run $X",
    "docker run img $X",
    "podman exec c $X",
    "docker --context x inspect $C",
    # yarn and bun run any installed bin, not only a package script
    "yarn run build $X",
    "bun run dev $X",
)
STILL_OUTWARD_FORMS = 35
# Spec §1.6.2: every real publish and each command whose computed word may still be
# one, held past the inert forms above; `docker exec`'s later words are a command (R8)
STILL_HELD = (
    "cargo publish",
    "npm publish",
    "npm run $X",
    "uv publish",
    "uv run bash $X",
    "docker push reg/app:1",
    "docker build --push -t reg/app .",
    "docker $V",
    "docker exec c $ACTION",
    # a publisher or host tool run through a run form: its computed word may be the
    # verb; under uv only a listed tool is inert, and yarn or bun run any bin
    "uv run uv $X",
    "npm run npm $V",
    "uv run git $X",
    "pnpm run gh $X",
    "uv run pypy $X",
    "uv run doas $X",
    "yarn run uv $X",
    "bun run npm $V",
    # a computed verb in text the reader cannot follow: read as literal text, it
    # passed as no publish
    "eval $Z; npm $V",
    "git $Y; npm $V",
    # a uv tool given by path may be any program, and `coverage run` runs any script
    "uv run ./x/pytest $X",
    "uv run /tmp/x/pytest $X",
    "uv run coverage run $X",
    # a computed `eval` or shell `-c` body may be any command, under a wrapper too;
    # a shell body past a command's first word is read as text
    "eval $Z",
    "eval $Z; cargo test $V",
    'eval "npm $V"',
    'bash -c "$C"',
    'sh -ec "$C"',
    'sudo bash -c "$C"',
    'xargs -I{} sh -c "$C"',
    "sudo bash -c 'npm publish'",
    # in text the reader cannot follow, every computed word may be the verb
    "eval $Z; npm test $1",
    "eval $Z; docker run -v $PWD:/a -e K=$K img",
    "git $Y; cargo test $V",
    "git $Y; docker run -v $PWD:/a img",
)
STILL_HELD_FORMS = 34
# Each held beside the script pub.sh, which publishes: an `eval` or shell word that runs
# nothing leaves the line read, a script past an unreadable part too, a shell under a
# runner reads its script, and a shell's computed `--` body, stdin or script may run
# any.
SCRIPT_HELD = (
    "echo eval; bash pub.sh",
    "grep -c eval x; bash pub.sh",
    "echo ls | bash; bash pub.sh",
    "sudo bash pub.sh",
    'bash -c -- "$C"',
    'bash <<< "$C"',
    'echo "$C" | bash',
    'bash "$F"',
)


class ComputedArguments(unittest.TestCase):
    """A publisher's computed word: an argument after its subcommand, else a verb."""

    def test_computed_arguments(self) -> None:
        """Each argument form acts on nothing; each still-outward form is outward."""
        from dsp_route.outward import outward_in  # the hook imports it lazily (TID253)

        assert len(ARGUMENTS) == ARGUMENT_FORMS
        assert len(STILL_OUTWARD) == STILL_OUTWARD_FORMS
        assert len(STILL_HELD) == STILL_HELD_FORMS
        for command in ARGUMENTS:
            with self.subTest(command):
                assert outward_in(command) is None
        for command in (*STILL_OUTWARD, *STILL_HELD):
            with self.subTest(command):
                assert outward_in(command) is not None

    def test_computed_script_body(self) -> None:
        """A script's computed `eval` is held; a script of local work passes."""
        from dsp_route.outward import outward_in  # the hook imports it lazily (TID253)

        with tempfile.TemporaryDirectory(prefix="dsp-test-") as d:
            _ = (pathlib.Path(d) / "ship.sh").write_text('cargo test\neval "$CMD"\n')
            _ = (pathlib.Path(d) / "check.sh").write_text("cargo test\n")
            assert outward_in("bash ship.sh", d) is not None
            assert outward_in("bash check.sh", d) is None

    def test_where_bodies_run(self) -> None:
        """`eval` or a shell's body counts where it runs; the rest is still read."""
        from dsp_route.outward import outward_in  # the hook imports it lazily (TID253)

        with tempfile.TemporaryDirectory(prefix="dsp-test-") as d:
            _ = (pathlib.Path(d) / "pub.sh").write_text("npm publish\n")
            _ = (pathlib.Path(d) / "pub-safe.sh").write_text("cargo test\n")
            for command in SCRIPT_HELD:
                with self.subTest(command):
                    assert outward_in(command, d) is not None
            for command in ("bash -c 'cargo test'", "bash pub-safe.sh"):
                with self.subTest(command):
                    assert outward_in(command, d) is None


if __name__ == "__main__":
    _ = unittest.main()
