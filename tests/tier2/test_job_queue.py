"""job add, list and cancel: the queue's books, before anything runs (Request 29 from bernstein;
PLAN.md "Settled" 64-69). In-process, in a scratch working folder, the clock fixed."""
import contextlib
import io
import json
import os
import pathlib
import shlex

import pytest

from lobstertools import job

NOW = "2026-11-21T16:30:00+00:00"
JOB = str(pathlib.Path(__file__).resolve().parents[2] / "job")
HOSTILE = ["printf", "%s\n", "$(rm -rf /)", "`x`", "\\", '"q"', "'q'", "</script>", "café 日本",
           "a\nb", "--", "-x"]


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LOBSTER_JOB_NOW", NOW)

    def _run(*argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = job.main(list(argv))
            except SystemExit as exit_:
                code = exit_.code
        return code, out.getvalue(), err.getvalue()

    return _run


def queue(tmp_path, name="default"):
    return tmp_path / "jobs" / name


def ids(folder):
    return sorted(os.listdir(folder)) if folder.exists() else []


def snapshot(top):
    return {str(p.relative_to(top)): p.read_bytes() for p in sorted(top.rglob("*")) if p.is_file()}


def test_add_puts_the_command_at_the_end_and_says_how_to_start_a_runner(run, tmp_path):
    code, out, err = run("add", "--", "sleep", "5")
    assert (code, err) == (0, "")
    assert out == ("Added job 0001 to queue default: sleep 5\n"
                   "No runner for queue default: start one in the background with:\n"
                   "  %s run\n" % shlex.quote(JOB))
    saved = json.loads((queue(tmp_path) / "waiting" / "0001" / "job.json").read_text("utf-8"))
    assert saved == {"id": "0001", "argv": ["sleep", "5"], "cwd": str(tmp_path), "added": NOW,
                     "go_on": False}


def test_jobs_are_numbered_in_order_and_a_number_is_never_used_again(run, tmp_path):
    run("add", "--", "true")
    run("add", "--", "false")
    run("cancel", "0002")
    code, out, _ = run("add", "--", "echo", "three")
    assert code == 0 and out.startswith("Added job 0003 to queue default: echo three\n")
    assert ids(queue(tmp_path) / "waiting") == ["0001", "0003"]
    assert ids(queue(tmp_path) / "cancelled") == ["0002"]


def test_go_on_is_kept_with_the_job(run, tmp_path):
    run("add", "--go-on", "--", "false")
    saved = json.loads((queue(tmp_path) / "waiting" / "0001" / "job.json").read_text("utf-8"))
    assert saved["go_on"] is True


def test_the_arguments_are_kept_exactly_as_given(run, tmp_path):
    code, _, err = run("add", "--", *HOSTILE)
    assert (code, err) == (0, "")
    saved = json.loads((queue(tmp_path) / "waiting" / "0001" / "job.json").read_text("utf-8"))
    assert saved["argv"] == HOSTILE


def test_add_refuses_a_missing_double_dash_or_an_empty_command(run, tmp_path):
    code, out, err = run("add", "sleep", "5")
    assert (code, out) == (2, "")
    assert err == "job: put the command after --: job add [--queue NAME] -- COMMAND [ARG ...]\n"
    code, out, err = run("add", "--")
    assert (code, out, err) == (2, "", "job: no command after --\n")
    assert not (tmp_path / "jobs").exists()


@pytest.mark.parametrize("name", ["../up", ".hidden", "a/b", "", "-x", "sp ace", "café"])
def test_add_refuses_a_queue_name_that_could_leave_its_folder(run, tmp_path, name):
    code, out, err = run("add", "--queue=" + name, "--", "true")
    assert (code, out) == (2, "")
    assert err == ("job: a queue name is letters, figures, - and _, starting with a letter or "
                   "figure, not %r\n" % name)
    assert not (tmp_path / "jobs").exists()


def test_add_dry_run_writes_nothing(run, tmp_path):
    code, out, _ = run("add", "--dry-run", "--", "sleep", "5")
    assert code == 0
    assert out.startswith("Would add job 0001 to queue default: sleep 5\n")
    assert not (tmp_path / "jobs").exists()


def test_dir_and_queue_choose_where_the_queue_is(run, tmp_path):
    elsewhere = tmp_path / "else where"
    code, out, _ = run("add", "--dir", str(elsewhere), "--queue", "night", "--", "true")
    assert code == 0
    assert ids(elsewhere / "night" / "waiting") == ["0001"]
    assert out.endswith("  %s run --queue night --dir %s\n" % (shlex.quote(JOB),
                                                               shlex.quote(str(elsewhere))))


def test_list_of_a_queue_never_used(run, tmp_path):
    code, out, err = run("list")
    assert (code, err) == (0, "")
    assert out == "Queue default (%s): empty; no runner\n" % queue(tmp_path)


def test_list_shows_waiting_in_order_and_cancelled(run, tmp_path):
    run("add", "--", "sleep", "1")
    run("add", "--go-on", "--", "echo", "two words")
    run("add", "--", "true")
    run("cancel", "3")
    code, out, _ = run("list")
    assert code == 0
    assert out == ("Queue default (%s): no runner\n"
                   "Waiting:\n"
                   "  0001  added %s  sleep 1\n"
                   "  0002  added %s  echo 'two words'  (--go-on)\n"
                   "Cancelled:\n"
                   "  0003  cancelled %s  true\n" % (queue(tmp_path), NOW, NOW, NOW))


def test_list_writes_nothing(run, tmp_path):
    run("add", "--", "true")
    before = snapshot(tmp_path)
    run("list")
    run("list", "--queue", "other")
    assert snapshot(tmp_path) == before


def test_cancel_moves_a_waiting_job_to_cancelled_unchanged(run, tmp_path):
    run("add", "--", "sleep", "1")
    run("add", "--", "sleep", "2")
    kept = (queue(tmp_path) / "waiting" / "0002" / "job.json").read_bytes()
    code, out, err = run("cancel", "0002")
    assert (code, out, err) == (0, "Cancelled job 0002: sleep 2\n", "")
    assert ids(queue(tmp_path) / "waiting") == ["0001"]
    moved = queue(tmp_path) / "cancelled" / "0002"
    assert (moved / "job.json").read_bytes() == kept
    assert json.loads((moved / "cancelled.json").read_text("utf-8")) == {"cancelled": NOW}


def test_cancel_takes_the_number_without_its_noughts(run, tmp_path):
    run("add", "--", "true")
    assert run("cancel", "1")[:2] == (0, "Cancelled job 0001: true\n")


def test_cancel_refuses_a_job_that_is_not_there(run, tmp_path):
    run("add", "--", "true")
    assert run("cancel", "9") == (4, "", "job: no job 0009 in queue default\n")


def test_cancel_refuses_a_job_already_cancelled(run, tmp_path):
    run("add", "--", "true")
    run("cancel", "1")
    assert run("cancel", "1") == (3, "", "job: job 0001 is already cancelled\n")


def test_cancel_refuses_an_id_that_is_not_a_number(run, tmp_path):
    code, out, err = run("cancel", "../0001")
    assert (code, out) == (2, "")
    assert err == "job: a job id is a number, such as 3 or 0003, not '../0001'\n"


def test_cancel_dry_run_changes_nothing(run, tmp_path):
    run("add", "--", "true")
    before = snapshot(tmp_path)
    assert run("cancel", "--dry-run", "1")[:2] == (0, "Would cancel job 0001: true\n")
    assert snapshot(tmp_path) == before


def test_help_names_every_verb(run):
    code, out, _ = run("--help")
    assert code == 0
    for verb in ("add", "run", "list", "wait", "cancel"):
        assert verb in out


def test_no_verb_is_a_usage_error(run):
    code, _, err = run()
    assert code == 2 and "add" in err
