"""script-guard looks through wrappers and judges the command they run ("Settled" 83); xargs and
find -exec running a command that passes are not loops."""
import pytest

from lobstertools import guard

GANGLION_REFUSED = [
    ("env python3 -c 1", "an interpreter (python3)"),
    ("env -i FOO=1 sleep 1", "sleep"),
    ("/usr/bin/env -u X sleep 1", "sleep"),
    ("nohup sleep 5", "sleep"),
    ("time python3 x.py", "an interpreter (python3)"),
    ("time -p sleep 1", "sleep"),
    ("timeout 30 sleep 5", "sleep"),
    ("timeout -s KILL 30 sleep 5", "sleep"),
    ("timeout --kill-after=5 30 python3 x.py", "an interpreter (python3)"),
    ("nice -n 5 sleep 1", "sleep"),
    ("nice -5 sleep 1", "sleep"),
    ("caffeinate -i sleep 5", "sleep"),
    ("caffeinate -t 60 python3 x.py", "an interpreter (python3)"),
    ("command sleep 1", "sleep"),
    ("exec python3 x.py", "an interpreter (python3)"),
    ("exec -a name sleep 1", "sleep"),
    ("xargs perl -e 1", "an interpreter (perl)"),
    ("xargs -n 1 sleep", "sleep"),
    ("xargs -I{} sh -c 'sleep {}'", "sleep"),
    ("xargs -0 -L 1 python3", "an interpreter (python3)"),
    ("find . -exec python3 {} \\;", "an interpreter (python3)"),
    ("find . -name '*.m4a' -execdir sleep 1 ';'", "sleep"),
    ("find . -ok ls {} \\; -exec sleep 1 +", "sleep"),
    ("job add -- sleep 60", "sleep"),
    ("job add --go-on -- python3 x.py", "an interpreter (python3)"),
    ("each a b -- python3 -c {}", "an interpreter (python3)"),
    ("~/projects/code/lobster-tools-code/lobster-tools/each a -- sleep", "sleep"),
    ("secrets run google -- python3 x.py", "an interpreter (python3)"),
    ("nohup env timeout 5 sleep 1", "sleep"),
]

GANGLION_ALLOWED = [
    "xargs ls",
    "xargs",
    "find . -name x -exec ls {} \\;",
    "find . -exec grep -l for {} +",
    "command -v python3",
    "command -V sleep",
    "env",
    "env FOO=1",
    "time ls",
    "job list",
    "job run",
    "secrets check google",
    "secrets run google -- archive-ask --day 2026-11-20",
    "each a b -- ls",
    "timeout 5 ls",
    "nohup lobster-mail wait --timeout 2700",
    "caffeinate",
    "exec >log 2>&1",
    "nice ls",
]


def judge(command, kind, **more):
    """The guard's judge, from a working folder that is not a temporary one, wherever the suite
    itself is run from (relative paths in these commands are judged against it)."""
    return guard.judge(command, kind, cwd="/project", **more)


@pytest.mark.parametrize("command, reason", GANGLION_REFUSED)
def test_a_wrapped_command_is_judged_in_a_ganglion(command, reason):
    assert judge(command, "non-code") == reason


@pytest.mark.parametrize("command", GANGLION_ALLOWED)
def test_a_wrapped_command_that_passes_is_allowed_in_a_ganglion(command):
    assert judge(command, "non-code") is None


def test_wrappers_are_looked_through_in_a_claw_too():
    assert judge("env python3 -c 1", "code") == "an inline program (python3 -c)"
    assert judge("find . -exec perl -e 1 \\;", "code") == "an inline program (perl -e)"
    assert judge("xargs python3 kept-scripts/a.py", "code") is None
    assert judge("each a -- sleep", "code") is None
