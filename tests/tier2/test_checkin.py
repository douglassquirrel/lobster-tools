"""checkin: one look with the duty, exiting at once, for a session that cannot keep wait running
(each call foreground and cut off, as in the device shell; PLAN.md "Checking in without a
background wait")."""
import json

import pytest
from conftest import every_file

from lobstertools import mail

FIRST = "2026-10-10-0805-a-first-request"
ARRIVED = ("Mail has arrived for b: claim it with ack, report it, act on it only as your project's "
           "rules allow (by default, only with the OK of the person you work for), then check in "
           "again.")
OWN = ("Only this mailbox's own handover is waiting; it is for the next session: do not claim it, "
       "and do not check in again.")


@pytest.fixture
def no_sleeping(monkeypatch):
    """checkin exits at once: any sleep is a failure."""
    def refuse(_seconds):
        raise AssertionError("checkin must never sleep")
    monkeypatch.setattr(mail.time, "sleep", refuse)


def test_checkin_takes_the_duty_lists_the_mail_and_exits_0(run, root, mail_for_b, no_sleeping):
    code, out, err = run("checkin", "--root", str(root), "--as", "b", "--session", "desk-1")
    assert code == 0, err
    assert out.startswith("Duty for b taken by desk-1 at 2026-10-10T09:00:00Z\n")
    assert FIRST + "  a  2026-10-10T08:05:00Z  First request\n" in out
    assert out.rstrip().endswith(ARRIVED)
    assert (root / "b" / "duty" / "holder").read_text().startswith("desk-1\n")


def test_checkin_with_nothing_new_is_exit_5_and_keeps_the_duty(run, root, two, no_sleeping):
    code, out, err = run("checkin", "--root", str(root), "--as", "a", "--session", "desk-1")
    assert code == 5
    assert out.startswith("Duty for a taken by desk-1 at 2026-10-10T09:00:00Z\n")
    assert "No new mail for a; check in again later" in err
    assert (root / "a" / "duty" / "holder").exists()        # the duty is kept between check-ins
    code, out, err = run("checkin", "--root", str(root), "--as", "a", "--session", "desk-1",
                         "--json")
    assert code == 5 and out == ""                          # no JSON document: the code says it all
    assert "No new mail for a; check in again later" in err


def test_checkin_refreshes_the_heartbeat_when_the_same_session_holds_the_duty(run, root, two, monkeypatch):
    run("duty", "take", "--root", str(root), "--as", "a", "--session", "desk-1")
    monkeypatch.setenv("LOBSTER_MAIL_NOW", "2026-10-10T10:20:00+01:00")
    code, out, _ = run("checkin", "--root", str(root), "--as", "a", "--session", "desk-1")
    assert code == 5
    assert "desk-1 is already on duty for a" in out
    assert (root / "a" / "duty" / "heartbeat").read_text() == "2026-10-10T09:20:00Z\n"


def test_checkin_is_refused_while_another_session_holds_the_duty(run, root, mail_for_b):
    run("duty", "take", "--root", str(root), "--as", "b", "--session", "desk-1")
    code, out, err = run("checkin", "--root", str(root), "--as", "b", "--session", "desk-2")
    assert code == 3 and out == ""
    assert "held by desk-1" in err and "not checking in" in err


def test_checkin_tells_the_mailboxs_own_handover_from_a_request(run, root, two, no_sleeping):
    run("send", "--root", str(root), "--as", "b", "--to", "b", "--subject", "Handover", "-", stdin="x\n")
    code, out, err = run("checkin", "--root", str(root), "--as", "b", "--session", "desk-1")
    assert code == 0, err
    assert out.rstrip().endswith(OWN)
    run("send", "--root", str(root), "--as", "a", "--to", "b", "--subject", "Real", "-", stdin="y\n")
    code, out, _ = run("checkin", "--root", str(root), "--as", "b", "--session", "desk-1")
    assert code == 0 and out.rstrip().endswith(ARRIVED)
    code, out, _ = run("checkin", "--root", str(root), "--as", "b", "--session", "desk-1", "--json")
    result = json.loads(out)
    assert result["mailbox"] == "b" and result["session"] == "desk-1" and result["duty"] == "refreshed"
    assert result["own_handover_only"] is False
    # the same minute, so the listing sorts by id: a's message before b's own
    assert [m["subject"] for m in result["mail"]] == ["Real", "Handover"]


def test_checkin_takes_the_session_name_from_the_variable(run, root, mail_for_b, monkeypatch):
    code, _, err = run("checkin", "--root", str(root), "--as", "b")
    assert code == 2 and "--session" in err
    monkeypatch.setenv("LOBSTER_MAIL_SESSION", "desk-9")
    code, out, err = run("checkin", "--root", str(root), "--as", "b")
    assert code == 0, err
    assert "taken by desk-9" in out


def test_checkin_changes_no_message_file(run, root, mail_for_b):
    before = every_file(root)
    code, _, err = run("checkin", "--root", str(root), "--as", "b", "--session", "desk-1")
    assert code == 0, err
    assert every_file(root) == before


def test_start_names_checkin_for_a_session_that_cannot_run_a_background_command(run, root, two):
    code, out, err = run("start", "--root", str(root), "--as", "b")
    assert code == 0, err
    assert "lobster-mail checkin --as b --session NAME" in out
    assert out.index("lobster-mail wait --as b") < out.index("lobster-mail checkin --as b")
