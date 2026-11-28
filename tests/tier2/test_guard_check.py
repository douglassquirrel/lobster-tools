"""script-guard --check: the verdict for one command, by hand, logging nothing; and a usage error
never refuses (exit 0), so a hook set up wrongly cannot stop every command."""


def test_check_prints_refused_and_the_reason_and_exits_2(desk):
    assert desk.call("--check", "sleep 1", "--kind", "non-code") == (2, "refused: sleep\n", "")


def test_check_prints_allowed_and_exits_0(desk):
    assert desk.call("--check", "git status", "--kind", "non-code") == (0, "allowed\n", "")
    assert desk.call("--check", "for x in y; do :; done", "--kind", "code") == (0, "allowed\n", "")


def test_check_takes_the_kind_from_the_projects_lobster_conf(desk, monkeypatch):
    pond = desk.ganglion()
    assert desk.call("--check", "sleep 1", "--project", str(pond))[0] == 2
    monkeypatch.chdir(pond)
    assert desk.call("--check", "python3 -c 1") == (2, "refused: an interpreter (python3)\n", "")
    assert desk.call("--check", "python3 -c 1", "--kind", "code") == (
        2, "refused: an inline program (python3 -c)\n", "")


def test_check_says_why_it_allows_in_a_project_where_nothing_is_refused(desk):
    bare, feeler = desk.project("bare", None), desk.project("feel", "KIND=feeler\n")
    assert desk.call("--check", "sleep 1", "--project", str(bare)) == (
        0, "allowed (no lobster.conf in %s: script-guard refuses nothing there)\n" % bare, "")
    assert desk.call("--check", "sleep 1", "--project", str(feeler)) == (
        0, "allowed (KIND=feeler: script-guard refuses nothing there)\n", "")


def test_check_says_when_it_cannot_read_the_command(desk):
    assert desk.call("--check", "echo 'x", "--kind", "non-code") == (
        0, "allowed (cannot read it: a ' is not closed)\n", "")


def test_check_logs_nothing(desk):
    desk.call("--check", "sleep 1", "--project", str(desk.ganglion()))
    assert desk.log("pond") is None


def test_a_usage_error_allows_with_one_line_and_judges_nothing(desk):
    for argv in (["--check"], ["--kind", "banana", "--check", "sleep 1"], ["sleep 1"]):
        code, out, err = desk.call(*argv)
        assert (code, out) == (0, ""), argv
        assert err.startswith("script-guard: ") and err.endswith("; nothing judged\n"), err


def test_help_says_how_it_is_used(desk):
    code, out, _ = desk.call("--help")
    assert code == 0
    assert out.startswith("usage: script-guard [-h] [--check COMMAND [--kind {non-code,code}] "
                          "[--project DIR]]")
    assert "PreToolUse" in out
