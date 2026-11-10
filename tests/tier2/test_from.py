"""--from NAME on wait and checkin: only mail from the named senders counts; mail from others is
left in new/ untouched and only counted (PLAN.md "Watching for one sender")."""
import json

import pytest
from conftest import every_file, files_in

from lobstertools import mail

BAD = "--from '../x' is not a plain folder name"


@pytest.mark.parametrize("verb", ["wait", "checkin"])
def test_from_refuses_a_name_that_is_not_a_plain_mailbox_name(run, root, two, verb):
    code, out, err = run(verb, "--root", str(root), "--as", "b", "--session", "desk-1",
                         "--from", "../x")
    assert code == 2 and out == ""
    assert BAD in err
    assert not (root / "b" / "duty").exists()               # refused before taking the duty


@pytest.fixture
def others_waiting(run, root, two):
    """b's new/ holds one message from a and one hand-dropped file without headers: no bernstein mail."""
    code, _, err = run("send", "--root", str(root), "--as", "a", "--to", "b", "--subject", "From a",
                       "-", stdin="a's request\n")
    assert code == 0, err
    (root / "b" / "new" / "dropped-by-hand.md").write_bytes(b"no headers here\n")
    code, _, err = run("init", "bernstein", "--root", str(root))
    assert code == 0, err


def test_checkin_from_with_only_others_mail_is_exit_5_and_moves_nothing(run, root, others_waiting):
    before = files_in(root / "b" / "new")
    code, out, err = run("checkin", "--root", str(root), "--as", "b", "--session", "desk-1",
                         "--from", "bernstein")
    assert code == 5
    assert out == "Duty for b taken by desk-1 at 2026-10-10T09:00:00Z\n"
    assert err == ("lobster-mail checkin: No new mail from bernstein for b (2 other messages are "
                   "waiting, not from bernstein; left unclaimed); check in again later\n")
    assert files_in(root / "b" / "new") == before and files_in(root / "b" / "open") == []


ARRIVED_CHECKIN = ("Mail has arrived for b: claim it with ack, report it, act on it only as your "
                   "project's rules allow (by default, only with the OK of the person you work for), "
                   "then check in again.")
BERNSTEIN = "2026-10-10-0900-bernstein-request-6"


def test_checkin_from_lists_only_the_senders_mail_and_counts_the_rest(run, root, others_waiting):
    code, _, err = run("send", "--root", str(root), "--as", "bernstein", "--to", "b", "--subject",
                       "Request 6", "-", stdin="do this\n")
    assert code == 0, err
    before = files_in(root / "b" / "new")
    code, out, err = run("checkin", "--root", str(root), "--as", "b", "--session", "desk-1",
                         "--from", "bernstein")
    assert code == 0, err
    assert out == ("Duty for b taken by desk-1 at 2026-10-10T09:00:00Z\n"
                   + BERNSTEIN + "  bernstein  2026-10-10T09:00:00Z  Request 6\n"
                   "2 other messages are waiting, not from bernstein; left unclaimed\n"
                   + ARRIVED_CHECKIN + "\n")
    assert files_in(root / "b" / "new") == before and files_in(root / "b" / "open") == []


@pytest.fixture
def bernstein_too(run, root, others_waiting):
    code, _, err = run("send", "--root", str(root), "--as", "bernstein", "--to", "b", "--subject",
                       "Request 6", "-", stdin="do this\n")
    assert code == 0, err


def test_from_with_two_names_counts_both_and_json_gives_the_names_and_the_others(run, root, bernstein_too):
    code, out, err = run("checkin", "--root", str(root), "--as", "b", "--session", "desk-1",
                         "--from", "bernstein", "--from", "a", "--json")
    assert code == 0, err
    result = json.loads(out)
    assert [m["from"] for m in result["mail"]] == ["a", "bernstein"]
    assert result["from"] == ["bernstein", "a"] and result["other_waiting"] == 1
    assert result["own_handover_only"] is False
    code, out, _ = run("checkin", "--root", str(root), "--as", "b", "--session", "desk-1",
                       "--from", "bernstein", "--from", "a")
    assert "\n1 other message is waiting, not from bernstein or a; left unclaimed\n" in out


def test_from_names_a_sender_once_however_often_it_is_given(run, root, others_waiting):
    code, _, err = run("checkin", "--root", str(root), "--as", "b", "--session", "desk-1",
                       "--from", "bernstein", "--from", "bernstein")
    assert code == 5
    assert "No new mail from bernstein for b (2 other messages are waiting, not from bernstein; " in err


