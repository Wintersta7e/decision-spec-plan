# SPDX-License-Identifier: MIT
"""Outward actions on the hosted repository.

The lead's `route_state.py --hook` asks the user each time, read as bash reads the
command (F81).
"""

import unittest

from typing_extensions import override

import support
from support import ev


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
            leadbash("s1", "X=$(ls); bash -c $X; node -e a.push(1); gh cache delete 5"),
        )
        _ = self.hook("silent", leadbash("s1", "source ./env.sh; git push origin main"))
        _ = self.hook(
            "silent", leadbash("s1", "eval $X; gh pr view 5; git log --grep merge")
        )
        # a script file the command runs is read: an outward action in it asks
        _ = self.write(t / "scripts/merge.sh", "gh pr merge 7 --squash\n")
        _ = self.hook(
            "ask:acts on the hosted repository",
            leadbash("s1", f"bash {t}/scripts/merge.sh"),
        )
        _ = self.hook("silent", leadbash("s1", f"bash {t}/scripts/env.sh"))


if __name__ == "__main__":
    _ = unittest.main()
