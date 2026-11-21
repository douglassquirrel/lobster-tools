"""job wait, and job cancel --running (Request 29 from bernstein; PLAN.md "Settled" 64-69)."""
import contextlib
import os
import shlex
import time

from job_helpers import COMMAND, NOW, STUB, dead_pid

from lobstertools import job


class Clock:
    """Fake time for job wait: each sleep advances it and runs what was planned, if anything."""

    def __init__(self, monkeypatch, each=None):
        self.time, self.sleeps, self.each = 0.0, [], each
        monkeypatch.setattr(job, "now", lambda: self.time)
        monkeypatch.setattr(job, "sleep", self.sleep)

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.time += seconds
        if self.each:
            self.each()


def snapshot(top):
    return {str(p.relative_to(top)): p.read_bytes() for p in sorted(top.rglob("*"))
            if p.is_file() and p.name != "log"}


def test_says_at_once_when_the_queue_is_empty(scene, monkeypatch):
    clock = Clock(monkeypatch)
    assert scene.run("wait") == (0, "Queue default is empty: nothing waiting or running\n", "")
    assert clock.sleeps == []


def test_says_at_once_when_jobs_wait_with_no_runner(scene, monkeypatch):
    clock = Clock(monkeypatch)
    scene.add("A")
    scene.add("B")
    assert scene.run("wait") == (0, "Queue default has 2 waiting and no runner; start one in the "
                                    "background with:\n  %s run\n" % shlex.quote(COMMAND), "")
    # five seconds' grace first, for a runner started just before the wait (found by Tier 3)
    assert clock.sleeps == [1] * 5


def test_a_runner_that_starts_in_the_grace_is_waited_on(scene, monkeypatch):
    scene.add("A")
    held = contextlib.ExitStack()

    def runner_starts_at_two_seconds():
        if clock.time == 2:
            held.enter_context(scene.runner_lock_held())

    clock = Clock(monkeypatch, runner_starts_at_two_seconds)
    with held:
        code, out, err = scene.run("wait", "--timeout", "8")
    assert (code, out) == (5, "")
    assert err == "job: nothing ended in 8 seconds\n"


def test_returns_when_the_running_job_ends_naming_it_and_its_exit_code(scene, monkeypatch):
    scene.hold("A")
    scene.add("A", 3)
    runner = scene.start_runner()
    scene.wait_until(lambda: scene.ids("running") == ["0001"] and
                     (scene.queue / "running" / "0001" / "started.json").exists())

    def go_on_a_little():
        scene.go("A")
        time.sleep(0.02)

    Clock(monkeypatch, go_on_a_little)
    code, out, err = scene.run("wait", "--timeout", "600")
    assert (code, err) == (0, "")
    assert out == "Job 0001 ended: exit 3 after 0s: %s A 3\n" % STUB
    runner.communicate(timeout=30)


def test_exits_5_at_the_timeout_naming_the_job_still_running(scene, monkeypatch):
    Clock(monkeypatch)
    scene.left_running("0001", os.getpid())
    with scene.runner_lock_held():
        code, out, err = scene.run("wait", "--timeout", "5")
    assert (code, out) == (5, "")
    assert err == "job: nothing ended in 5 seconds; job 0001 is running, since %s\n" % NOW


def test_says_at_once_when_the_running_job_was_interrupted(scene, monkeypatch):
    Clock(monkeypatch)
    scene.left_running("0001", dead_pid())
    assert scene.run("wait") == (0, ("Job 0001 was interrupted: its runner stopped before it "
                                     "ended, and it is no longer running\n"), "")


def test_waits_on_while_a_job_runs_without_its_runner(scene, monkeypatch):
    Clock(monkeypatch)
    scene.left_running("0001", os.getpid())
    code, _, err = scene.run("wait", "--timeout", "3")
    assert code == 5 and "job 0001 is running, since" in err


def test_wait_writes_nothing(scene, monkeypatch):
    Clock(monkeypatch)
    scene.add("A")
    scene.left_running("0002", os.getpid())
    before = snapshot(scene.tmp)
    scene.run("wait", "--timeout", "2")
    assert snapshot(scene.tmp) == before


def test_wait_refuses_a_negative_timeout(scene):
    code, out, err = scene.run("wait", "--timeout", "-1")
    assert (code, out) == (2, "")
    assert "--timeout must be 0 or more" in err


def test_cancel_running_sends_sigterm_and_the_runner_records_it(scene):
    scene.hold("A")
    scene.add("A")
    scene.add("B")
    runner = scene.start_runner()
    scene.wait_until(lambda: (scene.queue / "running" / "0001" / "started.json").exists())
    pid = scene.read("running", "0001", "started.json")["pid"]
    code, out, err = scene.run("cancel", "--running", "1")
    assert (code, err) == (0, "")
    assert out == ("Sent SIGTERM to job 0001 (process group %d): %s A 0; its runner records how "
                   "it ended\n" % (pid, STUB))
    _, runner_err = runner.communicate(timeout=30)
    assert runner.returncode == 1 and "job 0001 failed (signal 15)" in runner_err
    assert scene.read("done", "0001", "ended.json")["signal"] == 15
    assert scene.ids("waiting") == ["0002"]
    assert "end A" not in scene.log()


def test_cancel_running_dry_run_sends_nothing(scene):
    scene.hold("A")
    scene.add("A")
    runner = scene.start_runner()
    scene.wait_until(lambda: (scene.queue / "running" / "0001" / "started.json").exists())
    pid = scene.read("running", "0001", "started.json")["pid"]
    assert scene.run("cancel", "--running", "--dry-run", "1") == (
        0, "Would send SIGTERM to job 0001 (process group %d): %s A 0\n" % (pid, STUB), "")
    scene.go("A")
    runner.communicate(timeout=30)
    assert runner.returncode == 0
    assert scene.read("done", "0001", "ended.json")["exit"] == 0


def test_cancel_running_refuses_a_job_whose_process_is_gone(scene):
    scene.left_running("0001", dead_pid())
    assert scene.run("cancel", "--running", "1") == (
        3, "", ("job: job 0001 is no longer running, but its runner stopped before recording its "
                "end; the next job run marks it interrupted\n"))


def test_list_shows_a_job_running_under_its_runner(scene):
    scene.left_running("0001", os.getpid())
    with scene.runner_lock_held():
        out = scene.run("list")[1]
    assert out.startswith("Queue default (%s): runner running\n" % scene.queue)
    assert "  0001  since %s, process %d, running  sleep 1\n" % (NOW, os.getpid()) in out


def test_cancel_running_says_so_when_the_signal_cannot_be_sent(scene, monkeypatch):
    scene.left_running("0001", os.getpid())

    def refused(pid):
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(job, "stop_job", refused)
    assert scene.run("cancel", "--running", "1") == (
        1, "", "job: could not stop job 0001 (process group %d): Operation not permitted\n"
        % os.getpid())