@pytest.fixture
def fake_clock(monkeypatch):
    """wait's clock and sleep, injected: each sleep moves the clock on and runs what is queued."""
    clock = {"t": 0.0, "on_sleep": []}

    def sleep(seconds):
        clock["t"] += seconds
        while clock["on_sleep"]:
            clock["on_sleep"].pop(0)()
    monkeypatch.setattr(mail.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(mail.time, "sleep", sleep)
    return clock


def test_wait_from_keeps_watching_past_others_mail_and_times_out_with_exit_5(run, root, others_waiting, fake_clock):
    before = every_file(root)
    code, out, err = run("wait", "--root", str(root), "--as", "b", "--session", "desk-1",
                         "--from", "bernstein", "--timeout", "5", "--every", "2")
    assert code == 5
    assert fake_clock["t"] == 6                             # it watched, rather than returning at once
    assert out == "Duty for b taken by desk-1 at 2026-10-10T09:00:00Z\n"
    assert err == ("lobster-mail wait: No new mail from bernstein for b after 5 seconds (2 other "
                   "messages are waiting, not from bernstein; left unclaimed); run wait again to "
                   "keep watching\n")
    assert every_file(root) == before


ARRIVED_WAIT = ("Mail has arrived for b: claim it with ack, report it, act on it only as your "
                "project's rules allow (by default, only with the OK of the person you work for), "
                "then wait again.")


def test_wait_from_returns_when_the_senders_mail_arrives_and_lists_only_it(run, root, others_waiting, fake_clock):
    def bernstein_sends():
        code, _, err = run("send", "--root", str(root), "--as", "bernstein", "--to", "b",
                           "--subject", "Request 6", "-", stdin="do this\n")
        assert code == 0, err
    fake_clock["on_sleep"].append(bernstein_sends)
    code, out, err = run("wait", "--root", str(root), "--as", "b", "--session", "desk-1",
                         "--from", "bernstein", "--timeout", "30", "--every", "2")
    assert code == 0, err
    assert fake_clock["t"] == 2
    assert out.endswith(BERNSTEIN + "  bernstein  2026-10-10T09:00:00Z  Request 6\n"
                        "2 other messages are waiting, not from bernstein; left unclaimed\n"
                        + ARRIVED_WAIT + "\n")
    assert files_in(root / "b" / "open") == [] and len(files_in(root / "b" / "new")) == 3


@pytest.mark.parametrize("verb", ["wait", "checkin"])
def test_without_from_the_json_keeps_exactly_its_old_keys(run, root, bernstein_too, verb):
    code, out, err = run(verb, "--root", str(root), "--as", "b", "--session", "desk-1", "--json")
    assert code == 0, err
    result = json.loads(out)
    assert sorted(result) == ["duty", "mail", "mailbox", "own_handover_only", "reported",
                              "session"]
    assert len(result["mail"]) == 3                         # everyone's mail counts, as before


def test_wait_from_still_returns_exit_6_when_the_pace_changes_while_others_mail_waits(run, root, others_waiting, fake_clock):
    def set_eager():
        code, _, err = run("pace", "--root", str(root), "--as", "b", "eager")
        assert code == 0, err
    fake_clock["on_sleep"].append(set_eager)
    code, _, err = run("wait", "--root", str(root), "--as", "b", "--session", "desk-1",
                       "--from", "bernstein", "--timeout", "30", "--every", "2")
    assert code == 6
    assert "the pace for b changed from normal to eager while watching" in err


OWN_CHECKIN = ("Only this mailbox's own handover is waiting; it is for the next session: do not "
               "claim it, and do not check in again.")


def test_from_counts_the_mailboxs_own_handover_only_when_the_mailbox_is_named(run, root, two):
    run("send", "--root", str(root), "--as", "b", "--to", "b", "--subject", "Handover", "-", stdin="x\n")
    code, _, err = run("checkin", "--root", str(root), "--as", "b", "--session", "desk-1",
                       "--from", "bernstein")
    assert code == 5
    assert "(1 other message is waiting, not from bernstein; left unclaimed)" in err
    code, out, err = run("checkin", "--root", str(root), "--as", "b", "--session", "desk-1",
                         "--from", "bernstein", "--from", "b")
    assert code == 0, err
    assert out.rstrip().endswith(OWN_CHECKIN)


@pytest.mark.parametrize("verb", ["wait", "checkin"])
def test_from_is_in_the_verbs_help(run, verb):
    code, out, _ = run(verb, "--help")
    assert code == 0
    assert "--from NAME" in out and "mail from others is left in new/" in " ".join(out.split())
