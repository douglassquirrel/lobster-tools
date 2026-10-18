"""The routine each pace prints, in the wording Squirrel approved on 18 October 2026 (PLAN.md "A
mail pace setting"). At normal, or with no setting, nothing prints differently from before."""

MEANING = {
    "eager": (
        "eager: keep watching all the time and report new mail at once, even in the middle of a task.\n"
        "  Claude Code: keep wait running in the background. Without a background wait: checkin after\n"
        "  every step, and when idle one scheduled check-in 5 minutes ahead, each scheduling the next.\n"),
    "normal": (
        "normal: keep watching and report new mail at the next pause in the work.\n"
        "  Claude Code: keep wait running in the background. Without a background wait: checkin between\n"
        "  steps, and when idle one scheduled check-in 15 minutes ahead, each scheduling the next.\n"),
    "relaxed": (
        "relaxed: keep no watch running. Check once at the end of each turn, when it is the person's turn\n"
        "  to type, and at the start and end of the session. Claude Code: do not run wait. Without a\n"
        "  background wait: no check-ins during work and none scheduled.\n"),
}
STOP = ("Now: stop watching. Claude Code: when the running wait returns, do not run it again. Without a\n"
        "  background wait: do not schedule the next check-in, and cancel one already scheduled if you can.\n")
START = ("Now: start watching. Claude Code: run lobster-mail wait --as a --session NAME in the background.\n"
         "  Without a background wait: schedule one check-in %d minutes from now.\n")
SWITCH = ("Now: Claude Code: the running wait returns with exit 6 to say the pace changed; run it again.\n"
          "  Without a background wait: schedule the next check-in %d minutes from now instead.\n")


def pace(run, root, *argv):
    code, out, err = run("pace", *argv, "--as", "a", "--root", str(root))
    assert (code, err) == (0, ""), argv
    return out


def test_pace_shows_the_meaning_of_the_level_in_force(run, root, two):
    assert pace(run, root) == ("Pace for a: normal (nothing set; normal is the default)\n"
                               + MEANING["normal"])
    for level in ("eager", "relaxed", "normal"):
        pace(run, root, level)
        assert pace(run, root) == "Pace for a: %s\n" % level + MEANING[level]


def test_a_change_of_pace_says_what_to_do_now(run, root, two):
    assert pace(run, root, "relaxed") == ("Pace for a set to relaxed (was normal)\n"
                                          + MEANING["relaxed"] + STOP)
    assert pace(run, root, "eager") == ("Pace for a set to eager (was relaxed)\n"
                                        + MEANING["eager"] + START % 5)
    assert pace(run, root, "normal") == ("Pace for a set to normal (was eager)\n"
                                         + MEANING["normal"] + SWITCH % 15)
    assert pace(run, root, "relaxed") == ("Pace for a set to relaxed (was normal)\n"
                                          + MEANING["relaxed"] + STOP)
    assert pace(run, root, "normal") == ("Pace for a set to normal (was relaxed)\n"
                                         + MEANING["normal"] + START % 15)
    assert pace(run, root, "eager") == ("Pace for a set to eager (was normal)\n"
                                        + MEANING["eager"] + SWITCH % 5)


def test_setting_the_level_already_in_force_says_nothing_to_do(run, root, two):
    assert pace(run, root, "normal") == ("Pace for a set to normal (was normal)\n"
                                         + MEANING["normal"])


STEP3 = {
    "eager": (
        "3. The pace is eager: watch all the time and report new mail at once, even in the middle of a\n"
        "   task. Keep this running as a background command, and run it again each time it returns:\n"
        "   lobster-mail wait --as a --session NAME\n"
        "   When it returns with mail: ack it and report it at once, act on it only as your project's\n"
        "   rules allow, and wait again.\n"
        "   A session that cannot run a background command checks in after every step of work, and\n"
        "   when idle schedules one check-in 5 minutes ahead, each check-in scheduling the next:\n"
        "   lobster-mail checkin --as a --session NAME\n"),
    "relaxed": (
        "3. The pace is relaxed: keep no watch running, in the background or by scheduled check-ins.\n"
        "   Instead check once at the end of each turn, when it is the person's turn to type:\n"
        "   lobster-mail checkin --as a --session NAME\n"
        "   When it lists mail: ack it, report it, and act on it only as your project's rules allow.\n"),
}
NORMAL_STEP3 = ("3. Then watch, as a background command that returns when mail arrives or the wait "
                "times out:\n")


