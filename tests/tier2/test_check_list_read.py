import json

from conftest import HOSTILE, REMINDER, files_in
from lobstertools import message


def snapshot(root):
    return {box: files_in(root / name / box) for name in ("a", "b")
            for box in ("tmp", "new", "open", "done", "sent")}


def test_check_lists_new_mail_oldest_first_with_the_count_and_the_reminder(run, root, mail_for_b):
    before = snapshot(root)
    code, out, err = run("check", "--root", str(root), "--as", "b")
    assert code == 0, err
    lines = out.splitlines()
    assert lines[0] == "2026-10-10-0905-a-first-request  a  2026-10-10T09:05:00+01:00  First request"
    assert lines[1] == ("2026-10-10-0940-a-second-a-follow-up  a  2026-10-10T09:40:00+01:00  "
                        "Second: a follow-up")
    assert lines[2].startswith("note-from-squirrel  (no headers)  ") and lines[2].endswith(
        "  note-from-squirrel.md")
    assert lines[3] == "3 new messages for b"
    assert lines[4] == REMINDER
    assert snapshot(root) == before


def test_check_with_no_new_mail_says_so(run, root, two):
    code, out, _ = run("check", "--root", str(root), "--as", "a")
    assert code == 0
    assert out.splitlines() == ["No new mail for a", REMINDER]


def test_check_json_gives_id_from_date_subject_and_path(run, root, mail_for_b):
    code, out, _ = run("check", "--root", str(root), "--as", "b", "--json")
    assert code == 0
    items = json.loads(out)
    assert [i["id"] for i in items] == mail_for_b
    assert items[0] == {
        "id": "2026-10-10-0905-a-first-request", "from": "a", "date": "2026-10-10T09:05:00+01:00",
        "subject": "First request", "box": "new",
        "path": str(root / "b" / "new" / "2026-10-10-0905-a-first-request.md"), "headers": True,
    }
    assert items[2]["headers"] is False and items[2]["from"] is None
    assert items[2]["subject"] == "note-from-squirrel.md"


def test_list_shows_all_four_folders_with_counts_or_just_one(run, root, mail_for_b):
    code, out, _ = run("list", "--root", str(root), "--as", "a")
    assert code == 0
    assert "new/ (0)" in out and "open/ (0)" in out and "done/ (0)" in out and "sent/ (2)" in out
    assert "2026-10-10-0905-a-first-request  a  2026-10-10T09:05:00+01:00  First request" in out
    code, out, _ = run("list", "--root", str(root), "--as", "b", "--new")
    assert code == 0
    assert out.splitlines()[0] == "new/ (3)"
    assert "sent/" not in out
    code, out, _ = run("list", "--root", str(root), "--as", "b", "--sent", "--json")
    assert json.loads(out) == []


def test_read_prints_the_file_verbatim_and_moves_nothing(run, root, mail_for_b):
    path = root / "b" / "new" / "2026-10-10-0905-a-first-request.md"
    before = snapshot(root)
    code, out, err = run("read", "2026-10-10-0905-a-first-request", "--root", str(root), "--as", "b")
    assert code == 0, err
    assert out == path.read_bytes().decode("utf-8")
    assert message.parse(path.read_bytes()).body == HOSTILE
    assert snapshot(root) == before


def test_read_finds_a_message_in_sent_too_and_reads_a_hand_dropped_file(run, root, mail_for_b):
    code, out, _ = run("read", "2026-10-10-0905-a-first-request", "--root", str(root), "--as", "a")
    assert code == 0 and "Subject: First request" in out
    code, out, _ = run("read", "note-from-squirrel", "--root", str(root), "--as", "b")
    assert code == 0 and out == "From: me\n\nJust a note.\n"


def test_read_reports_a_body_that_no_longer_matches_its_hash_but_still_prints_it(run, root, mail_for_b):
    path = root / "b" / "new" / "2026-10-10-0905-a-first-request.md"
    path.write_bytes(path.read_bytes() + b"tampered")
    code, out, err = run("read", "2026-10-10-0905-a-first-request", "--root", str(root), "--as", "b")
    assert code == 5
    assert "SHA-256" in err and "stale or altered" in err
    assert out.endswith("tampered")


def test_read_of_an_unknown_id_says_where_it_looked(run, root, two):
    code, out, err = run("read", "nothing-here", "--root", str(root), "--as", "a")
    assert code == 3
    assert "nothing-here" in err and "new/, open/, done/ or sent/" in err and out == ""
