import hashlib
import json
import os

from conftest import HOSTILE, every_file, files_in
from lobstertools import message

ID = "2026-10-10-0900-a-hello-there"


def test_send_delivers_to_new_and_keeps_the_same_bytes_in_sent(run, root, two):
    code, out, err = run("send", "--root", str(root), "--as", "a", "--to", "b", "--subject",
                         "Hello there", str(two))
    assert code == 0, err
    assert files_in(root / "b" / "new") == [ID + ".md"]
    assert files_in(root / "a" / "sent") == [ID + ".md"]
    delivered = (root / "b" / "new" / (ID + ".md")).read_bytes()
    assert (root / "a" / "sent" / (ID + ".md")).read_bytes() == delivered
    parsed = message.parse(delivered)
    assert parsed.body == HOSTILE
    assert parsed.headers == {
        "From": "a", "To": "b", "Date": "2026-10-10T10:00:00+01:00", "Subject": "Hello there",
        "Id": ID, "Body-SHA-256": hashlib.sha256(HOSTILE).hexdigest(),
    }
    assert "Sent %s to b" % ID in out
    assert str(root / "b" / "new" / (ID + ".md")) in out
    assert hashlib.sha256(delivered).hexdigest() in out
    assert files_in(root / "b" / "tmp") == [] and files_in(root / "a" / "tmp") == []


def test_send_reads_the_body_from_stdin_with_a_dash(run, root, two):
    code, _, _ = run("send", "--root", str(root), "--as", "a", "--to", "b", "--subject", "Hi", "-",
                     stdin="from stdin\n")
    assert code == 0
    delivered = (root / "b" / "new" / "2026-10-10-0900-a-hi.md").read_bytes()
    assert message.parse(delivered).body == b"from stdin\n"


def test_send_refuses_an_empty_or_missing_body(run, root, two, tmp_path):
    empty = tmp_path / "empty.md"
    empty.write_bytes(b"")
    code, _, err = run("send", "--root", str(root), "--as", "a", "--to", "b", "--subject", "x",
                       str(empty))
    assert code == 2 and "empty" in err
    code, _, err = run("send", "--root", str(root), "--as", "a", "--to", "b", "--subject", "x",
                       str(tmp_path / "missing.md"))
    assert code == 2 and "missing.md" in err
    assert files_in(root / "b" / "new") == []


def test_send_refuses_an_empty_or_multi_line_subject(run, root, two):
    for subject in ["", "   ", "two\nlines"]:
        code, _, err = run("send", "--root", str(root), "--as", "a", "--to", "b", "--subject",
                           subject, str(two))
        assert code == 2, repr(subject)
        assert "subject" in err
    assert files_in(root / "b" / "new") == []


def test_send_refuses_an_unknown_recipient_or_sender_and_writes_nothing(run, root, two):
    code, _, err = run("send", "--root", str(root), "--as", "a", "--to", "bb", "--subject", "x",
                       str(two))
    assert code == 3 and "no mailbox bb" in err and "lobster-mail init bb" in err
    assert not (root / "bb").exists()
    code, _, err = run("send", "--root", str(root), "--as", "aa", "--to", "b", "--subject", "x",
                       str(two))
    assert code == 3 and "no mailbox aa" in err
    assert files_in(root / "b" / "new") == [] and files_in(root / "a" / "sent") == []


def test_send_adds_a_counter_when_the_id_is_taken(run, root, two):
    for _ in range(3):
        code, _, _ = run("send", "--root", str(root), "--as", "a", "--to", "b", "--subject",
                         "Hello there", str(two))
        assert code == 0
    expected = sorted([ID + ".md", ID + "-2.md", ID + "-3.md"])
    assert files_in(root / "b" / "new") == expected
    assert files_in(root / "a" / "sent") == expected


def test_send_dry_run_shows_the_headers_and_writes_nothing(run, root, two):
    code, out, _ = run("send", "--root", str(root), "--as", "a", "--to", "b", "--subject",
                       "Hello there", str(two), "--dry-run")
    assert code == 0
    assert "Would send %s to b" % ID in out
    assert "From: a\nTo: b\nDate: 2026-10-10T10:00:00+01:00\nSubject: Hello there\nId: %s\n" % ID in out
    for folder in ("new", "tmp"):
        assert files_in(root / "b" / folder) == []
    assert files_in(root / "a" / "sent") == []


def test_send_goes_through_tmp_and_publishes_by_rename(run, root, two, monkeypatch):
    renames = []
    real = os.rename

    def recording(src, dst):
        renames.append((src, dst))
        real(src, dst)

    monkeypatch.setattr(os, "rename", recording)
    code, _, _ = run("send", "--root", str(root), "--as", "a", "--to", "b", "--subject", "Hi",
                     str(two))
    assert code == 0
    assert [(os.path.relpath(s, root), os.path.relpath(d, root)) for s, d in renames] == [
        ("b/tmp/2026-10-10-0900-a-hi.md", "b/new/2026-10-10-0900-a-hi.md"),
        ("a/tmp/2026-10-10-0900-a-hi.md", "a/sent/2026-10-10-0900-a-hi.md"),
    ]


def test_a_failed_delivery_leaves_the_whole_file_in_tmp_and_names_it(run, root, two, monkeypatch):
    def refuse(src, dst):
        raise OSError(22, "Invalid argument")

    monkeypatch.setattr(os, "rename", refuse)
    code, out, err = run("send", "--root", str(root), "--as", "a", "--to", "b", "--subject", "Hi",
                         str(two))
    assert code == 4
    tmp = root / "b" / "tmp" / "2026-10-10-0900-a-hi.md"
    assert "could not deliver" in err and str(tmp) in err and "Invalid argument" in err
    assert message.parse(tmp.read_bytes()).body == HOSTILE
    assert files_in(root / "b" / "new") == [] and files_in(root / "a" / "sent") == []


def test_send_never_modifies_the_body_file(run, root, two):
    before = hashlib.sha256(two.read_bytes()).hexdigest()
    run("send", "--root", str(root), "--as", "a", "--to", "b", "--subject", "Hi", str(two))
    assert hashlib.sha256(two.read_bytes()).hexdigest() == before


def test_send_json_names_the_id_the_paths_and_the_hash(run, root, two):
    code, out, _ = run("send", "--root", str(root), "--as", "a", "--to", "b", "--subject",
                       "Hello there", str(two), "--json")
    assert code == 0
    result = json.loads(out)
    delivered = root / "b" / "new" / (ID + ".md")
    assert result == {
        "id": ID, "from": "a", "to": "b", "subject": "Hello there",
        "path": str(delivered), "sent_copy": str(root / "a" / "sent" / (ID + ".md")),
        "sha256": hashlib.sha256(delivered.read_bytes()).hexdigest(),
    }


def test_send_adds_exactly_two_files_and_changes_no_other(run, root, mail_for_b, two):
    before = every_file(root)
    code, _, err = run("send", "--root", str(root), "--as", "b", "--to", "a", "--subject", "Hi", str(two))
    assert code == 0, err
    after = every_file(root)
    assert sorted(set(after) - set(before)) == ["2026-10-10-0900-b-hi.md"]
    assert {name: after[name] for name in before} == before
    assert files_in(root / "a" / "new") == ["2026-10-10-0900-b-hi.md"]
    assert files_in(root / "b" / "sent") == ["2026-10-10-0900-b-hi.md"]
