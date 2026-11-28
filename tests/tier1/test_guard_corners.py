"""Corners of the shell script-guard reads: continued lines, $'...', nested ${ } and $(( )), an
arithmetic command, -- among options, values attached to options, and nothing given at all."""
import pytest

from lobstertools import guard
from lobstertools.guard import commands

GANGLION = [
    ("ls \\\n  && sleep 1", "sleep"),
    ("sl\\\neep 1", "sleep"),
    ("echo $'it\\'s'; sleep 1", "sleep"),
    ("echo ${a:-${b}}; sleep 1", "sleep"),
    ("echo $(( (1 + 2) * 3 )); sleep 1", "sleep"),
    ("(( x = 1 )); sleep 1", "sleep"),
    ("env -- sleep 1", "sleep"),
    ("env -iu X sleep 1", "sleep"),
    ("nice -- python3 x.py", "an interpreter (python3)"),
    ("ls # a comment at the end", None),
    ("(( x ))", None),
    ("ls >", None),
    ("bash", None),
    ("echo 'a' > out; sort < in", None),
]

CLAW = [
    ("python3", None),
    ("python3 -- kept-scripts/x.py", None),
    ("python3 -u -- -", "an inline program (python3 -)"),
    ("node --require x kept-scripts/a.js", None),
    ("node --require=x -e 1", "an inline program (node -e)"),
    ("ruby -Ilib kept-scripts/a.rb", None),
    ("perl -0777 -p kept-scripts/a.pl", None),
    ("perl -l0 -ne 'print'", "an inline program (perl -e)"),
    ("python3 -m", None),
]


def judge(command, kind, **more):
    """The guard's judge, from a working folder that is not a temporary one, wherever the suite
    itself is run from (relative paths in these commands are judged against it)."""
    return guard.judge(command, kind, cwd="/project", **more)


@pytest.mark.parametrize("command, reason", GANGLION)
def test_corners_in_a_ganglion(command, reason):
    assert judge(command, "non-code") == reason


@pytest.mark.parametrize("command, reason", CLAW)
def test_corners_in_a_claw(command, reason):
    assert judge(command, "code") == reason


def test_a_continued_line_joins_its_word():
    assert [c.words for c in commands("ec\\\nho a\\\n b")] == [["echo", "a", "b"]]
