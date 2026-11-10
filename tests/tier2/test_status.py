"""status: a short status the session on duty reports about itself, kept with the duty (PLAN.md
"A status a session reports about itself")."""
import json

UNTIL = "2026-10-10T10:30:00Z"


def take(run, root, session="desk", box="b"):
    code, _, err = run("duty", "take", "--as", box, "--session", session, "--root", str(root))
    assert code == 0, err


def status(run, root, *argv):
    return run("status", "--as", "b", "--root", str(root), *argv)


def test_the_holder_sets_a_status_with_until_and_status_shows_it(run, root, two):
    take(run, root)
    code, out, err = status(run, root, "--session", "desk", "dreaming", "--until", UNTIL)
    assert (code, err) == (0, "")
    assert out == ('Status for b set by desk at 2026-10-10T09:00:00Z: "dreaming", until '
                   '2026-10-10T10:30:00Z\n')
    code, out, err = status(run, root)
    assert (code, err) == (0, "")
    assert out == ('Status for b: "dreaming", set by desk at 2026-10-10T09:00:00Z, until '
                   '2026-10-10T10:30:00Z\n')


def test_a_status_without_until_says_none(run, root, two):
    take(run, root)
    code, out, _ = status(run, root, "--session", "desk", "dormant")
    assert code == 0
    assert out == 'Status for b set by desk at 2026-10-10T09:00:00Z: "dormant"\n'
    _, out, _ = status(run, root)
    assert out == 'Status for b: "dormant", set by desk at 2026-10-10T09:00:00Z\n'


def test_json_carries_reported_for_set_show_and_clear(run, root, two):
    take(run, root)
    reported = {"status": "dreaming", "set": "2026-10-10T09:00:00Z", "until": UNTIL}
    code, out, _ = status(run, root, "--session", "desk", "dreaming", "--until", UNTIL, "--json")
    assert code == 0
    assert json.loads(out) == {"mailbox": "b", "holder": "desk", "reported": reported,
                               "action": "set"}
    _, out, _ = status(run, root, "--json")
    assert json.loads(out) == {"mailbox": "b", "holder": "desk", "reported": reported}
    _, out, _ = status(run, root, "--session", "desk", "--clear", "--json")
    assert json.loads(out) == {"mailbox": "b", "holder": "desk", "reported": None,
                               "action": "cleared"}
    _, out, _ = status(run, root, "--json")
    assert json.loads(out) == {"mailbox": "b", "holder": "desk", "reported": None}


def test_clear_leaves_no_status_and_deletes_nothing(run, root, two):
    take(run, root)
    status(run, root, "--session", "desk", "dreaming")
    code, out, err = status(run, root, "--session", "desk", "--clear")
    assert (code, err) == (0, "")
    assert out == "Status for b cleared by desk at 2026-10-10T09:00:00Z\n"
    _, out, _ = status(run, root)
    assert out == "No status for b\n"
    assert sorted(p.name for p in (root / "b" / "duty").iterdir()) == [
        "heartbeat", "holder", "status"]
    assert (root / "b" / "duty" / "status").read_text() == "{}\n"


def test_a_new_status_replaces_the_old_one(run, root, two, monkeypatch):
    take(run, root)
    status(run, root, "--session", "desk", "dreaming", "--until", UNTIL)
    monkeypatch.setenv("LOBSTER_MAIL_NOW", "2026-10-10T10:05:00+01:00")
    status(run, root, "--session", "desk", "waiting for Squirrel")
    _, out, _ = status(run, root)
    assert out == 'Status for b: "waiting for Squirrel", set by desk at 2026-10-10T09:05:00Z\n'


def test_no_status_ever_set_and_nobody_on_duty_both_show_none(run, root, two):
    code, out, err = status(run, root)
    assert (code, out, err) == (0, "No status for b\n", "")
    _, out, _ = status(run, root, "--json")
    assert json.loads(out) == {"mailbox": "b", "holder": None, "reported": None}
    take(run, root)
    assert status(run, root)[1] == "No status for b\n"


def test_hostile_text_is_stored_and_shown_as_given(run, root, two):
    take(run, root)
    text = "q \"x\" 'y' $(rm -rf /) `z` \\ café 日本 ✓ </script>"
    code, _, err = status(run, root, "--session", "desk", text)
    assert (code, err) == (0, "")
    _, out, _ = status(run, root)
    assert out == 'Status for b: "%s", set by desk at 2026-10-10T09:00:00Z\n' % text
    _, out, _ = status(run, root, "--json")
    assert json.loads(out)["reported"]["status"] == text


def test_setting_a_status_does_not_beat_the_heartbeat(run, root, two, monkeypatch):
    take(run, root)
    monkeypatch.setenv("LOBSTER_MAIL_NOW", "2026-10-10T10:20:00+01:00")
    status(run, root, "--session", "desk", "dreaming")
    assert (root / "b" / "duty" / "heartbeat").read_text() == "2026-10-10T09:00:00Z\n"


