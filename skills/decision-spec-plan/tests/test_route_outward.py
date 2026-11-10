"""Outward actions on the hosted repository: the lead's `route_state.py --hook` asks the user each
time, read as bash reads the command (F81)."""

import unittest

import support
from support import ev


def leadbash(session, command):
    """A lead's Bash call, the command put into the JSON text as is."""
    return ev(
        "PreToolUse",
        session,
        f'"tool_name":"Bash","tool_input":{{"command":"{command}"}}',
    )


class OutwardActions(support.Route):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # the sourced script section 152 left in T/scripts
        cls.write(
            cls.T / "scripts/env.sh",
            'export NVM_DIR=x\nnvm_ls() { git -C "$NVM_DIR" fetch; }\n',
        )

    def test_outward_actions(self):
        T = self.T
        # nine PRs were closed with --delete-branch unasked
        self.hook(
            "ask:gh pr close 5.*the user approves it here",
            leadbash("s1", "gh pr close 5 --delete-branch"),
        )
        self.hook(
            "ask:gh -R o/r pr merge", leadbash("s1", "gh -R o/r pr merge 7 --squash")
        )
        self.hook(
            "ask:--delete-branch",
            leadbash("s1", "git fetch && gh pr merge 7 --delete-branch"),
        )
        self.hook(
            "ask:gh release create",
            leadbash("s1", "gh release create v1.0 dist/app.zip"),
        )
        self.hook("silent", leadbash("s1", "gh pr view 5 --json title"))
        self.hook("silent", leadbash("s1", "gh run watch 12 --exit-status"))
        self.hook(
            "silent", leadbash("s1", "gh pr list; git log --oneline -1 | grep merge")
        )
        # the same actions in other forms: options between gh's words, `gh api` writes, remote
        # deletes
        self.hook("ask:gh pr -R o/r close 5", leadbash("s1", "gh pr -R o/r close 5"))
        self.hook(
            "ask:gh api -X PATCH",
            leadbash("s1", "gh api -X PATCH repos/o/r/pulls/5 -f state=closed"),
        )
        self.hook(
            "ask:--method DELETE",
            leadbash("s1", "gh api repos/o/r/git/refs/heads/x --method DELETE"),
        )
        self.hook(
            "ask:gh api repos/o/r/issues/5/comments -f",
            leadbash("s1", "gh api repos/o/r/issues/5/comments -f body=x"),
        )
        self.hook(
            "ask:git push origin --delete old",
            leadbash("s1", "git push origin --delete old"),
        )
        self.hook("ask:git push origin :old", leadbash("s1", "git push origin :old"))
        self.hook(
            "ask:-fbody=x",
            leadbash("s1", "gh api repos/o/r/issues/5/comments -fbody=x"),
        )
        self.hook(
            "ask:--prune",
            leadbash("s1", "git push --prune origin 'refs/heads/*:refs/heads/*'"),
        )
        self.hook("ask:git push -fd", leadbash("s1", "git push -fd origin old"))
        self.hook(
            "ask:git push origin ':old'", leadbash("s1", "git push origin ':old'")
        )
        self.hook("silent", leadbash("s1", "gh api repos/o/r/pulls/5"))
        self.hook(
            "silent",
            leadbash("s1", "git push origin main && git push origin HEAD:refs/heads/x"),
        )
        self.hook(
            "silent", leadbash("s1", "git push --dry-run -u origin main --follow-tags")
        )
        # a publish to a package or image registry cannot be taken back: one lead published five
        # immutable packages on a bare "go"
        self.hook(
            "ask:npm publish --access public.*or a registry",
            leadbash("s1", "npm run build && npm publish --access public"),
        )
        self.hook("ask:twine upload", leadbash("s1", "python -m twine upload dist/*"))
        self.hook(
            "ask:docker image push", leadbash("s1", "docker image push reg/app:1")
        )
        self.hook(
            "ask:cargo publish", leadbash("s1", "cd core && cargo publish -p core")
        )
        self.hook(
            "silent",
            leadbash("s1", "npm run build; npm pack; docker build -t x .; cargo build"),
        )
        # the verb past valued options, a computed verb, a --push flag, text eval runs
        self.hook(
            "ask:npm --registry r --tag beta --otp 1 publish",
            leadbash("s1", "npm --registry r --tag beta --otp 1 publish"),
        )
        self.hook("ask:npm \\$V", leadbash("s1", "V=publish; npm $V"))
        self.hook(
            "ask:docker buildx build --push",
            leadbash("s1", "docker buildx build --push -t reg/app ."),
        )
        self.hook("ask:eval", leadbash("s1", "X='npm publish'; eval $X"))
        self.hook("ask:gradlew publish", leadbash("s1", "./gradlew publish"))
        self.hook(
            "silent",
            leadbash("s1", "docker run -v $PWD:/app -e K=$K img npm test"),
        )
        # the text names the action it matched, past the excerpt of a long command (live: the
        # excerpt showed no gh at all)
        self.hook(
            "ask:`gh pr close 9` in `echo",
            leadbash("s1", "echo x; " * 30 + "gh pr close 9"),
        )
        # read as bash reads the command: wrapped forms count, quoted text does not, and a long
        # line is read in linear time (a regex took 36 s on 1,000 repeats of `gh pr x`)
        self.hook(
            "ask:timeout 30 gh pr close 5", leadbash("s1", "timeout 30 gh pr close 5")
        )
        self.hook(
            "ask:bash -c", leadbash("s1", "bash -c 'git push origin --delete old'")
        )
        self.hook("silent", leadbash("s1", "echo 'gh pr close 5'"))
        # text a shell runs that the reader cannot follow, or one it fails on, asks when it names
        # gh or push
        self.hook("ask:eval", leadbash("s1", "X='gh pr close 5'; eval $X"))
        self.hook("ask:bash", leadbash("s1", "echo 'gh pr close 5' | bash"))
        deep = "$(" * 1500 + "gh pr close 5" + ")" * 1500
        self.hook("ask:acts on the hosted repository", leadbash("s1", deep))
        # ...and only then: an unreadable command that names gh or push for anything else passes
        # (a stub gh, a JS .push(, a plain push held 5 agents' local work on 2026-10-31)
        self.hook(
            "silent",
            leadbash("s1", "X=$(ls); bash -c $X; node -e a.push(1); gh cache delete 5"),
        )
        self.hook("silent", leadbash("s1", "source ./env.sh; git push origin main"))
        self.hook(
            "silent", leadbash("s1", "eval $X; gh pr view 5; git log --grep merge")
        )
        # a script file the command runs is read: an outward action in it asks
        self.write(T / "scripts/merge.sh", "gh pr merge 7 --squash\n")
        self.hook(
            "ask:acts on the hosted repository",
            leadbash("s1", f"bash {T}/scripts/merge.sh"),
        )
        self.hook("silent", leadbash("s1", f"bash {T}/scripts/env.sh"))


if __name__ == "__main__":
    unittest.main()
