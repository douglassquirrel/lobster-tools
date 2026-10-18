"""duty status --all: who is on duty in every mailbox under the root, read-only."""
import json


def test_duty_status_all_with_as_is_refused(run, root, two):
    code, out, err = run("duty", "status", "--all", "--as", "a", "--root", str(root))
    assert code == 2 and out == ""
    assert "--all" in err and "--as" in err and "not both" in err


def test_all_is_refused_on_take_beat_and_release(run, root, two):
    for action in ("take", "beat", "release"):
        code, out, err = run("duty", action, "--all", "--session", "s", "--root", str(root))
        assert code == 2 and out == "", action
        assert "--all is only for duty status" in err, action


def test_duty_status_all_needs_no_as_and_lists_an_empty_root(run, root, two, monkeypatch):
    empty = root.parent / "empty-root"
    empty.mkdir()
    code, out, err = run("duty", "status", "--all", "--root", str(empty))
    assert (code, err) == (0, "")
    assert out == "No mailboxes in %s\n" % empty


def all_json(run, root, *extra):
    code, out, err = run("duty", "status", "--all", "--json", "--root", str(root), *extra)
    assert (code, err) == (0, "")
    return json.loads(out)


def test_json_lists_each_mailbox_in_name_order_with_its_counts(run, root, mail_for_b):
    run("ack", "--as", "b", "--root", str(root))
    assert all_json(run, root) == {"root": str(root), "skipped": [], "mailboxes": [
        {"mailbox": "a", "duty": None, "duty_changing": False, "new": 0, "open": 0,
         "handover_waiting": False},
        {"mailbox": "b", "duty": None, "duty_changing": False, "new": 2, "open": 1,
         "handover_waiting": False},
    ]}


def test_each_duty_is_what_duty_status_gives_and_a_stale_one_is_left_in_place(run, root, two,
                                                                             monkeypatch):
    monkeypatch.setenv("LOBSTER_MAIL_NOW", "2026-10-10T08:00:00+01:00")
    run("duty", "take", "--as", "b", "--session", "old-desk", "--root", str(root))
    monkeypatch.setenv("LOBSTER_MAIL_NOW", "2026-10-10T09:55:00+01:00")
    run("duty", "take", "--as", "a", "--session", "desk-1", "--root", str(root))
    monkeypatch.setenv("LOBSTER_MAIL_NOW", "2026-10-10T10:00:00+01:00")
    listed = {e["mailbox"]: e["duty"] for e in all_json(run, root)["mailboxes"]}
    for name in ("a", "b"):
        _, single, _ = run("duty", "status", "--as", name, "--json", "--root", str(root))
        assert listed[name] == json.loads(single), name
    assert listed["a"]["stale"] is False and listed["a"]["minutes"] == 5
    assert listed["b"] == {"mailbox": "b", "holder": "old-desk", "since": "2026-10-10T07:00:00Z",
                           "last_beat": "2026-10-10T07:00:00Z", "stale": True, "minutes": 120}
    assert (root / "b" / "duty" / "holder").read_text() == "old-desk\n2026-10-10T07:00:00Z\n"
    assert not (root / "b" / "duty-log").exists()
    assert all_json(run, root, "--stale", "180")["mailboxes"][1]["duty"]["stale"] is False
    assert all_json(run, root, "--stale", "5")["mailboxes"][0]["duty"]["stale"] is True


def test_handover_waiting_is_true_only_for_a_message_from_the_mailbox_to_itself(run, root, two):
    run("send", "--as", "a", "--to", "b", "--subject", "Not a handover", "-", "--root", str(root),
        stdin="for b\n")
    code, _, err = run("handover", "--as", "a", "-", "--root", str(root), stdin="Stopped here.\n")
    assert code == 0, err
    listed = {e["mailbox"]: e for e in all_json(run, root)["mailboxes"]}
    assert (listed["a"]["new"], listed["a"]["handover_waiting"]) == (1, True)
    assert (listed["b"]["new"], listed["b"]["handover_waiting"]) == (1, False)


def test_a_folder_that_is_not_a_whole_mailbox_is_skipped_and_named(run, root, two):
    (root / "half" / "new").mkdir(parents=True)
    (root / ".hidden").mkdir()
    (root / "notes.txt").write_text("not a mailbox\n")
    listing = all_json(run, root)
    assert [e["mailbox"] for e in listing["mailboxes"]] == ["a", "b"]
    assert listing["skipped"] == ["half"]


def test_a_missing_root_is_refused_with_exit_3_and_how_to_make_one(run, root):
    code, out, err = run("duty", "status", "--all", "--root", str(root))
    assert code == 3 and out == ""
    assert err == ("lobster-mail duty: the mail root %s does not exist (lobster-mail init NAME "
                   "makes it and a first mailbox)\n" % root)


def test_without_json_it_prints_one_line_per_mailbox_and_the_skipped_folders(run, root, two,
                                                                            monkeypatch):
    run("init", "carol", "--root", str(root))
    (root / "half" / "new").mkdir(parents=True)
    run("send", "--as", "a", "--to", "carol", "--subject", "Hello", "-", "--root", str(root),
        stdin="hi\n")
    run("handover", "--as", "carol", "-", "--root", str(root), stdin="Stopped.\n")
    run("ack", "--as", "carol", "--root", str(root))
    monkeypatch.setenv("LOBSTER_MAIL_NOW", "2026-10-10T08:00:00+01:00")
    run("duty", "take", "--as", "b", "--session", "old-desk", "--root", str(root))
    monkeypatch.setenv("LOBSTER_MAIL_NOW", "2026-10-10T09:55:00+01:00")
    run("duty", "take", "--as", "a", "--session", "desk-1", "--root", str(root))
    monkeypatch.setenv("LOBSTER_MAIL_NOW", "2026-10-10T10:00:00+01:00")
    code, out, err = run("duty", "status", "--all", "--root", str(root))
    assert (code, err) == (0, "")
    assert out == (
        "a      on duty desk-1, fresh, last beat 2026-10-10T08:55:00Z (5 minutes ago)  "
        "new 0  open 0  handover no\n"
        "b      on duty old-desk, stale, last beat 2026-10-10T07:00:00Z (120 minutes ago)  "
        "new 0  open 0  handover no\n"
        "carol  nobody on duty  new 1  open 1  handover waiting\n"
        "Not mailboxes, skipped: half\n")


def snapshot(root):
    """Every folder and file under the root, files with their bytes."""
    return {str(p.relative_to(root)): (p.read_bytes() if p.is_file() else "folder")
            for p in sorted(root.rglob("*"))}


def test_it_changes_nothing_under_the_root_not_even_a_stale_duty(run, root, mail_for_b,
                                                               monkeypatch):
    monkeypatch.setenv("LOBSTER_MAIL_NOW", "2026-10-10T08:00:00+01:00")
    run("duty", "take", "--as", "b", "--session", "old-desk", "--root", str(root))
    run("handover", "--as", "a", "-", "--root", str(root), stdin="Stopped.\n")
    (root / "half" / "new").mkdir(parents=True)
    monkeypatch.setenv("LOBSTER_MAIL_NOW", "2026-10-10T10:00:00+01:00")
    before = snapshot(root)
    assert run("duty", "status", "--all", "--root", str(root))[0] == 0
    assert snapshot(root) == before
    assert all_json(run, root)["mailboxes"][1]["duty"]["stale"] is True
    assert snapshot(root) == before
