"""shell_cmd.py's reading of a command line, checked against bash itself where bash can say.

- Words: a simple command's words, quotes and escapes read, against bash's `set --` of the same
  text.
- Lists: the simple commands a line of `&&`, `||`, `;`, `|`, groups, subshells, comments,
  continuations and heredocs runs, against the commands bash runs: with PATH empty every command
  falls to command_not_found_handle, which records its words.
- Where shell_cmd differs from bash on purpose (it expands nothing, and reads a CR as a blank),
  the difference is asserted as expected, and bash is run to show it is one.
- Unwrapping (`env`, `timeout`, `bash -c`, `eval`) bash cannot show: expected events, by hand.

The bash checks skip when bash is absent.
"""

import os
import shutil
import subprocess
import tempfile
import unittest

import support  # noqa: F401  (puts the scripts on sys.path)

import shell_cmd

BASH = shutil.which("bash")
# a backslash: the `$'\u…'` cases are built with it, so no `\u` sits in a string literal
BS = chr(92)

# Simple commands whose words bash and shell_cmd must read alike.
WORDS = [
    "git push origin main",
    "git  push\torigin   main",
    "'git' \"push\" origin",
    r"g\it p\ush origin",
    "git \\\n push origin",
    "echo \"a b\" 'c d' e\\ f",
    'echo "it\'s" \'say "hi"\'',
    r'echo "a\"b" "c\\d" "e\$f" "g\`h"',
    r'echo "\a\b" "\n"',
    r"echo 'a\nb' 'a\'",
    r"echo 'a'\''b'",
    'echo "line one\\\ncontinued"',
    "echo '' \"\" a''b",
    "echo \"a\"b'c'$'d'",
    r"echo a\\b a\ ",
    "echo a#b # a comment && git push",
    r"echo \#not-a-comment",
    r"echo x\\",
    'echo café "naïve"',
    "echo -- -n -e",
    "FOO='a b' BAR=1 git -C \"/a b/wt\" commit -m 'x y'",
    "env FOO=1 nice -n 5 git push",
    "echo *.no-such-file",
    'echo $"locale string"',
    r"echo $'a\nb' $'tab\there' $'q\'s' $'\"' $'\?' $'\\'",
    r"echo $'\x70ush' $'\160ush' $'\101\102' $'\x41B' $'\x4' $'it\x27s'",
    r"echo $'\e[0m' $'\E' $'\a\b\f\v\r'",
    f"git $'{BS}u0070ush' $'{BS}U00000070ush'",
    f"echo $'{BS}u263a' $'{BS}u' $'{BS}U'",
    r"echo $'\cA' $'\cz' $'\c'",
    r"echo $'\q' $'\x' $'p\ush'",
]

# Lines of several commands, every word static and no command a builtin: the commands bash runs,
# in order. `fail` is a command whose handler returns 1, so `||` runs what follows it.
LISTS = [
    "git a && git b",
    "git a;git b",
    "git a&&git b",
    "fail a || git b",
    "git a\ngit b",
    "# only a comment\ngit a # && git b",
    "git a && \\\ngit b",
    "(cd /tmp && ls) && git b",
    "{ git a; git b; }",
    "! git a; git b",
    "if git a; then git b; fi",
    "time git a",
    "FOO=1 BAR=2 git a && X=1 git b",
    "git a >out 2>&1 && git b </dev/null",
    "cat <<EOF && git b\nfoo && bar\nEOF\ngit c",
    "cat <<'EOF'\ngit push origin main\nEOF",
    'cat <<"E"OF\n$(git push)\nEOF\ngit d',
    "cat <<-EOF\n\tgit push\n\tEOF\ngit e",
    "cat <<A <<B\na\nA\nb\nB\ngit f",
    'cat <<< "git a && git b"; git c',
    r"\git a; 'git' b; g\it c",
    "echo 'git push' && git log --grep push",
    "git a | git b",
    "git a & git b",
]

# What shell_cmd reads where bash reads otherwise on purpose: (text, shell_cmd's words, static).
EXPECTED_DIFFERENCES = [
    ("echo $HOME", ["echo", "$HOME"], False),
    ("echo ${HOME}/x", ["echo", "${HOME}/x"], False),
    ("echo $(echo hi)", ["echo", "$(echo hi)"], False),
    ("echo `echo hi`", ["echo", "`echo hi`"], False),
    ("echo $((1 + 2))", ["echo", "$((1 + 2))"], False),
    ("echo ~/x", ["echo", "~/x"], True),
    ("echo {a,b}", ["echo", "{a,b}"], True),
    ("echo a\rb", ["echo", "a", "b"], True),
]


def bash_words(text, cwd):
    """bash's words of a simple command, as `set --` reads it."""
    r = subprocess.run(
        [
            BASH,
            "--norc",
            "--noprofile",
            "-c",
            'eval "set -- $1"; printf "%s\\0" "$@"',
            "_",
            text,
        ],
        capture_output=True,
        cwd=cwd,
        env={"PATH": "/nonexistent-dsp", "HOME": cwd, "LANG": "C.UTF-8"},
        check=False,
    )
    return r.stdout.decode("utf-8", "surrogateescape").split("\0")[:-1]


