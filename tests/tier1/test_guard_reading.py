"""What script-guard cannot read is said, not guessed ("Settled" 82: allowed by the hook, with a
line on standard error); and a long command line is judged quickly."""
import sys
import time

import pytest

from lobstertools import guard
from lobstertools.guard import Unreadable, commands

UNREADABLE = [
    ("echo 'unclosed", "a ' is not closed"),
    ('echo "unclosed', 'a " is not closed'),
    ("echo $(ls", "a $( ) is not closed"),
    ("echo `ls", "a ` is not closed"),
    ("echo ${HOME", "a ${ } is not closed"),
    ("echo $((1 +", "a $(( )) is not closed"),
    ("echo $'x", "a $' is not closed"),
    ("cat <<", "a heredoc has no delimiter"),
    ("case $x in a) sleep 1;; esac", "case is not read"),
]


def judge(command, kind, **more):
    """The guard's judge, from a working folder that is not a temporary one, wherever the suite
    itself is run from (relative paths in these commands are judged against it)."""
    return guard.judge(command, kind, cwd="/project", **more)


@pytest.mark.parametrize("command, why", UNREADABLE)
def test_a_command_it_cannot_read_raises_unreadable_saying_why(command, why):
    with pytest.raises(Unreadable) as raised:
        judge(command, "non-code")
    assert str(raised.value) == why


def test_a_project_of_another_kind_is_not_even_read():
    assert judge("echo 'unclosed", "feeler") is None


def test_nested_substitutions_are_followed_to_any_depth():
    assert judge("echo $(echo $(echo `echo \\`sleep 1\\``))", "non-code") == "sleep"
    assert judge('echo "$(echo "$(sleep 1)")"', "non-code") == "sleep"


def test_a_heredoc_body_runs_to_its_delimiter_and_what_follows_is_judged():
    text = "cat > a.md <<'EOF'\nfor x in y\nEOF\nsleep 1"
    assert judge(text, "non-code") == "sleep"
    assert judge("cat <<-\tEND\n\tsleep 1\n\tEND\nls", "non-code") is None
    assert judge("cat <<A <<'B'\n$(sleep 1)\nA\nfor\nB\n", "non-code") == "sleep"


def test_the_words_of_a_command_are_its_words_after_quotes_are_taken_away():
    assert [c.words for c in commands("a 'b c' \"d\\\"e\" f\\ g $'h' 2>&1 | i <<< j")] == [
        ["a", "b c", 'd"e', "f g", "h"], ["i"]]


def test_a_long_command_line_is_judged_in_well_under_a_tenth_of_a_second():
    long = " | ".join("grep -e 'for x in %d' file%d.txt" % (n, n) for n in range(400))
    long += "\ncat > notes.md <<'EOF'\n" + "while true; do sleep 1; done\n" * 400 + "EOF\n"
    assert len(long) > 20000
    tracer = sys.gettrace()  # coverage's tracer slows it tenfold: time the guard, not coverage
    sys.settrace(None)
    try:
        start = time.perf_counter()
        verdict = judge(long, "non-code")
        took = time.perf_counter() - start
    finally:
        sys.settrace(tracer)
    assert verdict is None
    assert took < 0.1