def duty_files(root, box="b"):
    folder = root / box / "duty"
    if not folder.exists():
        return None
    return {p.name: p.read_bytes() for p in folder.iterdir()}


def test_setting_or_clearing_needs_a_session(run, root, two):
    take(run, root)
    before = duty_files(root)
    for argv in (["dreaming"], ["--clear"]):
        code, out, err = status(run, root, *argv)
        assert code == 2 and out == "", argv
        assert "--session NAME is required to set or clear a status" in err
    assert duty_files(root) == before


def test_nobody_on_duty_refuses_to_set_and_creates_nothing(run, root, two):
    for argv in (["dreaming"], ["--clear"]):
        code, out, err = status(run, root, "--session", "desk", *argv)
        assert (code, out) == (3, ""), argv
        assert err == ("lobster-mail status: nobody is on duty for b; only the session on duty "
                       "may set or clear its status\n")
    assert duty_files(root) is None


def test_another_session_may_not_set_or_clear_and_nothing_changes(run, root, two):
    take(run, root)
    status(run, root, "--session", "desk", "dreaming")
    before = duty_files(root)
    for argv in (["dormant"], ["--clear"]):
        code, out, err = status(run, root, "--session", "other", *argv)
        assert (code, out) == (3, ""), argv
        assert err == ("lobster-mail status: duty for b is held by desk, not other; only the "
                       "session on duty may set or clear its status\n")
    assert duty_files(root) == before


def test_bad_text_or_until_is_refused_and_nothing_changes(run, root, two):
    take(run, root)
    before = duty_files(root)
    cases = [
        (["dreaming", "--clear"], "give a status or --clear, not both"),
        (["--until", UNTIL], "--until goes with a status to set"),
        (["--clear", "--until", UNTIL], "--until goes with a status to set"),
        (["two\nlines"], "the status must be one line of plain text"),
        (["x" * 61], "this one has 61"),
        (["dreaming", "--until", "soon"], "--until 'soon' is not a time with a zone"),
    ]
    for argv, said in cases:
        code, out, err = status(run, root, "--session", "desk", *argv)
        assert (code, out) == (2, ""), argv
        assert said in err, argv
    assert duty_files(root) == before


def test_the_holder_of_a_stale_duty_may_still_set_and_clear(run, root, two, monkeypatch):
    take(run, root)
    monkeypatch.setenv("LOBSTER_MAIL_NOW", "2026-10-10T12:00:00+01:00")
    code, _, err = status(run, root, "--session", "desk", "dormant")
    assert (code, err) == (0, "")
    code, _, err = status(run, root, "--session", "desk", "--clear")
    assert (code, err) == (0, "")


def test_session_may_come_from_the_environment(run, root, two, monkeypatch):
    take(run, root)
    monkeypatch.setenv("LOBSTER_MAIL_SESSION", "desk")
    code, out, _ = status(run, root, "dreaming")
    assert code == 0 and out.startswith("Status for b set by desk")


def duty_json(run, root, *argv):
    code, out, err = run("duty", "status", "--json", "--root", str(root), *argv)
    assert (code, err) == (0, "")
    return json.loads(out)


def test_duty_status_shows_the_status_in_text_and_json(run, root, two):
    take(run, root)
    status(run, root, "--session", "desk", "dreaming", "--until", UNTIL)
    _, out, _ = run("duty", "status", "--as", "b", "--root", str(root))
    assert out == ("b: on duty desk since 2026-10-10T09:00:00Z; last beat 2026-10-10T09:00:00Z "
                   "(fresh, 0 minutes ago); reporting \"dreaming\" since 2026-10-10T09:00:00Z "
                   "(until 2026-10-10T10:30:00Z)\n")
    reported = {"status": "dreaming", "set": "2026-10-10T09:00:00Z", "until": UNTIL}
    assert duty_json(run, root, "--as", "b")["reported"] == reported
    entries = {e["mailbox"]: e for e in duty_json(run, root, "--all")["mailboxes"]}
    assert entries["b"]["reported"] == reported
    assert entries["a"]["reported"] is None


def test_duty_status_all_text_shows_the_status_after_the_duty(run, root, two):
    take(run, root)
    status(run, root, "--session", "desk", "dormant")
    _, out, _ = run("duty", "status", "--all", "--root", str(root))
    assert out == (
        "a  nobody on duty  new 0  open 0  handover no  pace normal\n"
        "b  on duty desk, fresh, last beat 2026-10-10T09:00:00Z (0 minutes ago); reporting "
        "\"dormant\" since 2026-10-10T09:00:00Z  new 0  open 0  handover no  pace normal\n")