HANDLER = r"""
command_not_found_handle() {
    { printf '%s\0' "$@"; printf '\1\0'; } >&3
    [ "$1" != fail ]
}
{ eval "$1"; } 3>"$2" >/dev/null 2>&1
"""


def bash_runs(text, cwd):
    """The argv of each command bash runs for text that it cannot find (every non-builtin)."""
    out = os.path.join(cwd, "runs")
    subprocess.run(
        [BASH, "--norc", "--noprofile", "-c", HANDLER, "_", text, out],
        cwd=cwd,
        env={"PATH": "/nonexistent-dsp", "HOME": cwd, "LANG": "C.UTF-8"},
        capture_output=True,
        check=False,
    )
    with open(out, "rb") as f:
        fields = f.read().decode("utf-8", "surrogateescape").split("\0")[:-1]
    runs, cur = [], []
    for field in fields:
        if field == "\1":
            runs.append(cur)
            cur = []
        else:
            cur.append(field)
    return runs


class ShellCmdAgainstBash(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not BASH:
            raise unittest.SkipTest("bash is not installed")
        cls._tmp = tempfile.TemporaryDirectory(prefix="dsp-sh-")
        cls.cwd = cls._tmp.name
        r = subprocess.run(
            [BASH, "--norc", "--noprofile", "-c", "compgen -b"],
            capture_output=True,
            text=True,
            check=True,
        )
        cls.builtins = set(r.stdout.split())

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_words(self):
        for text in WORDS:
            with self.subTest(text):
                tokens = shell_cmd._scan(text)[0]
                self.assertTrue(
                    all(isinstance(t, shell_cmd.Word) and t.static for t in tokens),
                    f"corpus case is not one static simple command: {tokens}",
                )
                self.assertEqual([t.text for t in tokens], bash_words(text, self.cwd))

    def test_lists(self):
        for text in LISTS:
            with self.subTest(text):
                cmds = [c for kind, c in shell_cmd.events(text) if kind == "cmd"]
                self.assertTrue(
                    all(w.static for c in cmds for w in c.words),
                    "corpus case has a computed word",
                )
                mine = [c.argv for c in cmds if c.words and c.name not in self.builtins]
                theirs = bash_runs(text, self.cwd)
                if any(op in text for op in ("|", "&")) and "&&" not in text:
                    # a pipeline's and a background job's commands run at once
                    mine, theirs = sorted(mine), sorted(theirs)
                self.assertEqual(mine, theirs)

    def test_expected_differences(self):
        for text, words, static in EXPECTED_DIFFERENCES:
            with self.subTest(text):
                tokens = shell_cmd._scan(text)[0]
                self.assertEqual([t.text for t in tokens], words)
                self.assertEqual(all(t.static for t in tokens), static)
                self.assertNotEqual(
                    bash_words(text, self.cwd), words, "bash reads it alike"
                )


# (text, [(argv, assignment names, the operator before it)] of its commands)
UNWRAP_CASES = [
    ("env FOO=1 BAR=2 git push", [(["git", "push"], ["FOO", "BAR"], None)]),
    ("timeout 60 git push origin", [(["git", "push", "origin"], [], None)]),
    ("nice -n 5 nohup git push", [(["git", "push"], [], None)]),
    ("command -v git", [(["command", "-v", "git"], [], None)]),
    (
        "bash -c 'git push; cd x'",
        [(["git", "push"], [], None), (["cd", "x"], [], ";")],
    ),
    ("eval git push", [(["git", "push"], [], None)]),
    ("sudo git push", [(["sudo", "git", "push"], [], None)]),
    (
        "cd a && cd b; cd - || ls",
        [
            (["cd", "a"], [], None),
            (["cd", "b"], [], "&&"),
            (["cd", "-"], [], ";"),
            (["ls"], [], "||"),
        ],
    ),
    (
        "X=$(git rev-parse HEAD) git push",
        [(["git", "rev-parse", "HEAD"], [], None), (["git", "push"], ["X"], None)],
    ),
    (
        "echo `git push`",
        [(["git", "push"], [], None), (["echo", "`git push`"], [], None)],
    ),
]


class Unwrapping(unittest.TestCase):
    """What the reader makes of wrappers, nested shells and `cd` chains, which no bash run shows."""

    def test_events(self):
        for text, want in UNWRAP_CASES:
            with self.subTest(text):
                got = [
                    (c.argv, [name for name, _ in c.assigns], c.after)
                    for kind, c in shell_cmd.events(text)
                    if kind == "cmd"
                ]
                self.assertEqual(got, want)

    def test_opaque(self):
        for text in ("bash script.sh", "source ./env.sh", 'eval "$X"', "echo x | bash"):
            with self.subTest(text):
                kinds = [kind for kind, _ in shell_cmd.events(text)]
                self.assertIn("opaque", kinds)

    def test_escape_past_unicode_reads(self):
        tokens = shell_cmd._scan(r"echo $'\UFFFFFFFF' $'\U110000'")[0]
        self.assertEqual(len(tokens), 3)


if __name__ == "__main__":
    unittest.main()
