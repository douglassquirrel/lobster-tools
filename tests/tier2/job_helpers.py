"""Shared by job's tier 2 tests that run jobs: the command called in-process in a scratch working
folder with the clock fixed, and the stand-in job tests/stubs/jobstub, run by its full path."""
import contextlib
import fcntl
import hashlib
import io
import json
import os
import pathlib
import subprocess
import sys
import time

import pytest

from lobstertools import job

NOW = "2026-11-21T16:30:00+00:00"
HERE = pathlib.Path(__file__).resolve().parent
STUB = str(HERE.parent / "stubs" / "jobstub")
COMMAND = str(HERE.parents[1] / "job")


class Scene:
    def __init__(self, tmp_path, monkeypatch):
        self.tmp = tmp_path
        self.stub = tmp_path / "stub"
        self.stub.mkdir()
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LOBSTER_JOB_NOW", NOW)
        monkeypatch.setenv("JOBSTUB_DIR", str(self.stub))
        self.queue = tmp_path / "jobs" / "default"
        self.runners = []

    def run(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = job.main(list(argv))
            except SystemExit as exit_:
                code = exit_.code
        return code, out.getvalue(), err.getvalue()

    def add(self, name, code=0, *more, go_on=False):
        flags = ["--go-on"] if go_on else []
        result = self.run("add", *flags, "--", STUB, name, str(code), *more)
        assert result[0] == 0, result
        return result

    def log(self):
        path = self.stub / "log"
        return path.read_text("utf-8").splitlines() if path.exists() else []

    def hold(self, name):
        (self.stub / ("hold-" + name)).write_text("")

    def go(self, name):
        (self.stub / ("go-" + name)).write_text("")

    def ids(self, which):
        folder = self.queue / which
        return sorted(os.listdir(folder)) if folder.exists() else []

    def read(self, which, ident, name):
        return json.loads((self.queue / which / ident / name).read_text("utf-8"))

    def output(self, which, ident):
        return (self.queue / which / ident / "output").read_bytes()

    def wait_until(self, test, seconds=10):
        """Real time, for a runner started as a program: look every hundredth of a second."""
        limit = time.monotonic() + seconds
        while not test():
            assert time.monotonic() < limit, "gave up waiting"
            time.sleep(0.01)

    def start_runner(self, *more):
        runner = subprocess.Popen([sys.executable, COMMAND, "run", *more], cwd=str(self.tmp),
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.runners.append(runner)
        return runner

    def release(self):
        """After each test, passed or failed: let every held stand-in go, and see every runner
        it started end, so none is left polling."""
        for hold in self.stub.glob("hold-*"):
            (self.stub / ("go-" + hold.name[len("hold-"):])).write_text("")
        for runner in self.runners:
            if runner.poll() is None:
                try:
                    runner.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    runner.kill()
                    runner.communicate()

    @contextlib.contextmanager
    def runner_lock_held(self):
        self.queue.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self.queue / "runner.lock"), os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def left_running(self, ident, pid, argv=("sleep", "1")):
        """A job in running/ as a runner that stopped would leave it."""
        folder = self.queue / "running" / ident
        folder.mkdir(parents=True)
        for which in ("waiting", "done", "cancelled"):
            (self.queue / which).mkdir(exist_ok=True)
        (folder / "job.json").write_text(json.dumps(
            {"id": ident, "argv": list(argv), "cwd": str(self.tmp), "added": NOW,
             "go_on": False}), "utf-8")
        (folder / "started.json").write_text(json.dumps({"started": NOW, "pid": pid}), "utf-8")
        (folder / "output").write_bytes(b"")


def dead_pid():
    """The process id of a program that has ended and been reaped."""
    process = subprocess.Popen(["/bin/sh", "-c", "exit 0"])
    process.wait()
    return process.pid


@pytest.fixture(scope="session", autouse=True)
def jobstub_is_never_written_over():
    before = hashlib.sha256(pathlib.Path(STUB).read_bytes()).hexdigest()
    yield
    assert hashlib.sha256(pathlib.Path(STUB).read_bytes()).hexdigest() == before


@pytest.fixture
def scene(tmp_path, monkeypatch):
    made = Scene(tmp_path, monkeypatch)
    yield made
    made.release()
