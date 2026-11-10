"""A session that takes up its own name's duty is told when the duty still carries a status, and
nothing is cleared (PLAN.md "Telling a session its duty still carries a status")."""
import json

UNTIL = "2026-10-10T10:30:00Z"


def take(run, root, *extra, session="mac"):
    return run("duty", "take", "--as", "b", "--session", session, "--root", str(root), *extra)


def set_status(run, root, text, *extra):
    code, _, err = run("status", "--as", "b", "--session", "mac", "--root", str(root), text,
                       *extra)
    assert code == 0, err


def shown(run, root):
    return run("status", "--as", "b", "--root", str(root))[1]


def carries(text, until=""):
    return ('It carries the status "%s", set at 2026-10-10T09:00:00Z%s; if that is no longer true '
            "(this session has taken up an earlier session's duty, for one), clear it: "
            "lobster-mail status --as b --session mac --clear\n" % (text, until))


ALREADY = ("mac is already on duty for b since 2026-10-10T09:00:00Z; heartbeat refreshed to "
           "2026-10-10T09:00:00Z\n")


def test_duty_take_by_its_own_name_says_the_duty_carries_a_status_and_keeps_it(run, root, two):
    take(run, root)
    set_status(run, root, "dormant", "--until", UNTIL)
    before = shown(run, root)
    code, out, err = take(run, root)
    assert (code, err) == (0, "")
    assert out == ALREADY + carries("dormant", " (until 2026-10-10T10:30:00Z)")
    assert shown(run, root) == before


def test_the_same_when_the_duty_is_stale(run, root, two, monkeypatch):
    take(run, root)
    set_status(run, root, "dreaming")
    monkeypatch.setenv("LOBSTER_MAIL_NOW", "2026-10-10T12:00:00+01:00")
    code, out, _ = take(run, root)
    assert code == 0
    assert out == ("mac is already on duty for b since 2026-10-10T09:00:00Z; heartbeat refreshed "
                   "to 2026-10-10T11:00:00Z\n" + carries("dreaming"))
    assert shown(run, root).startswith('Status for b: "dreaming"')


def test_with_no_status_or_a_cleared_one_the_output_is_as_before(run, root, two):
    take(run, root)
    assert take(run, root)[1] == ALREADY
    set_status(run, root, "dormant")
    run("status", "--as", "b", "--session", "mac", "--clear", "--root", str(root))
    assert take(run, root)[1] == ALREADY


def test_hostile_status_text_is_shown_in_the_line_as_set(run, root, two):
    take(run, root)
    text = "q \"x\" $(y) `z` \\ café 日本"
    set_status(run, root, text)
    assert take(run, root)[1] == ALREADY + carries(text)


def test_duty_take_json_carries_reported_or_null(run, root, two, monkeypatch):
    code, out, _ = take(run, root, "--json")
    assert code == 0 and json.loads(out)["reported"] is None
    set_status(run, root, "dormant")
    _, out, _ = take(run, root, "--json")
    assert json.loads(out) == {
        "mailbox": "b", "holder": "mac", "since": "2026-10-10T09:00:00Z",
        "last_beat": "2026-10-10T09:00:00Z", "action": "refreshed",
        "reported": {"status": "dormant", "set": "2026-10-10T09:00:00Z", "until": None}}
    monkeypatch.setenv("LOBSTER_MAIL_NOW", "2026-10-10T12:00:00+01:00")
    _, out, _ = take(run, root, "--json", session="laptop")
    taken = json.loads(out)
    assert taken["action"] == "taken" and taken["reported"] is None


def watch(run, root, verb, *extra):
    argv = [verb, "--as", "b", "--session", "mac", "--root", str(root), *extra]
    if verb == "wait":
        argv += ["--timeout", "1", "--every", "1"]
    return run(*argv)


def test_wait_and_checkin_print_the_line_and_keep_the_status(run, root, mail_for_b):
    take(run, root)
    set_status(run, root, "dormant")
    for verb in ("wait", "checkin"):
        code, out, _ = watch(run, root, verb)
        assert code == 0, verb
        assert out.startswith(ALREADY + carries("dormant")), verb
    assert shown(run, root).startswith('Status for b: "dormant"')


def test_checkin_with_nothing_new_still_says_so(run, root, two):
    take(run, root)
    set_status(run, root, "dreaming")
    code, out, _ = watch(run, root, "checkin")
    assert code == 5
    assert out == ALREADY + carries("dreaming")


def test_wait_and_checkin_json_carry_reported_or_null(run, root, mail_for_b):
    for verb in ("wait", "checkin"):
        _, out, _ = watch(run, root, verb, "--json")
        assert json.loads(out)["reported"] is None, verb
    set_status(run, root, "dormant")
    for verb in ("wait", "checkin"):
        _, out, _ = watch(run, root, verb, "--json")
        assert json.loads(out)["reported"] == {
            "status": "dormant", "set": "2026-10-10T09:00:00Z", "until": None}, verb
