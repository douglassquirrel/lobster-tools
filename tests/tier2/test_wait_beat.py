"""wait keeps the duty's heartbeat fresh while it waits (Request 9; PLAN.md "wait keeps the duty's
heartbeat fresh while it waits"). The wall clock (LOBSTER_MAIL_NOW) and the monotonic clock are
both faked: sleep advances them together, and a hook may act at a given minute."""
from datetime import datetime, timedelta

import pytest
from conftest import every_file

from lobstertools import mail

START = datetime.fromisoformat("2026-10-10T10:00:00+01:00")   # conftest's NOW: 09:00:00Z


@pytest.fixture
def fake_time(monkeypatch):
    """Sleep moves both clocks; at[minute] runs once when the clock first reaches that minute;
    beats records the heartbeat file's text and the duty's age in minutes at every sleep."""
    state = {"t": 0.0, "at": {}, "beats": [], "ages": [], "box": None}

    def set_wall(seconds):
        monkeypatch.setenv("LOBSTER_MAIL_NOW", (START + timedelta(seconds=seconds)).isoformat())

    def sleep(seconds):
        state["t"] += seconds
        set_wall(state["t"])
        for minute in sorted(state["at"]):
            if state["t"] >= minute * 60:
                state["at"].pop(minute)()
        box = state["box"]
        if box is not None and (box / "duty" / "heartbeat").exists():
            text = (box / "duty" / "heartbeat").read_text()
            if not state["beats"] or state["beats"][-1] != text:
                state["beats"].append(text)
            beat = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
            state["ages"].append((START + timedelta(seconds=state["t"]) - beat).total_seconds() / 60)

    monkeypatch.setattr(mail.time, "monotonic", lambda: state["t"])
    monkeypatch.setattr(mail.time, "sleep", sleep)
    state["set_wall"] = set_wall
    return state


def wait_b(run, root, *extra):
    return run("wait", "--root", str(root), "--as", "b", "--session", "mac", "--every", "60", *extra)


def test_a_30_minute_wait_beats_the_heartbeat_at_10_and_20_minutes_and_is_never_stale(run, root, two, fake_time):
    fake_time["box"] = root / "b"
    code, out, err = wait_b(run, root, "--timeout", "1800")
    assert code == 5, err
    assert fake_time["beats"] == ["2026-10-10T09:00:00Z\n", "2026-10-10T09:10:00Z\n", "2026-10-10T09:20:00Z\n"]
    assert max(fake_time["ages"]) <= 10
    assert (root / "b" / "duty" / "heartbeat").read_text() == "2026-10-10T09:30:00Z\n"   # the last look
    assert out == "Duty for b taken by mac at 2026-10-10T09:00:00Z\n"   # the beats print nothing


def test_beat_sets_the_interval_in_minutes(run, root, two, fake_time):
    fake_time["box"] = root / "b"
    code, _, err = wait_b(run, root, "--timeout", "1200", "--beat", "7")
    assert code == 5, err
    assert fake_time["beats"] == ["2026-10-10T09:00:00Z\n", "2026-10-10T09:07:00Z\n", "2026-10-10T09:14:00Z\n"]


def test_a_takeover_between_beats_ends_the_wait_with_exit_3_and_leaves_the_new_holders_files(run, root, two, fake_time):
    box = root / "b"
    seen = {}

    def take_over():
        code, _, err = run("duty", "take", "--root", str(root), "--as", "b", "--session", "desk",
                           "--stale", "5")
        assert code == 0, err
        seen.update({name: (box / "duty" / name).read_bytes() for name in ("holder", "heartbeat")})

    fake_time["at"][15] = take_over
    code, out, err = wait_b(run, root, "--timeout", "1800")
    assert code == 3 and out == "Duty for b taken by mac at 2026-10-10T09:00:00Z\n"
    assert err == ("lobster-mail wait: the duty of b was taken by desk while watching (last beat "
                   "2026-10-10T09:15:00Z); not watching\n")
    assert {name: (box / "duty" / name).read_bytes() for name in ("holder", "heartbeat")} == seen
    assert seen["holder"].startswith(b"desk\n")


