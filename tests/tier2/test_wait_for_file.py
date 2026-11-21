"""wait-for-file, the command (Request 29 from bernstein; PLAN.md "Settled" 64). Called in-process
with the clock and the sleep replaced, but for two runs of the program itself."""
import contextlib
import io
import os
import pathlib
import subprocess
import sys

from lobstertools import waitfile

COMMAND = pathlib.Path(__file__).resolve().parents[2] / "wait-for-file"


class Clock:
    """Fake time: each sleep advances it and then does what was planned for that moment."""

    def __init__(self, monkeypatch, plan=None):
        self.time, self.sleeps, self.plan = 0.0, [], dict(plan or {})
        monkeypatch.setattr(waitfile, "now", lambda: self.time)
        monkeypatch.setattr(waitfile, "sleep", self.sleep)

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.time += seconds
        action = self.plan.get(self.time)
        if action:
            action()


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = waitfile.main(list(argv))
        except SystemExit as exit_:
            code = exit_.code
    return code, out.getvalue(), err.getvalue()


def test_prints_the_path_and_exits_0_when_the_file_is_there(tmp_path, monkeypatch):
    clock = Clock(monkeypatch)
    there = tmp_path / "delivery.wav"
    there.write_bytes(b"x")
    assert run(str(there)) == (0, "%s\n" % there, "")
    assert clock.sleeps == []


def test_waits_for_a_path_with_spaces_and_a_dollar(tmp_path, monkeypatch):
    odd = tmp_path / "my files" / "take $1 'final'.wav"
    odd.parent.mkdir()
    clock = Clock(monkeypatch, {3: lambda: odd.write_bytes(b"done")})
    assert run(str(odd), "--timeout", "60") == (0, "%s\n" % odd, "")
    assert clock.time == 3


def test_exits_5_at_the_timeout_saying_the_file_did_not_appear(tmp_path, monkeypatch):
    Clock(monkeypatch)
    missing = tmp_path / "never.wav"
    code, out, err = run(str(missing), "--timeout", "4")
    assert (code, out) == (5, "")
    assert err == "wait-for-file: %s did not appear in 4 seconds\n" % missing


def test_stable_waits_for_a_growing_file_to_stop(tmp_path, monkeypatch):
    growing = tmp_path / "half.wav"

    def grow(size):
        return lambda: growing.write_bytes(b"x" * size)

    clock = Clock(monkeypatch, {1: grow(1), 2: grow(2), 3: grow(3)})
    assert run(str(growing), "--stable", "5") == (0, "%s\n" % growing, "")
    assert clock.time == 8


def test_stable_says_still_changing_at_the_timeout(tmp_path, monkeypatch):
    growing = tmp_path / "half.wav"
    Clock(monkeypatch, {n: (lambda n=n: growing.write_bytes(b"x" * n)) for n in range(1, 30)})
    code, out, err = run(str(growing), "--stable", "5", "--timeout", "10")
    assert (code, out) == (5, "")
    assert err == ("wait-for-file: %s was still changing after 10 seconds (--stable 5)\n"
                   % growing)


def test_without_glob_a_star_is_part_of_the_name(tmp_path, monkeypatch):
    Clock(monkeypatch)
    (tmp_path / "a.wav").write_bytes(b"a")
    code, _, err = run(str(tmp_path / "*.wav"), "--timeout", "2")
    assert code == 5 and "did not appear" in err


def test_glob_prints_every_match(tmp_path, monkeypatch):
    Clock(monkeypatch)
    for name in ("b.wav", "a.wav", "c.txt"):
        (tmp_path / name).write_bytes(b"x")
    assert run(str(tmp_path / "*.wav"), "--glob") == (
        0, "%s\n%s\n" % (tmp_path / "a.wav", tmp_path / "b.wav"), "")


def test_refuses_a_negative_timeout_or_stable(tmp_path, monkeypatch):
    Clock(monkeypatch)
    for flag in ("--timeout", "--stable"):
        code, out, err = run(str(tmp_path / "f"), flag, "-1")
        assert (code, out) == (2, "")
        assert "%s must be 0 or more" % flag in err


def test_needs_a_path():
    code, _, err = run()
    assert code == 2 and "PATH" in err


def test_help_says_what_it_does():
    code, out, _ = run("--help")
    assert code == 0
    assert "wait-for-file" in out and "--stable" in out and "--glob" in out


def test_writes_nothing(tmp_path, monkeypatch):
    Clock(monkeypatch)
    (tmp_path / "a").write_bytes(b"a")
    before = sorted(os.listdir(tmp_path))
    run(str(tmp_path / "a"), "--stable", "2")
    run(str(tmp_path / "b"), "--timeout", "2")
    assert sorted(os.listdir(tmp_path)) == before


def test_runs_as_a_program(tmp_path):
    there = tmp_path / "x y.wav"
    there.write_bytes(b"x")
    done = subprocess.run([sys.executable, str(COMMAND), str(there)], capture_output=True,
                          text=True, cwd=str(tmp_path), check=False)
    assert (done.returncode, done.stdout, done.stderr) == (0, "%s\n" % there, "")
    done = subprocess.run([sys.executable, str(COMMAND), str(tmp_path / "no"), "--timeout",
                           "0.2"], capture_output=True, text=True, check=False)
    assert done.returncode == 5 and "did not appear in 0.2 seconds" in done.stderr
