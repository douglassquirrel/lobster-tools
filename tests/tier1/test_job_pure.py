"""job's small pure parts (Request 29 from bernstein; PLAN.md "Settled" 64-69)."""
import os
import re

from lobstertools import job

T0 = "2026-11-21T10:00:00+00:00"


def test_duration_in_seconds_minutes_and_hours():
    assert job.duration(T0, "2026-11-21T10:00:42+00:00") == "42s"
    assert job.duration(T0, "2026-11-21T10:03:05+00:00") == "3m05s"
    assert job.duration(T0, "2026-11-21T12:07:59+00:00") == "2h07m"


def test_duration_is_a_question_mark_when_a_time_is_missing_or_wrong():
    assert job.duration(None, T0) == "?"
    assert job.duration(T0, "yesterday") == "?"


def test_how_a_job_ended():
    assert job.how_it_ended({"exit": 0, "signal": None, "interrupted": False}) == "exit 0"
    assert job.how_it_ended({"exit": None, "signal": 15, "interrupted": False}) == \
        "ended by signal 15"
    assert job.how_it_ended({"exit": None, "signal": None, "interrupted": True}) == "interrupted"


def test_alive_for_this_process_and_for_no_process():
    assert job.alive(os.getpid()) is True
    assert [job.alive(pid) for pid in (None, 0, -1, "12")] == [False] * 4


def test_alive_for_a_process_it_may_not_signal():
    assert job.alive(1) is True   # launchd or init, owned by root: PermissionError, but there


def test_job_ids_are_four_figures():
    assert [job.job_id(t) for t in ("1", "0003", "12345")] == ["0001", "0003", "12345"]


def test_stamp_is_utc_to_the_second(monkeypatch):
    monkeypatch.delenv("LOBSTER_JOB_NOW", raising=False)
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00", job.stamp())


def test_a_job_file_that_cannot_be_read_is_none(tmp_path):
    queue = job.Queue(str(tmp_path), "q")
    (tmp_path / "q" / "waiting" / "0001").mkdir(parents=True)
    (tmp_path / "q" / "waiting" / "0001" / "job.json").write_text("{not json", "utf-8")
    assert queue.read("waiting", "0001") is None
    assert job.describe(queue, "waiting", "0001") == "0001  added ?  ?"
