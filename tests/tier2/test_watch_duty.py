import json

from conftest import every_file

from lobstertools import mail

FIRST = "2026-10-10-0805-a-first-request"


def test_watch_returns_at_once_when_mail_is_waiting(run, root, mail_for_b):
    code, out, err = run("watch", "--root", str(root), "--as", "b", "--timeout", "30")
    assert code == 0, err
    lines = out.splitlines()
    assert lines[0].startswith(FIRST + "  a  ") and len(lines) == 3
    assert "new messages" not in out
    code, out, _ = run("watch", "--root", str(root), "--as", "b", "--json")
    assert json.loads(out)[0]["id"] == FIRST


def test_watch_times_out_with_exit_5_when_nothing_arrives(run, root, two, monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr(mail.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(mail.time, "sleep", lambda s: clock.__setitem__("t", clock["t"] + s))
    code, out, err = run("watch", "--root", str(root), "--as", "a", "--timeout", "5", "--every", "2")
    assert code == 5 and out == ""
    assert "No new mail for a after 5 seconds" in err


def test_watch_returns_when_mail_arrives_during_the_wait(run, root, two, monkeypatch):
    clock = {"t": 0.0, "sleeps": 0}

    def sleep(seconds):
        clock["t"] += seconds
        clock["sleeps"] += 1
        if clock["sleeps"] == 2:
            (root / "a" / "new" / "dropped.md").write_bytes(b"hello\n")

    monkeypatch.setattr(mail.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(mail.time, "sleep", sleep)
    code, out, _ = run("watch", "--root", str(root), "--as", "a", "--every", "1")
    assert code == 0 and clock["sleeps"] == 2
    assert out.splitlines()[0].startswith("dropped  (no headers)  ")


def duty_dir(root):
    return root / "a" / "duty"


def test_duty_take_creates_the_lock_and_status_shows_it(run, root, two):
    code, out, err = run("duty", "take", "--root", str(root), "--as", "a", "--session", "desk-1")
    assert code == 0, err
    assert "Duty for a taken by desk-1 at 2026-10-10T09:00:00Z" in out
    assert (duty_dir(root) / "holder").read_text() == "desk-1\n2026-10-10T09:00:00Z\n"
    assert (duty_dir(root) / "heartbeat").read_text() == "2026-10-10T09:00:00Z\n"
    code, out, _ = run("duty", "status", "--root", str(root), "--as", "a")
    assert code == 0
    assert out.strip() == ("a: on duty desk-1 since 2026-10-10T09:00:00Z; last beat "
                           "2026-10-10T09:00:00Z (fresh, 0 minutes ago)")
    code, out, _ = run("duty", "status", "--root", str(root), "--as", "a", "--json")
    assert json.loads(out) == {"mailbox": "a", "holder": "desk-1", "since": "2026-10-10T09:00:00Z",
                               "last_beat": "2026-10-10T09:00:00Z", "stale": False, "minutes": 0}


def test_duty_take_by_another_session_is_refused_while_the_heartbeat_is_fresh(run, root, two, monkeypatch):
    run("duty", "take", "--root", str(root), "--as", "a", "--session", "desk-1")
    monkeypatch.setenv("LOBSTER_MAIL_NOW", "2026-10-10T10:30:00+01:00")
    code, out, err = run("duty", "take", "--root", str(root), "--as", "a", "--session", "desk-2")
    assert code == 3 and out == ""
    assert "held by desk-1" in err and "last beat 2026-10-10T09:00:00Z" in err and "30 minutes" in err
    assert (duty_dir(root) / "holder").read_text().startswith("desk-1\n")


def test_duty_take_by_the_same_session_refreshes_the_heartbeat(run, root, two, monkeypatch):
    run("duty", "take", "--root", str(root), "--as", "a", "--session", "desk-1")
    monkeypatch.setenv("LOBSTER_MAIL_NOW", "2026-10-10T10:20:00+01:00")
    code, out, _ = run("duty", "take", "--root", str(root), "--as", "a", "--session", "desk-1")
    assert code == 0 and "already on duty" in out
    assert (duty_dir(root) / "heartbeat").read_text() == "2026-10-10T09:20:00Z\n"
    assert (duty_dir(root) / "holder").read_text() == "desk-1\n2026-10-10T09:00:00Z\n"


def test_a_stale_lock_is_taken_over_and_kept_in_duty_log(run, root, two, monkeypatch):
    run("duty", "take", "--root", str(root), "--as", "a", "--session", "desk-1")
    monkeypatch.setenv("LOBSTER_MAIL_NOW", "2026-10-10T10:46:00+01:00")
    code, out, _ = run("duty", "status", "--root", str(root), "--as", "a")
    assert "(stale, 46 minutes ago)" in out
    code, out, err = run("duty", "take", "--root", str(root), "--as", "a", "--session", "desk-2")
    assert code == 0, err
    assert "took over from desk-1" in out and "stale" in out
    assert (duty_dir(root) / "holder").read_text() == "desk-2\n2026-10-10T09:46:00Z\n"
    logged = list((root / "a" / "duty-log").iterdir())
    assert [p.name for p in logged] == ["2026-10-10T09-46-00-desk-1"]
    assert (logged[0] / "holder").read_text() == "desk-1\n2026-10-10T09:00:00Z\n"


def test_the_stale_limit_is_a_flag(run, root, two, monkeypatch):
    run("duty", "take", "--root", str(root), "--as", "a", "--session", "desk-1")
    monkeypatch.setenv("LOBSTER_MAIL_NOW", "2026-10-10T10:10:00+01:00")
    code, _, _ = run("duty", "take", "--root", str(root), "--as", "a", "--session", "desk-2", "--stale", "5")
    assert code == 0


def test_duty_beat_and_release_need_the_holder(run, root, two, monkeypatch):
    run("duty", "take", "--root", str(root), "--as", "a", "--session", "desk-1")
    monkeypatch.setenv("LOBSTER_MAIL_NOW", "2026-10-10T10:05:00+01:00")
    code, _, err = run("duty", "beat", "--root", str(root), "--as", "a", "--session", "desk-2")
    assert code == 3 and "held by desk-1" in err
    code, out, _ = run("duty", "beat", "--root", str(root), "--as", "a", "--session", "desk-1")
    assert code == 0 and (duty_dir(root) / "heartbeat").read_text() == "2026-10-10T09:05:00Z\n"
    code, _, err = run("duty", "release", "--root", str(root), "--as", "a", "--session", "desk-2")
    assert code == 3 and "held by desk-1" in err
    code, out, _ = run("duty", "release", "--root", str(root), "--as", "a", "--session", "desk-1")
    assert code == 0 and "released" in out
    assert not duty_dir(root).exists()
    assert [p.name for p in (root / "a" / "duty-log").iterdir()] == ["2026-10-10T09-05-00-desk-1"]
    code, out, _ = run("duty", "status", "--root", str(root), "--as", "a")
    assert code == 0 and out.strip() == "Nobody is on duty for a"
    code, _, err = run("duty", "beat", "--root", str(root), "--as", "a", "--session", "desk-1")
    assert code == 3 and "nobody is on duty" in err


def test_duty_take_beat_and_release_need_a_session_name(run, root, two):
    for action in ("take", "beat", "release"):
        code, _, err = run("duty", action, "--root", str(root), "--as", "a")
        assert code == 2 and "--session" in err, action
    code, _, _ = run("duty", "status", "--root", str(root), "--as", "a")
    assert code == 0


def test_watch_changes_no_message_file(run, root, mail_for_b):
    before = every_file(root)
    code, _, err = run("watch", "--root", str(root), "--as", "b", "--timeout", "30")
    assert code == 0, err
    assert every_file(root) == before


def test_duty_changes_no_message_file(run, root, mail_for_b, monkeypatch):
    before = every_file(root)
    for action in ("take", "beat", "release"):
        code, _, err = run("duty", action, "--root", str(root), "--as", "b", "--session", "desk-1")
        assert code == 0, (action, err)
    run("duty", "take", "--root", str(root), "--as", "b", "--session", "desk-1")
    monkeypatch.setenv("LOBSTER_MAIL_NOW", "2026-10-10T10:46:00+01:00")
    code, _, err = run("duty", "take", "--root", str(root), "--as", "b", "--session", "desk-2")
    assert code == 0, err
    assert every_file(root) == before


def test_a_session_name_must_be_a_plain_name_since_it_names_a_folder(run, root, two):
    for action in ("take", "beat", "release"):
        code, out, err = run("duty", action, "--root", str(root), "--as", "a", "--session", "desk/1")
        assert code == 2 and out == "", action
        assert "--session 'desk/1' is not a plain folder name" in err, action
    assert not duty_dir(root).exists() and not (root / "a" / "duty-log").exists()


def test_duty_take_beat_and_release_print_json_when_asked(run, root, two, monkeypatch):
    code, out, _ = run("duty", "take", "--root", str(root), "--as", "a", "--session", "desk-1", "--json")
    assert code == 0 and json.loads(out) == {
        "mailbox": "a", "holder": "desk-1", "since": "2026-10-10T09:00:00Z",
        "last_beat": "2026-10-10T09:00:00Z", "action": "taken"}
    monkeypatch.setenv("LOBSTER_MAIL_NOW", "2026-10-10T10:05:00+01:00")
    code, out, _ = run("duty", "take", "--root", str(root), "--as", "a", "--session", "desk-1", "--json")
    assert code == 0 and json.loads(out)["action"] == "refreshed"
    assert json.loads(out)["last_beat"] == "2026-10-10T09:05:00Z"
    code, out, _ = run("duty", "beat", "--root", str(root), "--as", "a", "--session", "desk-1", "--json")
    assert code == 0 and json.loads(out) == {
        "mailbox": "a", "holder": "desk-1", "since": "2026-10-10T09:00:00Z",
        "last_beat": "2026-10-10T09:05:00Z", "action": "beat"}
    code, out, _ = run("duty", "release", "--root", str(root), "--as", "a", "--session", "desk-1", "--json")
    assert code == 0 and json.loads(out) == {
        "mailbox": "a", "holder": "desk-1", "since": "2026-10-10T09:00:00Z",
        "last_beat": "2026-10-10T09:05:00Z", "action": "released",
        "logged": str(root / "a" / "duty-log" / "2026-10-10T09-05-00-desk-1")}
    run("duty", "take", "--root", str(root), "--as", "a", "--session", "desk-1")
    monkeypatch.setenv("LOBSTER_MAIL_NOW", "2026-10-10T10:51:00+01:00")
    code, out, _ = run("duty", "take", "--root", str(root), "--as", "a", "--session", "desk-2", "--json")
    assert code == 0 and json.loads(out) == {
        "mailbox": "a", "holder": "desk-2", "since": "2026-10-10T09:51:00Z",
        "last_beat": "2026-10-10T09:51:00Z", "action": "taken", "took_over_from": "desk-1",
        "logged": str(root / "a" / "duty-log" / "2026-10-10T09-51-00-desk-1")}
