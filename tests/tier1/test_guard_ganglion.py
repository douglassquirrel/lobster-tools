"""script-guard in a ganglion (KIND=non-code): bernstein's examples from Request 34, refused and
allowed, judged by the pure judge()."""
import pytest

from lobstertools import guard

REFUSED = [
    ('for f in *.m4a; do ffprobe "$f"; done', "a loop (for)"),
    ('while read l; do echo "$l"; done < list', "a loop (while)"),
    ("until [ -f x ]; do sleep 30; done", "a loop (until)"),
    ("select x in a b; do echo $x; done", "a loop (select)"),
    ("sleep 60", "sleep"),
    ("python3 -c 1", "an interpreter (python3)"),
    ("python3 - <<'EOF'\nprint(1)\nEOF", "an interpreter (python3)"),
    ("perl -0pi -e 's/a/b/' f", "an interpreter (perl)"),
    ("f() { ls; }; f", "a shell function definition (f)"),
    ("function f { ls; }", "a shell function definition (f)"),
    ("bash -c 'for i in 1; do :; done'", "a loop (for)"),
    ("ls && for x in 1; do :; done", "a loop (for)"),
    ("echo $(for i in 1 2; do echo $i; done)", "a loop (for)"),
    ('echo "$(sleep 1)"', "sleep"),
    ("echo `python3 -c 1`", "an interpreter (python3)"),
    ("eval 'sleep 5'", "sleep"),
    ("sh build.sh", "a shell given a script or standard input (sh)"),
    ("bash <<'EOF'\nls\nEOF", "a shell given a script or standard input (bash)"),
    ("cat list | zsh", "a shell given a script or standard input (zsh)"),
    ("ruby x.rb", "an interpreter (ruby)"),
    ("osascript -e 'beep'", "an interpreter (osascript)"),
    ("/usr/bin/python3 tool.py", "an interpreter (python3)"),
    (".venv/bin/python -m pytest", "an interpreter (python)"),
    ("python3.9 x.py", "an interpreter (python3.9)"),
    ("node -e 1", "an interpreter (node)"),
    ("if true; then sleep 2; fi", "sleep"),
    ("{ sleep 1; }", "sleep"),
    ("(sleep 1)", "sleep"),
    ("X=1 sleep 1", "sleep"),
    ("ls\nsleep 1", "sleep"),
    ("cat <<EOF\n$(sleep 1)\nEOF", "sleep"),
    ("diff <(sleep 1) b", "sleep"),
]

ALLOWED = [
    'git commit -m "for the record, while waiting"',
    "grep -n 'for ' DIARY.md",
    "cat > notes.md <<'EOF'\nfor x in y; do\n  sleep 1\ndone\nEOF",
    "cat > notes.md <<\"EOF\"\n$(sleep 1)\nEOF",
    "sed -i '' 's/old/new/' CLAUDE.md",
    "awk '{print $1}' list.txt",
    "cat while.txt",
    "ls for",
    "lobster-mail wait --timeout 2700",
    "echo 'sleep 5'",
    "echo \\for x",
    "git log --oneline | head -5",
    "python3 --version",
    "perl --help",
    'git commit -F - <<\'EOF\'\nUntil now, for each file, python3 -c was run.\nEOF',
    'git commit -m "$(cat <<\'EOF\'\nA message (with brackets) for sleep\nEOF\n)"',
    "# for x in y\nls",
    "echo $((1 + 2))",
    "test -f x && echo yes || echo no",
    "[[ -f x && -d y ]] && ls",
    "",
]


def judge(command, kind, **more):
    """The guard's judge, from a working folder that is not a temporary one, wherever the suite
    itself is run from (relative paths in these commands are judged against it)."""
    return guard.judge(command, kind, cwd="/project", **more)


@pytest.mark.parametrize("command, reason", REFUSED)
def test_bernsteins_refused_examples_are_refused_with_the_reason(command, reason):
    assert judge(command, "non-code") == reason


@pytest.mark.parametrize("command", ALLOWED)
def test_bernsteins_allowed_examples_are_allowed(command):
    assert judge(command, "non-code") is None
