import json
import os

from conftest import HOSTILE, every_file

from lobstertools import message

FIRST = "2026-10-10-0805-a-first-request"
SECOND = "2026-10-10-0840-a-second-a-follow-up"


def test_ack_moves_a_new_message_to_open_and_prints_it(run, root, mail_for_b):
    before = every_file(root)
    code, out, err = run("ack", FIRST, "--root", str(root), "--as", "b")
    assert code == 0, err
    assert not (root / "b" / "new" / (FIRST + ".md")).exists()
    moved = root / "b" / "open" / (FIRST + ".md")
    assert out == moved.read_bytes().decode("utf-8")
    assert message.parse(moved.read_bytes()).body == HOSTILE
    assert every_file(root) == before


def test_ack_of_a_message_not_in_new_says_where_it_is(run, root, mail_for_b):
    run("ack", FIRST, "--root", str(root), "--as", "b")
    code, out, err = run("ack", FIRST, "--root", str(root), "--as", "b")
    assert code == 3 and out == ""
    assert "already claimed" in err and "open/" in err
    code, _, err = run("ack", "nothing-here", "--root", str(root), "--as", "b")
    assert code == 3 and "no message nothing-here" in err


def test_ack_that_loses_the_race_reports_the_other_session(run, root, mail_for_b, monkeypatch):
    real = os.rename

    def another_session_first(src, dst):
        real(src, dst)          # the other session claims it first ...
        real(src, dst)          # ... so our own rename finds nothing to move

    monkeypatch.setattr(os, "rename", another_session_first)
    code, out, err = run("ack", FIRST, "--root", str(root), "--as", "b")
    assert code == 3 and out == ""
    assert "another session" in err and "open/" in err
    assert (root / "b" / "open" / (FIRST + ".md")).exists()


def test_ack_dry_run_moves_nothing_and_prints_nothing_of_the_body(run, root, mail_for_b):
    before = every_file(root)
    code, out, _ = run("ack", FIRST, "--root", str(root), "--as", "b", "--dry-run")
    assert code == 0
    assert "Would claim %s: new/ -> open/" % FIRST in out and "rm -rf" not in out
    assert (root / "b" / "new" / (FIRST + ".md")).exists()
    assert every_file(root) == before


def test_ack_json_gives_the_headers_and_the_body(run, root, mail_for_b):
    code, out, _ = run("ack", SECOND, "--root", str(root), "--as", "b", "--json")
    assert code == 0
    result = json.loads(out)
    assert result["id"] == SECOND and result["from"] == "a" and result["subject"] == "Second: a follow-up"
    assert result["body"] == "Second body\n"
    assert result["path"] == str(root / "b" / "open" / (SECOND + ".md"))


def test_ack_claims_a_hand_dropped_file_too(run, root, mail_for_b):
    code, out, _ = run("ack", "note-from-squirrel", "--root", str(root), "--as", "b")
    assert code == 0 and out == "From: me\n\nJust a note.\n"
    assert (root / "b" / "open" / "note-from-squirrel.md").exists()


def test_ack_reports_a_tampered_body_after_claiming_it(run, root, mail_for_b):
    path = root / "b" / "new" / (FIRST + ".md")
    path.write_bytes(path.read_bytes() + b"x")
    code, out, err = run("ack", FIRST, "--root", str(root), "--as", "b")
    assert code == 5 and "SHA-256" in err and out.endswith("x")
    assert (root / "b" / "open" / (FIRST + ".md")).exists()


def test_done_moves_from_new_or_open_to_done(run, root, mail_for_b):
    before = every_file(root)
    code, out, err = run("done", FIRST, "--root", str(root), "--as", "b")
    assert code == 0, err
    assert "Done %s: new/ -> done/" % FIRST in out
    run("ack", SECOND, "--root", str(root), "--as", "b")
    code, out, _ = run("done", SECOND, "--root", str(root), "--as", "b", "--json")
    assert code == 0
    assert json.loads(out) == {"id": SECOND, "from_box": "open", "to_box": "done",
                               "path": str(root / "b" / "done" / (SECOND + ".md"))}
    assert sorted(p.name for p in (root / "b" / "done").iterdir()) == [FIRST + ".md", SECOND + ".md"]
    assert every_file(root) == before


def test_done_refuses_a_message_already_done_one_you_sent_or_unknown(run, root, mail_for_b):
    run("done", FIRST, "--root", str(root), "--as", "b")
    code, _, err = run("done", FIRST, "--root", str(root), "--as", "b")
    assert code == 3 and "already in done/" in err
    code, _, err = run("done", FIRST, "--root", str(root), "--as", "a")
    assert code == 3 and "sent/" in err and "you sent" in err
    code, _, err = run("done", "nothing-here", "--root", str(root), "--as", "b")
    assert code == 3 and "no message nothing-here" in err


def test_done_dry_run_moves_nothing(run, root, mail_for_b):
    before = every_file(root)
    code, out, _ = run("done", FIRST, "--root", str(root), "--as", "b", "--dry-run")
    assert code == 0 and "Would move %s: new/ -> done/" % FIRST in out
    assert (root / "b" / "new" / (FIRST + ".md")).exists()
    assert every_file(root) == before


def test_an_unknown_id_is_answered_with_the_ids_waiting_in_new(run, root, mail_for_b):
    for verb in ("ack", "done", "read", "thread"):
        code, _, err = run(verb, "2026-10-10-0805-a-first-reqeust", "--root", str(root), "--as", "b")
        assert code == 3, verb
        assert ("no message 2026-10-10-0805-a-first-reqeust in b's new/, open/, done/ or sent/; "
                "new/ holds: 2026-10-10-0805-a-first-request, 2026-10-10-0840-a-second-a-follow-up, "
                "note-from-squirrel") in err, verb
    code, _, err = run("reply", "nothing-here", "--root", str(root), "--as", "b", "-", stdin="x\n")
    assert code == 3 and "; new/ holds: 2026-10-10-0805-a-first-request, " in err
    code, _, err = run("ack", "nothing-here", "--root", str(root), "--as", "a")
    assert code == 3 and "or sent/; new/ is empty" in err


def test_ack_without_an_id_claims_the_oldest_new_message(run, root, mail_for_b):
    before = every_file(root)
    code, out, err = run("ack", "--root", str(root), "--as", "b", "--dry-run")
    assert code == 0, err
    assert out.strip() == "Would claim %s: new/ -> open/" % FIRST
    assert every_file(root) == before
    code, out, err = run("ack", "--root", str(root), "--as", "b")
    assert code == 0, err
    assert out.startswith("From: a\nTo: b\n") and "Subject: First request\n" in out
    assert os.path.isfile(root / "b" / "open" / (FIRST + ".md"))
    assert every_file(root) == before
    code, out, _ = run("ack", "--root", str(root), "--as", "b", "--json")
    assert code == 0 and json.loads(out)["id"] == SECOND
    code, out, err = run("ack", "--root", str(root), "--as", "a")
    assert code == 3 and out == ""
    assert "no new mail for a; nothing to claim" in err
