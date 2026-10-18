"""pace: how eager a mailbox's sessions are about mail. One file, <ME>/pace; none means normal."""


def test_pace_with_no_setting_is_normal_and_writes_nothing(run, root, two):
    code, out, err = run("pace", "--as", "a", "--root", str(root))
    assert (code, err) == (0, "")
    assert out.splitlines()[0] == "Pace for a: normal (nothing set; normal is the default)"
    assert not (root / "a" / "pace").exists()


def test_each_level_is_set_then_shown_and_the_file_holds_just_the_level(run, root, two):
    was = "normal"
    for level in ("eager", "relaxed", "normal"):
        code, out, err = run("pace", level, "--as", "a", "--root", str(root))
        assert (code, err) == (0, ""), level
        assert out.splitlines()[0] == "Pace for a set to %s (was %s)" % (level, was)
        assert (root / "a" / "pace").read_text() == level + "\n"
        code, out, _ = run("pace", "--as", "a", "--root", str(root))
        assert out.splitlines()[0] == "Pace for a: %s" % level
        was = level
    assert sorted(p.name for p in (root / "a").iterdir()) == [
        "done", "new", "open", "pace", "sent", "tmp"]


def test_an_unknown_empty_or_hostile_level_exits_2_and_leaves_the_setting_alone(run, root, two):
    run("pace", "relaxed", "--as", "a", "--root", str(root))
    before = (root / "a" / "pace").read_bytes()
    for bad in ("fast", "", "Eager", "eager; rm -rf /", "$(x)", "</script>", "café", "normal\n"):
        code, out, err = run("pace", bad, "--as", "a", "--root", str(root))
        assert (code, out) == (2, ""), bad
        assert "eager, normal or relaxed" in err, bad
        assert (root / "a" / "pace").read_bytes() == before, bad
    assert sorted(p.name for p in (root / "a").iterdir()) == [
        "done", "new", "open", "pace", "sent", "tmp"]


def test_pace_writes_nothing_but_its_own_mailboxs_pace_file(run, root, mail_for_b):
    from test_duty_all import snapshot
    run("duty", "take", "--as", "b", "--session", "desk-1", "--root", str(root))
    before = snapshot(root)
    run("pace", "eager", "--as", "b", "--root", str(root))
    after = snapshot(root)
    assert after.pop("b/pace") == b"eager\n"
    assert after == before


def test_a_pace_file_that_holds_no_level_is_reported_with_exit_5(run, root, two):
    (root / "a" / "pace").write_text("fast\n")
    code, out, err = run("pace", "--as", "a", "--root", str(root))
    assert (code, out) == (5, "")
    assert err == ("lobster-mail pace: the pace file of a holds 'fast', which is not a level; set "
                   "one with lobster-mail pace --as a normal (or eager, or relaxed)\n")
    code, out, err = run("pace", "eager", "--as", "a", "--root", str(root))
    assert (code, err) == (0, "")
    assert out.splitlines()[0] == "Pace for a set to eager (was 'fast', not a level)"


def test_json_shows_and_sets_the_pace(run, root, two):
    import json
    code, out, err = run("pace", "--as", "a", "--json", "--root", str(root))
    assert (code, err) == (0, "")
    assert json.loads(out) == {"mailbox": "a", "pace": "normal", "set": False}
    code, out, err = run("pace", "relaxed", "--as", "a", "--json", "--root", str(root))
    assert json.loads(out) == {"mailbox": "a", "pace": "relaxed", "was": "normal"}
    code, out, err = run("pace", "--as", "a", "--json", "--root", str(root))
    assert json.loads(out) == {"mailbox": "a", "pace": "relaxed", "set": True}


def fake_clock(monkeypatch, on_sleep):
    from lobstertools import mail
    clock = {"t": 0.0, "sleeps": 0}

    def sleep(seconds):
        clock["t"] += seconds
        clock["sleeps"] += 1
        on_sleep(clock["sleeps"])

    monkeypatch.setattr(mail.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(mail.time, "sleep", sleep)
    return clock


def test_an_armed_wait_returns_with_exit_6_when_the_pace_changes(run, root, two, monkeypatch):
    def on_sleep(n):
        if n == 2:
            (root / "a" / "pace").write_text("relaxed\n")
    clock = fake_clock(monkeypatch, on_sleep)
    code, out, err = run("wait", "--as", "a", "--session", "desk-1", "--every", "5",
                         "--root", str(root))
    assert code == 6 and clock["sleeps"] == 2
    assert out == "Duty for a taken by desk-1 at 2026-10-10T09:00:00Z\n"
    assert err == ("lobster-mail wait: the pace for a changed from normal to relaxed while "
                   "watching; run lobster-mail pace --as a and follow what it says\n")


def test_mail_that_arrives_with_a_pace_change_is_reported_first(run, root, two, monkeypatch):
    def on_sleep(n):
        (root / "a" / "pace").write_text("eager\n")
        (root / "a" / "new" / "dropped.md").write_bytes(b"hello\n")
    fake_clock(monkeypatch, on_sleep)
    code, out, _ = run("wait", "--as", "a", "--session", "desk-1", "--root", str(root))
    assert code == 0 and "dropped  (no headers)" in out
