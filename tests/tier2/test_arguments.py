VERBS = ["init", "send", "reply", "check", "list", "read", "ack", "done", "thread", "watch", "duty"]


def test_help_lists_every_verb(run):
    code, out, err = run("--help")
    assert code == 0
    for verb in VERBS:
        assert verb in out, verb


def test_each_verb_has_its_own_help(run):
    for verb in VERBS:
        code, out, _ = run(verb, "--help")
        assert code == 0, verb
        assert "usage: lobster-mail " + verb in out


def test_no_verb_is_a_usage_error(run):
    code, out, err = run()
    assert code == 2
    assert "usage" in err.lower()


def test_unknown_verb_is_refused(run):
    code, _, err = run("frobnicate")
    assert code == 2
    assert "frobnicate" in err


def test_send_without_as_names_the_missing_flag(run, root):
    code, _, err = run("send", "--root", str(root), "--to", "b", "--subject", "s", "body.md")
    assert code == 2
    assert "--as" in err and "LOBSTER_MAIL_AS" in err
