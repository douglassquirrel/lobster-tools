import hashlib
import json

from conftest import every_file, files_in

from lobstertools import message

FIRST = "2026-10-10-0805-a-first-request"
REPLY = "2026-10-10-0900-b-re-first-request"


def test_reply_goes_to_the_original_sender_with_re_subject_and_in_reply_to(run, root, mail_for_b):
    code, out, err = run("reply", FIRST, "--root", str(root), "--as", "b", "-", stdin="Done.\n")
    assert code == 0, err
    assert files_in(root / "a" / "new") == [REPLY + ".md"]
    assert files_in(root / "b" / "sent") == [REPLY + ".md"]
    parsed = message.parse((root / "a" / "new" / (REPLY + ".md")).read_bytes())
    assert parsed.headers["From"] == "b" and parsed.headers["To"] == "a"
    assert parsed.headers["Subject"] == "Re: First request"
    assert parsed.headers["In-Reply-To"] == FIRST
    assert parsed.body == b"Done.\n"
    assert "Replied %s to a" % REPLY in out
    assert (root / "b" / "new" / (FIRST + ".md")).exists()      # the original is not moved


def test_reply_takes_a_subject_override_and_works_from_open_or_done(run, root, mail_for_b, tmp_path):
    body = tmp_path / "r.md"
    body.write_text("Reply body\n")
    run("ack", FIRST, "--root", str(root), "--as", "b")
    code, _, _ = run("reply", FIRST, "--root", str(root), "--as", "b", str(body), "--subject",
                     "Built in commit abc1234")
    assert code == 0
    sent = message.parse((root / "b" / "sent" / "2026-10-10-0900-b-built-in-commit-abc1234.md").read_bytes())
    assert sent.headers["Subject"] == "Built in commit abc1234" and sent.headers["In-Reply-To"] == FIRST
    run("done", FIRST, "--root", str(root), "--as", "b")
    code, _, err = run("reply", FIRST, "--root", str(root), "--as", "b", str(body))
    assert code == 0, err


def test_a_reply_to_a_reply_does_not_pile_up_re(run, root, mail_for_b):
    run("reply", FIRST, "--root", str(root), "--as", "b", "-", stdin="Done.\n")
    code, _, _ = run("reply", REPLY, "--root", str(root), "--as", "a", "-", stdin="Thanks.\n")
    assert code == 0
    back = message.parse((root / "b" / "new" / "2026-10-10-0900-a-re-first-request.md").read_bytes())
    assert back.headers["Subject"] == "Re: First request" and back.headers["In-Reply-To"] == REPLY


def test_reply_refuses_a_message_you_sent_a_hand_dropped_file_and_an_unknown_id(run, root, mail_for_b):
    code, _, err = run("reply", FIRST, "--root", str(root), "--as", "a", "-", stdin="x\n")
    assert code == 3 and "sent/" in err and "lobster-mail send" in err
    code, _, err = run("reply", "note-from-squirrel", "--root", str(root), "--as", "b", "-", stdin="x\n")
    assert code == 5 and "no headers" in err and "lobster-mail send --to" in err
    code, _, err = run("reply", "nothing-here", "--root", str(root), "--as", "b", "-", stdin="x\n")
    assert code == 3 and "no message nothing-here" in err
    assert files_in(root / "a" / "new") == [] and files_in(root / "b" / "sent") == []


def test_reply_dry_run_writes_nothing(run, root, mail_for_b):
    code, out, _ = run("reply", FIRST, "--root", str(root), "--as", "b", "-", "--dry-run", stdin="x\n")
    assert code == 0 and "Would reply %s to a" % REPLY in out and "In-Reply-To: %s" % FIRST in out
    assert files_in(root / "a" / "new") == [] and files_in(root / "b" / "sent") == []


def test_reply_json_names_the_id_and_the_paths(run, root, mail_for_b):
    code, out, _ = run("reply", FIRST, "--root", str(root), "--as", "b", "-", "--json", stdin="x\n")
    assert code == 0
    result = json.loads(out)
    assert result["id"] == REPLY and result["to"] == "a" and result["in_reply_to"] == FIRST
    assert result["path"] == str(root / "a" / "new" / (REPLY + ".md"))


def test_thread_prints_the_chain_oldest_first_with_folders_from_any_member(run, root, mail_for_b):
    run("reply", FIRST, "--root", str(root), "--as", "b", "-", stdin="Done.\n")
    run("reply", REPLY, "--root", str(root), "--as", "a", "-", stdin="Thanks.\n")
    expected = [
        "new/   %s  a  2026-10-10T09:05:00+01:00  First request" % FIRST,
        "sent/  %s  b  2026-10-10T10:00:00+01:00  Re: First request" % REPLY,
        "new/   2026-10-10-0900-a-re-first-request  a  2026-10-10T10:00:00+01:00  Re: First request",
    ]
    for member in (FIRST, REPLY, "2026-10-10-0900-a-re-first-request"):
        code, out, err = run("thread", member, "--root", str(root), "--as", "b")
        assert code == 0, err
        assert out.splitlines() == expected, member


def test_thread_marks_a_link_to_a_message_not_in_this_mailbox(run, root, two):
    headers = {"From": "a", "To": "b", "Date": "2026-10-10T09:00:00+01:00", "Subject": "Orphan",
               "Id": "orphan-reply", "In-Reply-To": "missing-id", "Body-SHA-256": hashlib.sha256(b"x").hexdigest()}
    (root / "b" / "new" / "orphan-reply.md").write_bytes(message.render(headers, b"x"))
    code, out, _ = run("thread", "orphan-reply", "--root", str(root), "--as", "b")
    assert code == 0
    assert out.splitlines() == ["(not in this mailbox: missing-id)",
                                "new/   orphan-reply  a  2026-10-10T09:00:00+01:00  Orphan"]


def test_thread_json_and_unknown_id(run, root, mail_for_b):
    run("reply", FIRST, "--root", str(root), "--as", "b", "-", stdin="Done.\n")
    code, out, _ = run("thread", FIRST, "--root", str(root), "--as", "b", "--json")
    assert code == 0
    items = json.loads(out)
    assert [(i["id"], i["box"], i["in_reply_to"]) for i in items] == [(FIRST, "new", None), (REPLY, "sent", FIRST)]
    code, _, err = run("thread", "nothing-here", "--root", str(root), "--as", "b")
    assert code == 3 and "no message nothing-here" in err


def test_reply_adds_exactly_two_files_and_changes_no_other(run, root, mail_for_b):
    before = every_file(root)
    code, _, err = run("reply", FIRST, "--root", str(root), "--as", "b", "-", stdin="Done.\n")
    assert code == 0, err
    after = every_file(root)
    assert sorted(set(after) - set(before)) == [REPLY + ".md"]
    assert {name: after[name] for name in before} == before
    assert files_in(root / "a" / "new") == [REPLY + ".md"]
    assert files_in(root / "b" / "sent") == [REPLY + ".md"]
