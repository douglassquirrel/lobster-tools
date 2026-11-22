"""secrets run passes a stop on to the command it runs (Request 01 from google-docs-tools; PLAN.md
"Settled" 77, 78). secrets is started as a program here, since a signal must reach its own process;
the command is the stand-in tests/stubs/secretstub in its "wait" mode."""
import os
import pathlib
import pty
import select
import signal
import subprocess
import sys
import time

CHECKOUT = pathlib.Path(__file__).resolve().parents[2]
STUB = str(CHECKOUT / "tests" / "stubs" / "secretstub")
COMMAND = str(CHECKOUT / "secrets")
VALUE = "masked-value-5678"


def ready(folder, how_long=10):
    """The stand-in's pid, once it has set its traps."""
    pid_file = folder / "pid"
    deadline = time.monotonic() + how_long
    while not pid_file.exists():
        assert time.monotonic() < deadline, "the command never started"
        time.sleep(0.01)
    return int(pid_file.read_text())


def gone(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


def finish(secrets, stub):
    """secrets' output once it has ended; if it has not within 15 seconds, both are stopped and
    the test fails."""
    try:
        return secrets.communicate(timeout=15)
    except subprocess.TimeoutExpired:
        secrets.kill()
        secrets.communicate()
        if not gone(stub):
            os.kill(stub, signal.SIGKILL)
        raise AssertionError("secrets did not end")


def start(vault, tag, ignore_term=False):
    """secrets run in a session of its own: no terminal, as for a background command."""
    if not (vault.root / "one").exists():
        vault.make("one", "export ONE_A='%s'\n" % VALUE)
    folder = vault.tmp / tag
    folder.mkdir()
    if ignore_term:
        (folder / "ignore-term").touch()
    secrets = subprocess.Popen(
        [sys.executable, COMMAND, "run", "one", *vault.r, "--", STUB, "wait", str(folder), "ONE_A"],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=True)
    return secrets, folder


def test_each_stop_sent_to_secrets_reaches_the_command_and_its_code_comes_back(vault):
    for signum, name, code in ((signal.SIGTERM, "TERM", 143), (signal.SIGINT, "INT", 130),
                               (signal.SIGHUP, "HUP", 129)):
        secrets, folder = start(vault, name)
        stub = ready(folder)
        secrets.send_signal(signum)
        out, err = finish(secrets, stub)
        assert (secrets.returncode, out, err) == (code, b"out:[secret]\n", b""), name
        assert (folder / "got").read_text() == name + "\n"
        assert gone(stub), "the command was left running after %s" % name


def test_a_command_that_ignores_the_stop_is_waited_for(vault):
    secrets, folder = start(vault, "ignoring", ignore_term=True)
    stub = ready(folder)
    secrets.send_signal(signal.SIGTERM)
    (folder / "go").touch()
    out, err = finish(secrets, stub)
    assert (secrets.returncode, out, err) == (0, b"out:[secret]\n", b"")
    assert gone(stub)


def foreground(vault, keys):
    """secrets run in the foreground of a terminal of its own (pty.fork); KEYS(master, pid, stub)
    does the test's part. Returns secrets' exit code and what the command logged."""
    vault.make("one", "export ONE_A='%s'\n" % VALUE)
    folder = vault.tmp / "stub"
    folder.mkdir()
    pid, master = pty.fork()
    if pid == 0:  # the child: become secrets, in the terminal's foreground
        try:
            os.execv(sys.executable, [sys.executable, COMMAND, "run", "one", *vault.r, "--", STUB,
                                      "wait", str(folder), "ONE_A"])
        finally:
            os._exit(99)
    stub = ready(folder)
    keys(master, pid, stub)
    shown, status = b"", None
    deadline = time.monotonic() + 15
    while status is None:  # read the terminal until secrets has ended, so it is never held up
        if select.select([master], [], [], 0.05)[0]:
            try:
                shown += os.read(master, 1024)
            except OSError:
                pass
        done, code = os.waitpid(pid, os.WNOHANG)
        if done:
            status = code
        elif time.monotonic() > deadline:
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)
            os.kill(stub, signal.SIGKILL)
            raise AssertionError("secrets did not end; the terminal showed %r" % shown)
    os.close(master)
    assert gone(stub)
    assert VALUE.encode() not in shown
    return os.waitstatus_to_exitcode(status) if hasattr(os, "waitstatus_to_exitcode") else \
        (status >> 8), (folder / "got").read_text()


def test_in_a_terminals_foreground_a_kill_int_is_not_passed_on_but_a_term_is(vault):
    def keys(master, pid, stub):
        os.kill(pid, signal.SIGINT)
        os.kill(pid, signal.SIGTERM)

    assert foreground(vault, keys) == (143, "TERM\n")


def test_in_a_terminals_foreground_a_ctrl_c_reaches_the_command_once(vault):
    def keys(master, pid, stub):
        os.write(master, b"\x03")

    assert foreground(vault, keys) == (130, "INT\n")
