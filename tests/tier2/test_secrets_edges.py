"""secrets: the refusals and corners not met in the other files (Request 30 from bernstein; PLAN.md
"Settled" 70-73)."""
import os

from secrets_helpers import mode


def test_an_env_sh_it_may_not_read_is_exit_3(vault):
    folder = vault.make("google", "export A='1'\n", file_mode=0o000)
    try:
        code, _out, err = vault.run("check", "google", *vault.r)
    finally:
        os.chmod(folder / "env.sh", 0o600)
    assert code == 3
    assert err == "secrets: cannot read %s: Permission denied\n" % (folder / "env.sh")


def test_an_env_sh_that_is_not_utf_8_is_exit_3(vault):
    folder = vault.make("google", "")
    (folder / "env.sh").write_bytes(b"export A='\xff'\n")
    code, _out, err = vault.run("check", "google", *vault.r)
    assert (code, err) == (3, "secrets: %s is not UTF-8 text; fix it in an editor\n"
                           % (folder / "env.sh"))


def test_a_config_file_it_cannot_read_is_a_plain_error(vault):
    (vault.home / ".lobster-tools.conf").write_text("not a setting\n")
    code, _out, err = vault.run("list")
    assert code == 2
    assert err.startswith("secrets: %s/.lobster-tools.conf: line 1" % vault.home)


def test_init_and_set_take_one_set_not_a_name_and_a_folder(vault):
    code, _out, err = vault.run("init", "google", "--set-dir", str(vault.tmp / "x"), "--names",
                               "A", *vault.r)
    assert (code, err) == (2, "secrets: name one set, or give one --set-dir DIR, not both\n")
    assert vault.run("set", "--set-dir", "a", "--set-dir", "b", "A", "--stdin")[0] == 2


def test_check_and_set_refuse_a_bad_name(vault):
    vault.make("google", "export A='1'\n")
    assert vault.run("check", "google", "--need", "lower", *vault.r) == (
        2, "", "secrets: 'lower' is not a name\n")
    code, _out, err = vault.run("set", "google", "bad-name", "--stdin", *vault.r, stdin=b"v")
    assert code == 2 and "'bad-name' is not a name" in err


def test_no_verb_is_a_usage_error(vault):
    code, _out, err = vault.run()
    assert code == 2 and "name a verb" in err


def test_check_keeps_exit_3_when_a_later_set_has_an_empty_name(vault):
    vault.make("google", "export A=''\n")
    assert vault.run("check", "nothere", "google", *vault.r)[0] == 3
    assert vault.run("check", "nothere", "google", "--need", "B", *vault.r)[0] == 3


def test_run_passes_comments_and_blank_lines_by(vault, capfd):
    vault.make("google", "# note\n\nexport A_NAME='value-one'\n")
    stub = os.path.join(os.path.dirname(os.path.dirname(__file__)), "stubs", "secretstub")
    assert vault.run("run", "google", "--no-mask", *vault.r, "--", stub, "env", "A_NAME")[0] == 0
    assert capfd.readouterr().out == "A_NAME=value-one\n"


def test_set_says_so_when_it_cannot_even_look_at_env_sh(vault, monkeypatch):
    folder = vault.make("google", "export A='1'\n")
    real_stat = os.stat

    def failing(path, *rest, **kw):
        if str(path) == str(folder / "env.sh") and not kw and not rest:
            raise OSError(5, "Input/output error")
        return real_stat(path, *rest, **kw)

    from lobstertools import secrets
    monkeypatch.setattr(secrets.os, "stat", failing)
    code, _out, err = vault.run("set", "google", "A", "--stdin", *vault.r, stdin=b"v")
    assert code == 3 and "could not write %s: Input/output error" % (folder / "env.sh") in err
    monkeypatch.undo()
    assert mode(folder / "env.sh") == 0o600
