"""script-guard in a claw (KIND=code): only an interpreter given an inline program is refused."""
import pytest

from lobstertools import guard
from lobstertools.guard import commands

INLINE = [
    ("python3 -c 'print(1)'", "an inline program (python3 -c)"),
    ("python3 -uc 'print(1)'", "an inline program (python3 -c)"),
    ("python3 -", "an inline program (python3 -)"),
    ("python3 - <<'EOF'\nprint(1)\nEOF", "an inline program (python3 -)"),
    ("python3 <<'EOF'\nprint(1)\nEOF", "an inline program (python3 on standard input)"),
    ("python3 <<< 'print(1)'", "an inline program (python3 on standard input)"),
    ("echo 'print(1)' | python3", "an inline program (python3 on standard input)"),
    ("perl -e 'print 1'", "an inline program (perl -e)"),
    ("perl -0pi -e 's/a/b/' f", "an inline program (perl -e)"),
    ("perl -lane 'print $F[0]' f", "an inline program (perl -e)"),
    ("ruby -e 'puts 1'", "an inline program (ruby -e)"),
    ("node -e 1", "an inline program (node -e)"),
    ("node --eval 1", "an inline program (node --eval)"),
    ("node -p 1", "an inline program (node -p)"),
    ("osascript -e 'beep'", "an inline program (osascript -e)"),
    ("php -r 'echo 1;'", "an inline program (php -r)"),
    ("lua -e 'print(1)'", "an inline program (lua -e)"),
    ("Rscript -e 1", "an inline program (Rscript -e)"),
    ("bash <<'EOF'\nls\nEOF", "an inline program (bash on standard input)"),
    ("cat steps | sh", "an inline program (sh on standard input)"),
    ("sh -s <<'EOF'\nls\nEOF", "an inline program (sh on standard input)"),
    ("bash -c 'python3 -c 1'", "an inline program (python3 -c)"),
    ("ls $(python3 -c 'print(1)')", "an inline program (python3 -c)"),
    ("X=1 python3 -c 1", "an inline program (python3 -c)"),
    (".venv/bin/python -c 1", "an inline program (python -c)"),
]

ALLOWED = [
    "python3 kept-scripts/count.py",
    "python3 kept-scripts/count.py <<'EOF'\ninput\nEOF",
    "python3 -m pytest -q",
    ".venv/bin/python -m venv x",
    "python3 -u -W ignore kept-scripts/count.py",
    "python3 < kept-scripts/count.py",
    "perl -i.bak -p kept-scripts/fix.pl notes.md",
    "perl -I/usr/share/perl5 kept-scripts/a.pl",
    "ruby -I lib kept-scripts/a.rb",
    "node kept-scripts/a.js",
    "osascript kept-scripts/a.scpt",
    "for f in a b; do ls \"$f\"; done",
    "while true; do break; done",
    "sleep 1",
    "f() { ls; }",
    "sh kept-scripts/tier3.sh",
    "sh -s < kept-scripts/steps.sh",
    "bash -c 'git status && ls'",
    "python3 --version",
    "sh",
]


def judge(command, kind, **more):
    """The guard's judge, from a working folder that is not a temporary one, wherever the suite
    itself is run from (relative paths in these commands are judged against it)."""
    return guard.judge(command, kind, cwd="/project", **more)


@pytest.mark.parametrize("command, reason", INLINE)
def test_an_inline_program_is_refused_in_a_claw(command, reason):
    assert judge(command, "code") == reason


@pytest.mark.parametrize("command", ALLOWED)
def test_a_kept_file_a_loop_and_sleep_are_allowed_in_a_claw(command):
    assert judge(command, "code") is None


def test_a_file_descriptor_before_a_redirection_is_not_a_word():
    assert [c.words for c in commands("ls -l 2>&1 >out 2>> err")] == [["ls", "-l"]]
