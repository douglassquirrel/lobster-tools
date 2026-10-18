"""A duty caught while it changes: made but not yet written, or gone between the look and the read.
Each is a plain answer, never a traceback or a misleading "could not write"."""
import json
import os

from lobstertools import mail

CHANGING = "the duty of a is being taken or given up right now; run again"


def test_a_duty_folder_without_its_files_yet_is_changing_with_exit_3(run, root, two):
    (root / "a" / "duty").mkdir()
    code, out, err = run("duty", "status", "--as", "a", "--root", str(root))
    assert (code, out) == (3, "")
    assert err == "lobster-mail duty: %s\n" % CHANGING


def test_an_empty_holder_file_is_changing_with_exit_3(run, root, two):
    (root / "a" / "duty").mkdir()
    (root / "a" / "duty" / "holder").write_text("")
    code, out, err = run("duty", "status", "--as", "a", "--root", str(root))
    assert (code, out) == (3, "")
    assert err == "lobster-mail duty: %s\n" % CHANGING


def test_a_duty_released_between_the_look_and_the_read_is_nobody_on_duty(run, root, two,
                                                                        monkeypatch):
    duty = str(root / "a" / "duty")
    real_isdir = os.path.isdir
    monkeypatch.setattr(mail.os.path, "isdir", lambda p: p == duty or real_isdir(p))
    code, out, err = run("duty", "status", "--as", "a", "--root", str(root))
    assert (code, out, err) == (0, "Nobody is on duty for a\n", "")


def test_start_says_the_duty_is_changing_and_still_exits_0(run, root, two):
    (root / "a" / "duty").mkdir()
    code, out, err = run("start", "--as", "a", "--root", str(root))
    assert (code, err) == (0, "")
    assert "-- Duty:\nThe duty of a is being taken or given up right now; run duty status again\n" in out


def test_handover_sends_the_note_and_releases_nothing_while_the_duty_is_changing(run, root, two):
    (root / "a" / "duty").mkdir()
    code, out, err = run("handover", "--as", "a", "--session", "desk-1", "-", "--root", str(root),
                         stdin="Stopped.\n")
    assert (code, err) == (0, "")
    assert out.splitlines()[-1] == ("Nothing released: the duty of a is being taken or given up "
                                    "right now; run duty status again")
    assert len(os.listdir(root / "a" / "new")) == 1
    assert os.listdir(root / "a" / "duty") == []


def test_all_lists_a_changing_duty_as_null_and_changing_and_the_rest_as_usual(run, root, two):
    (root / "a" / "duty").mkdir()
    code, out, err = run("duty", "status", "--all", "--json", "--root", str(root))
    assert (code, err) == (0, "")
    assert [(e["mailbox"], e["duty"], e["duty_changing"]) for e in json.loads(out)["mailboxes"]] == [
        ("a", None, True), ("b", None, False)]
    code, out, err = run("duty", "status", "--all", "--root", str(root))
    assert (code, err) == (0, "")
    assert out == ("a  duty being taken or given up right now  new 0  open 0  handover no  pace normal\n"
                   "b  nobody on duty  new 0  open 0  handover no  pace normal\n")


def test_take_wait_and_checkin_refuse_a_changing_duty_and_leave_it_alone(run, root, two):
    (root / "a" / "duty").mkdir()
    for argv, tail in ((("duty", "take"), ""), (("wait", "--timeout", "1"), "; not watching"),
                       (("checkin",), "; not checking in")):
        code, out, err = run(*argv, "--as", "a", "--session", "desk-1", "--root", str(root))
        assert (code, out) == (3, ""), argv
        assert err == "lobster-mail %s: %s%s\n" % (argv[0], CHANGING, tail), argv
    assert os.listdir(root / "a" / "duty") == []
    assert not (root / "a" / "duty-log").exists()