def start(run, root):
    code, out, err = run("start", "--as", "a", "--root", str(root))
    assert (code, err) == (0, "")
    return out


def test_start_gives_step_3_for_the_pace(run, root, two):
    for level in ("eager", "relaxed"):
        pace(run, root, level)
        out = start(run, root)
        assert "\n" + STEP3[level] + "4. Before the session ends:" in out, level
        assert NORMAL_STEP3 not in out, level


def test_at_normal_or_with_a_broken_pace_file_start_prints_what_it_did_before(run, root, two):
    before = start(run, root)
    assert NORMAL_STEP3 in before
    pace(run, root, "normal")
    assert start(run, root) == before
    (root / "a" / "pace").write_text("fast\n")
    assert start(run, root) == before


EAGER_ARRIVED = ("Mail has arrived for a: claim it with ack and report it at once, even in the middle "
                 "of a task; act on it only as your project's rules allow (by default, only with the "
                 "OK of the person you work for), then %s again.")
RELAXED_WAIT = ("The pace for a is relaxed: the routine is checkin at the end of each turn, not wait; "
                "watching anyway, since wait was run.")


def drop_mail(root):
    (root / "a" / "new" / "dropped.md").write_bytes(b"hello\n")


def test_at_eager_wait_and_checkin_say_to_report_at_once(run, root, two):
    pace(run, root, "eager")
    drop_mail(root)
    for argv, again in ((("wait",), "wait"), (("checkin",), "check in")):
        code, out, err = run(*argv, "--as", "a", "--session", "desk-1", "--root", str(root))
        assert (code, err) == (0, ""), argv
        assert out.rstrip().endswith(EAGER_ARRIVED % again), argv


def test_checkin_with_nothing_new_says_when_to_look_again_for_the_pace(run, root, two):
    expected = {"eager": "No new mail for a; check in again after the next step, or in about 5 "
                         "minutes if idle",
                "relaxed": "No new mail for a; check again at the end of the next turn",
                "normal": "No new mail for a; check in again later"}
    for level, text in expected.items():
        pace(run, root, level)
        code, _, err = run("checkin", "--as", "a", "--session", "desk-1", "--root", str(root))
        assert (code, err) == (5, "lobster-mail checkin: %s\n" % text), level


def test_at_relaxed_wait_says_so_first_then_watches_anyway(run, root, two):
    pace(run, root, "relaxed")
    drop_mail(root)
    code, out, err = run("wait", "--as", "a", "--session", "desk-1", "--root", str(root))
    assert (code, err) == (0, "")
    lines = out.splitlines()
    assert lines[0] == RELAXED_WAIT
    assert lines[1] == "Duty for a taken by desk-1 at 2026-10-10T09:00:00Z"
    assert lines[2].startswith("dropped  (no headers)")
    code, out, _ = run("wait", "--as", "a", "--session", "desk-1", "--json", "--root", str(root))
    assert code == 0 and out.startswith("{")


def test_at_normal_wait_and_checkin_print_what_they_did_before(run, root, two):
    drop_mail(root)
    run("duty", "take", "--as", "a", "--session", "desk-1", "--root", str(root))
    argvs = [("wait", "--as", "a", "--session", "desk-1", "--root", str(root)),
             ("checkin", "--as", "a", "--session", "desk-1", "--root", str(root))]
    before = [run(*argv) for argv in argvs]
    pace(run, root, "normal")
    assert [run(*argv) for argv in argvs] == before