def test_a_duty_given_up_meanwhile_ends_the_wait_with_exit_3(run, root, two, fake_time):
    fake_time["at"][12] = lambda: run("duty", "release", "--root", str(root), "--as", "b",
                                      "--session", "mac")
    code, _, err = wait_b(run, root, "--timeout", "1800")
    assert code == 3
    assert err == "lobster-mail wait: the duty of b was given up while watching; not watching\n"
    assert not (root / "b" / "duty").exists()


def test_after_the_mac_sleeps_the_first_look_beats_at_once(run, root, two, fake_time):
    box = root / "b"
    # Three hours pass on the wall clock while the monotonic clock (which stops in sleep) moves 60s.
    fake_time["at"][1] = lambda: fake_time["set_wall"](3 * 3600)
    fake_time["box"] = box
    code, _, err = wait_b(run, root, "--timeout", "120")
    assert code == 5, err
    assert (box / "duty" / "heartbeat").read_text() == "2026-10-10T12:00:00Z\n"


def test_a_beat_keeps_the_status_the_session_reports(run, root, two, fake_time):
    code, _, err = run("duty", "take", "--root", str(root), "--as", "b", "--session", "mac")
    assert code == 0, err
    code, _, err = run("status", "--root", str(root), "--as", "b", "--session", "mac", "watching")
    assert code == 0, err
    status = (root / "b" / "duty" / "status").read_bytes()
    fake_time["box"] = root / "b"
    code, _, err = wait_b(run, root, "--timeout", "1500")
    assert code == 5, err
    assert len(fake_time["beats"]) == 3
    assert (root / "b" / "duty" / "status").read_bytes() == status


def test_beats_write_nothing_but_the_heartbeat(run, root, mail_for_b, fake_time):
    box = root / "b"
    code, _, err = run("ack", "--root", str(root), "--as", "b", "note-from-squirrel")
    assert code == 0, err
    for entry in list((box / "new").iterdir()):
        run("ack", "--root", str(root), "--as", "b", entry.stem)
    before_messages = every_file(root)
    run("duty", "take", "--root", str(root), "--as", "b", "--session", "mac")
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    code, _, err = wait_b(run, root, "--timeout", "1800")
    assert code == 5, err
    after = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    heartbeat = box.relative_to(root) / "duty" / "heartbeat"
    assert set(after) == set(before)
    assert {k: v for k, v in after.items() if k != heartbeat} == \
           {k: v for k, v in before.items() if k != heartbeat}
    assert after[heartbeat] == b"2026-10-10T09:30:00Z\n"   # the last look, at 30 minutes, beats too
    assert every_file(root) == before_messages


def test_mail_arriving_after_some_beats_ends_the_wait_as_before(run, root, two, fake_time):
    fake_time["at"][25] = lambda: run("send", "--root", str(root), "--as", "a", "--to", "b",
                                      "--subject", "Late", "-", stdin="Hello\n")
    fake_time["box"] = root / "b"
    code, out, err = wait_b(run, root, "--timeout", "3600")
    assert code == 0, err
    assert "a-late" in out and "Mail has arrived for b" in out
    assert fake_time["beats"][-1] == "2026-10-10T09:20:00Z\n"


@pytest.mark.parametrize("beat, stale", [("2.5", None), ("0", None), ("-3", None), ("abc", None),
                                         ("45", None), ("50", None), ("20", "15")])
def test_beat_must_be_a_whole_number_of_minutes_under_the_staleness(run, root, two, beat, stale):
    extra = ["--stale", stale] if stale else []
    code, out, err = wait_b(run, root, "--timeout", "1", "--beat", beat, *extra)
    assert code == 2 and out == ""
    assert err == ("lobster-mail wait: --beat must be a whole number of minutes, at least 1 and less "
                   "than --stale (%s): not %s\n" % (stale or "45", beat))
    assert not (root / "b" / "duty").exists()


def test_wait_gives_up_after_an_hour_by_default(run, root, two, fake_time):
    code, _, err = wait_b(run, root)
    assert code == 5
    assert "No new mail for b after 3600 seconds; run wait again to keep watching" in err
    assert fake_time["t"] == 3600


def test_wait_help_gives_the_beat_and_the_hours_default(run):
    code, out, _ = run("wait", "--help")
    assert code == 0
    assert "--beat MINUTES" in out
    assert "default 10" in out
    assert "default 3600" in out
