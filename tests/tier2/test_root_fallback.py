"""The mail root: when nothing names it, $HOME/mnt/mail is used if it is a folder (the device
shell, where the mail folder is connected on its own)."""


def test_root_falls_back_to_home_mnt_mail_when_nothing_is_configured(run, tmp_path):
    mount = tmp_path / "home" / "mnt" / "mail"
    mount.mkdir(parents=True)
    code, out, err = run("init", "a")
    assert code == 0, err
    assert "Made mailbox a in %s:" % mount in out
    code, out, err = run("check", "--as", "a")
    assert code == 0, err
    assert "No new mail for a" in out


def test_the_no_root_error_names_the_fallback(run, tmp_path):
    code, out, err = run("check", "--as", "a")
    assert code == 2 and out == ""
    assert ("no mail root: give --root DIR, or set LOBSTER_MAIL_ROOT, or put "
            "MAIL_ROOT=~/projects/mail in ~/.lobster-tools.conf (or connect the mail folder so "
            "that ~/mnt/mail exists)") in err
