"""each started as a program, as a user runs it: --help, a run, and a stop passed on."""
import signal
import subprocess
import sys
import time

import pytest
from each_helpers import COMMAND


def start(bench, *argv):
    return subprocess.Popen([sys.executable, COMMAND, *argv], cwd=str(bench.tmp),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def wait_until(test, seconds=10):
    limit = time.monotonic() + seconds
    while not test():
        assert time.monotonic() < limit, "gave up waiting"
        time.sleep(0.01)


def test_help_says_what_it_does(bench):
    done = subprocess.run([sys.executable, COMMAND, "--help"], capture_output=True, text=True,
                          check=False)
    assert done.returncode == 0
    assert done.stdout.startswith("usage: each [--from FILE|-] [--go-on] [--dry-run] [ITEM ...] "
                                  "-- COMMAND [ARG ...]")
    assert "never through a shell" in " ".join(done.stdout.lower().split())


def test_runs_as_a_program(bench):
    done = subprocess.run([sys.executable, COMMAND, "a", "--", "archive-ask"], cwd=str(bench.tmp),
                          capture_output=True, text=True, check=False)
    assert (done.returncode, done.stdout) == (
        0, "[1/1] archive-ask a\nout 1\nexit 0\n1 ran: 1 succeeded, 0 failed\n")


@pytest.mark.parametrize("signum, logged", [(signal.SIGTERM, "term 1"), (signal.SIGINT, "int 1")])
def test_a_stop_reaches_the_running_command_and_nothing_more_starts(bench, signum, logged):
    (bench.stub / "hold-1").write_text("")
    each = start(bench, "a", "b", "--", "archive-ask")
    try:
        wait_until(lambda: (bench.stub / "held-1").exists())
        each.send_signal(signum)
        out, err = each.communicate(timeout=10)
    finally:
        (bench.stub / "go-1").write_text("")
        if each.poll() is None:
            each.kill()
            each.communicate()
    assert each.returncode == 128 + signum
    assert bench.log() == ["ran 1", logged]
    assert out.splitlines()[-1] == ("stopped by signal %d: 1 of 2 ran (0 succeeded, 1 failed), "
                                    "1 not run" % signum)
    assert "Traceback" not in err
