"""job run: the queue's jobs run one at a time, in order (Request 29 from bernstein; PLAN.md
"Settled" 64-69). The jobs are the stand-in tests/stubs/jobstub."""
import os
import shlex

from job_helpers import COMMAND, NOW, STUB, dead_pid

HOSTILE = ["$(rm -rf /)", "`x`", "\\", '"q"', "'q'", "</script>", "café 日本", "a\nb", "-x", ""]


def started(ident, *argv):
    return "Job %s started: %s" % (ident, " ".join(shlex.quote(a) for a in argv))


def test_runs_the_waiting_jobs_one_at_a_time_in_order(scene):
    for name in ("A", "B", "C"):
        scene.add(name)
    code, out, err = scene.run("run")
    assert (code, err) == (0, "")
    here = os.path.realpath(str(scene.tmp))
    assert scene.log() == ["start A %s" % here, "end A", "start B %s" % here, "end B",
                           "start C %s" % here, "end C"]
    assert out.splitlines() == [
        started("0001", STUB, "A", "0"), "Job 0001 ended: exit 0 after 0s",
        started("0002", STUB, "B", "0"), "Job 0002 ended: exit 0 after 0s",
        started("0003", STUB, "C", "0"), "Job 0003 ended: exit 0 after 0s",
        "Queue default is empty: ran 3 jobs"]
    assert scene.ids("done") == ["0001", "0002", "0003"]
    assert scene.ids("waiting") == [] and scene.ids("running") == []


def test_keeps_each_jobs_output_exit_code_and_times(scene):
    scene.add("A")
    scene.run("run")
    assert scene.output("done", "0001") == b"err A\n"
    began = scene.read("done", "0001", "started.json")
    assert began["started"] == NOW and isinstance(began["pid"], int)
    assert scene.read("done", "0001", "ended.json") == {"ended": NOW, "exit": 0, "signal": None,
                                                        "interrupted": False}


def test_passes_the_arguments_exactly_as_given_never_through_a_shell(scene):
    scene.add("A", 0, *HOSTILE)
    assert scene.run("run")[0] == 0
    expected = b"".join(a.encode("utf-8") + b"\0" for a in HOSTILE) + b"err A\n"
    assert scene.output("done", "0001") == expected


def test_a_job_runs_in_the_folder_it_was_added_from(scene, monkeypatch):
    sub = scene.tmp / "sub folder"
    sub.mkdir()
    monkeypatch.chdir(sub)
    scene.run("add", "--dir", str(scene.tmp / "jobs"), "--", STUB, "A", "0")
    monkeypatch.chdir(scene.tmp)
    assert scene.run("run")[0] == 0
    assert scene.log()[0] == "start A %s" % os.path.realpath(str(sub))


def test_a_failure_stops_the_queue_and_says_how_to_go_on(scene):
    scene.add("A")
    scene.add("B", 3)
    scene.add("C")
    code, out, err = scene.run("run")
    assert code == 1
    assert out.splitlines()[-1] == "Job 0002 ended: exit 3 after 0s"
    assert err == ("job: job 0002 failed (exit 3), so the queue stopped with 1 waiting; to go on, "
                   "run it again:\n  %s run\nor cancel what should not run\n"
                   % shlex.quote(COMMAND))
    assert scene.ids("waiting") == ["0003"]
    assert scene.read("done", "0002", "ended.json")["exit"] == 3
    assert "start C" not in " ".join(scene.log())


def test_go_on_lets_the_queue_pass_that_jobs_failure(scene):
    scene.add("A")
    scene.add("B", 3, go_on=True)
    scene.add("C")
    code, out, err = scene.run("run")
    assert (code, err) == (0, "")
    assert out.splitlines()[-1] == "Queue default is empty: ran 3 jobs, 1 failed (--go-on)"
    assert scene.ids("done") == ["0001", "0002", "0003"]


def test_a_command_that_cannot_start_is_a_failure_with_exit_127(scene):
    scene.run("add", "--", str(scene.tmp / "no such program"))
    scene.add("B")
    code, _, err = scene.run("run")
    assert code == 1 and "job 0001 failed (exit 127)" in err
    text = scene.output("done", "0001").decode("utf-8")
    assert text.startswith("job: cannot start %s in %s: " % (shlex.quote(str(scene.tmp / "no such "
                                                                             "program")), scene.tmp))
    assert scene.read("done", "0001", "ended.json")["exit"] == 127
    assert scene.ids("waiting") == ["0002"]