def test_with_no_status_duty_status_is_as_before_but_for_reported_null(run, root, two):
    take(run, root)
    _, out, _ = run("duty", "status", "--as", "b", "--root", str(root))
    assert out == ("b: on duty desk since 2026-10-10T09:00:00Z; last beat 2026-10-10T09:00:00Z "
                   "(fresh, 0 minutes ago)\n")
    assert duty_json(run, root, "--as", "b") == {
        "mailbox": "b", "holder": "desk", "since": "2026-10-10T09:00:00Z",
        "last_beat": "2026-10-10T09:00:00Z", "stale": False, "minutes": 0, "reported": None}
    _, out, _ = run("duty", "status", "--as", "a", "--json", "--root", str(root))
    assert out == "null\n"


def test_a_status_file_that_is_not_a_status_is_exit_5_and_shown_as_none_by_duty(run, root, two):
    take(run, root)
    (root / "b" / "duty" / "status").write_text("not json\n")
    code, out, err = status(run, root)
    assert (code, out) == (5, "")
    assert err == ("lobster-mail status: the status file in %s is not a status; set one with "
                   "status TEXT, or clear it with status --clear\n" % (root / "b" / "duty"))
    assert duty_json(run, root, "--as", "b")["reported"] is None
    for text in ('["a list"]\n', '{"status": "dreaming"}\n'):
        (root / "b" / "duty" / "status").write_text(text)
        assert status(run, root)[0] == 5, text
        assert duty_json(run, root, "--as", "b")["reported"] is None, text


def test_handover_release_and_a_stale_takeover_each_clear_it_and_keep_it_in_the_log(
        run, root, two, monkeypatch):
    def logged():
        return sorted((root / "b" / "duty-log").iterdir())

    take(run, root)
    status(run, root, "--session", "desk", "dreaming")
    code, _, err = run("handover", "--as", "b", "--session", "desk", "--root", str(root), "-",
                       stdin="Stopped here.\n")
    assert (code, err) == (0, "")
    assert status(run, root)[1] == "No status for b\n"
    assert '"dreaming"' in (logged()[-1] / "status").read_text()

    monkeypatch.setenv("LOBSTER_MAIL_NOW", "2026-10-10T10:10:00+01:00")
    take(run, root)
    assert status(run, root)[1] == "No status for b\n"
    status(run, root, "--session", "desk", "dormant")
    code, _, err = run("duty", "release", "--as", "b", "--session", "desk", "--root", str(root))
    assert (code, err) == (0, "")
    assert status(run, root)[1] == "No status for b\n"
    assert '"dormant"' in (logged()[-1] / "status").read_text()

    monkeypatch.setenv("LOBSTER_MAIL_NOW", "2026-10-10T10:20:00+01:00")
    take(run, root)
    status(run, root, "--session", "desk", "dormant")
    monkeypatch.setenv("LOBSTER_MAIL_NOW", "2026-10-10T11:20:00+01:00")
    _, out, _ = status(run, root)
    assert out.startswith('Status for b: "dormant"')
    take(run, root, session="laptop")
    _, out, _ = status(run, root, "--json")
    assert json.loads(out) == {"mailbox": "b", "holder": "laptop", "reported": None}
    assert len(logged()) == 3


def test_a_stale_duty_keeps_its_status_in_duty_status_all(run, root, two, monkeypatch):
    monkeypatch.setenv("LOBSTER_MAIL_NOW", "2026-10-10T08:00:00+01:00")
    take(run, root)
    status(run, root, "--session", "desk", "dormant")
    monkeypatch.setenv("LOBSTER_MAIL_NOW", "2026-10-10T12:00:00+01:00")
    entry = duty_json(run, root, "--all")["mailboxes"][1]
    assert entry["duty"]["stale"] is True
    assert entry["reported"] == {"status": "dormant", "set": "2026-10-10T07:00:00Z",
                                 "until": None}


def test_a_status_past_its_until_is_shown_as_it_was_set(run, root, two, monkeypatch):
    take(run, root)
    status(run, root, "--session", "desk", "dreaming", "--until", UNTIL)
    monkeypatch.setenv("LOBSTER_MAIL_NOW", "2026-10-10T13:00:00+01:00")
    _, out, _ = status(run, root)
    assert out == ('Status for b: "dreaming", set by desk at 2026-10-10T09:00:00Z, until '
                   '2026-10-10T10:30:00Z\n')
    assert duty_json(run, root, "--as", "b")["reported"]["until"] == UNTIL


def test_status_never_touches_a_message(run, root, mail_for_b):
    from conftest import every_file
    before = every_file(root)
    take(run, root)
    status(run, root, "--session", "desk", "dreaming")
    status(run, root)
    status(run, root, "--session", "desk", "--clear")
    assert every_file(root) == before


def test_help_lists_status_and_its_own_help_names_every_option(run):
    code, out, _ = run("--help")
    assert code == 0 and "status" in out.split("positional arguments")[1]
    code, out, _ = run("status", "--help")
    assert code == 0
    assert out.startswith("usage: lobster-mail status")
    for option in ("TEXT", "--session NAME", "--until TIME", "--clear", "--json", "--as ME"):
        assert option in out, option