def test_an_empty_queue_has_nothing_to_run(scene):
    assert scene.run("run") == (0, "Queue default is empty: nothing to run\n", "")


def test_a_second_runner_for_the_same_queue_is_refused(scene):
    scene.add("A")
    with scene.runner_lock_held():
        code, out, err = scene.run("run")
    assert (code, out) == (3, "")
    assert err == "job: another job run is running queue default; only one may run a queue\n"
    assert scene.ids("waiting") == ["0001"] and scene.log() == []


def test_a_job_left_running_by_a_runner_that_stopped_is_marked_interrupted(scene):
    scene.left_running("0001", dead_pid())
    scene.add("B")
    code, out, err = scene.run("run")
    assert (code, out) == (1, "")
    assert err == ("job: job 0001 was interrupted: its runner stopped before it ended, and it is "
                   "no longer running, so the queue stopped with 1 waiting; to go on, run it "
                   "again:\n  %s run\nor cancel what should not run\n"
                   % shlex.quote(COMMAND))
    assert scene.ids("done") == ["0001"] and scene.ids("waiting") == ["0002"]
    assert scene.read("done", "0001", "ended.json") == {"ended": NOW, "exit": None,
                                                        "signal": None, "interrupted": True}
    assert scene.log() == []


def test_a_job_still_running_without_its_runner_blocks_a_new_runner(scene):
    scene.left_running("0001", os.getpid())
    scene.add("B")
    code, out, err = scene.run("run")
    assert (code, out) == (3, "")
    assert err == ("job: job 0001 is still running as process %d, with no runner to record its "
                   "end; wait for it to end, or stop it with: job cancel --running 0001\n"
                   % os.getpid())
    assert scene.ids("running") == ["0001"] and scene.ids("waiting") == ["0002"]


def test_list_shows_done_and_running_jobs(scene):
    scene.add("A")
    scene.add("B", 3)
    scene.run("run")
    scene.left_running("0004", os.getpid(), ["sleep", "9"])
    code, out, _ = scene.run("list")
    assert code == 0
    assert out == ("Queue default (%s): no runner\n"
                   "Done:\n"
                   "  0001  exit 0 after 0s, ended %s  %s A 0\n"
                   "  0002  exit 3 after 0s, ended %s  %s B 3\n"
                   "Running:\n"
                   "  0004  since %s, process %d, no runner: still running  sleep 9\n"
                   % (scene.queue, NOW, STUB, NOW, STUB, NOW, os.getpid()))


def test_list_shows_an_interrupted_job(scene):
    scene.left_running("0001", dead_pid())
    out = scene.run("list")[1]
    assert "  0001  since %s, process" % NOW in out
    assert "no runner: interrupted  sleep 1\n" in out


def test_cancel_refuses_a_job_that_has_ended_or_is_running(scene):
    scene.add("A")
    scene.run("run")
    assert scene.run("cancel", "1") == (3, "", "job: job 0001 has already ended\n")
    scene.left_running("0002", os.getpid())
    assert scene.run("cancel", "2") == (
        3, "", "job: job 0002 is running; add --running to stop it (SIGTERM)\n")


def test_add_while_a_runner_runs_says_it_will_run_in_turn(scene):
    with scene.runner_lock_held():
        code, out, _ = scene.run("add", "--", STUB, "A", "0")
    assert code == 0
    assert out == ("Added job 0001 to queue default: %s A 0\n"
                   "The runner for queue default will start it in turn.\n" % STUB)


def test_runs_as_a_program_and_takes_a_job_added_while_one_runs(scene):
    scene.hold("A")
    scene.add("A")
    scene.add("B")
    runner = scene.start_runner()
    scene.wait_until(lambda: scene.ids("running") == ["0001"])
    scene.add("C")
    scene.go("A")
    out, err = runner.communicate(timeout=30)
    assert (runner.returncode, err) == (0, "")
    assert [line.split()[0] + " " + line.split()[1] for line in scene.log()] == [
        "start A", "end A", "start B", "end B", "start C", "end C"]
    assert out.splitlines()[-1] == "Queue default is empty: ran 3 jobs"
