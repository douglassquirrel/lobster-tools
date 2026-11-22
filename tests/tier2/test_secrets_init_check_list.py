"""secrets init, check and list (Request 30 from bernstein; PLAN.md "Settled" 70-73)."""
from secrets_helpers import HOSTILE, mode


def test_init_makes_the_folder_700_and_env_sh_600_with_every_name_empty(vault):
    code, out, err = vault.run("init", "google", "--names", "G_ID", "G_SECRET", *vault.r)
    assert (code, err) == (0, "")
    folder = vault.root / "google"
    assert (mode(folder), mode(folder / "env.sh")) == (0o700, 0o600)
    assert (folder / "env.sh").read_text() == "export G_ID=''\nexport G_SECRET=''\n"
    assert out == "Made %s (700) and %s (600): G_ID G_SECRET\n" % (folder, folder / "env.sh")


def test_init_dry_run_writes_nothing(vault):
    code, out, err = vault.run("init", "google", "--names", "G_ID", "--dry-run", *vault.r)
    assert (code, err) == (0, "")
    assert out.startswith("Would make %s (700)" % (vault.root / "google"))
    assert list(vault.root.iterdir()) == []


def test_init_refuses_a_set_that_exists_and_writes_over_nothing(vault):
    vault.make("google", "export KEEP='it'\n")
    before = vault.files()
    code, out, err = vault.run("init", "google", "--names", "G_ID", *vault.r)
    assert (code, out) == (4, "")
    assert err == "secrets: %s already exists; nothing written\n" % (vault.root / "google")
    assert vault.files() == before


def test_init_refuses_bad_and_repeated_names(vault):
    assert vault.run("init", "google", "--names", "lower", *vault.r)[0] == 2
    assert vault.run("init", "google", "--names", "A", "A", *vault.r)[0] == 2
    assert vault.run("init", "../up", "--names", "A", *vault.r)[0] == 2
    assert vault.run("init", "google", *vault.r)[0] == 2
    assert list(vault.root.iterdir()) == []


def test_init_refuses_when_the_root_is_not_there_and_says_how_to_make_it(vault):
    missing = vault.tmp / "nowhere"
    code, _out, err = vault.run("init", "google", "--names", "A", "--root", str(missing))
    assert code == 3
    assert err == "secrets: no folder %s; make it with: mkdir -m 700 %s\n" % (missing, missing)


def test_init_in_a_folder_given_by_path(vault):
    target = vault.tmp / "old-secrets"
    code, _out, err = vault.run("init", "--set-dir", str(target), "--names", "A")
    assert (code, err) == (0, "")
    assert (target / "env.sh").read_text() == "export A=''\n"


def test_the_root_comes_from_the_environment_then_the_config_file(vault, monkeypatch):
    (vault.home / ".lobster-tools.conf").write_text("SECRETS_ROOT=%s\n" % vault.root)
    assert vault.run("init", "fromconf", "--names", "A")[0] == 0
    other = vault.tmp / "other"
    other.mkdir()
    monkeypatch.setenv("LOBSTER_SECRETS_ROOT", str(other))
    assert vault.run("init", "fromenv", "--names", "A")[0] == 0
    assert sorted(p.name for p in vault.root.iterdir()) == ["fromconf"]
    assert sorted(p.name for p in other.iterdir()) == ["fromenv"]


def test_no_root_anywhere_is_a_plain_error(vault):
    code, _out, err = vault.run("check", "google")
    assert code == 2
    assert "SECRETS_ROOT" in err and "--root" in err


def test_check_says_set_or_empty_for_each_name_and_never_the_value(vault):
    vault.make("google", "export G_ID='%s'\nexport G_SECRET=''\n" % HOSTILE.replace("'", "'\\''"))
    code, out, err = vault.run("check", "google", *vault.r)
    assert (code, err) == (1, "")
    assert out == "google (%s):\n  G_ID      set\n  G_SECRET  empty\n" % (vault.root / "google")
    assert "s3cr3t" not in out + err


def test_check_exits_0_when_every_name_is_set(vault):
    vault.make("google", "export G_ID='abc'\n")
    assert vault.run("check", "google", *vault.r)[0] == 0


def test_check_need_counts_only_the_names_needed_and_says_missing(vault):
    vault.make("google", "export G_ID='abc'\nexport SPARE=''\n")
    assert vault.run("check", "google", "--need", "G_ID", *vault.r)[0] == 0
    code, out, _err = vault.run("check", "google", "--need", "G_ID", "G_TOKEN", *vault.r)
    assert code == 1
    assert out.endswith("G_TOKEN  missing (in none of the sets)\n")


def test_check_need_is_met_by_any_of_several_sets(vault):
    vault.make("google", "export G_ID='abc'\n")
    vault.make("dropbox", "export D_TOKEN='xyz'\n")
    code, out, err = vault.run("check", "google", "dropbox", "--need", "G_ID", "D_TOKEN", *vault.r)
    assert (code, err) == (0, "")
    assert "missing" not in out


def test_check_says_so_when_the_file_or_folder_is_open_to_others(vault):
    vault.make("google", "export G_ID='abc'\n", folder_mode=0o755, file_mode=0o644)
    code, out, _err = vault.run("check", "google", *vault.r)
    assert code == 6
    folder = vault.root / "google"
    assert "  unsafe: %s is mode 755; make it private with: chmod 700 %s\n" % (folder, folder) in out
    env = folder / "env.sh"
    assert "  unsafe: %s is mode 644; make it private with: chmod 600 %s\n" % (env, env) in out


def test_check_says_so_when_the_set_is_inside_a_git_working_tree(vault):
    repo = vault.tmp / "repo"
    (repo / ".git").mkdir(parents=True)
    folder = repo / "secrets-here"
    vault.run("init", "--set-dir", str(folder), "--names", "A")
    code, out, _err = vault.run("check", "--set-dir", str(folder))
    assert code == 1
    assert "  unsafe: %s is inside the git working tree %s\n" % (folder, repo) in out


def test_check_a_set_that_is_not_there_is_exit_3(vault):
    vault.make("google", "export G_ID='abc'\n")
    code, out, err = vault.run("check", "google", "dropbox", *vault.r)
    assert code == 3
    assert err == "secrets: no set dropbox: no file %s\n" % (vault.root / "dropbox" / "env.sh")
    assert "google (" in out


def test_check_a_line_it_cannot_read_names_the_number_never_the_text(vault):
    vault.make("google", "export G_ID='abc'\nexport BAD=$(%s)\n" % HOSTILE.replace("'", ""))
    code, out, err = vault.run("check", "google", *vault.r)
    assert code == 3
    env = vault.root / "google" / "env.sh"
    assert err == ("secrets: line 2 of %s is not a line of the form export NAME='value'; "
                   "fix it in an editor\n" % env)
    assert "s3cr3t" not in out + err


def test_check_only_reads(vault):
    vault.make("google", "export G_ID='abc'\n", file_mode=0o644)
    before = vault.files()
    modes = mode(vault.root / "google" / "env.sh")
    vault.run("check", "google", *vault.r)
    assert vault.files() == before and mode(vault.root / "google" / "env.sh") == modes


def test_list_prints_each_set_and_its_names_only(vault):
    vault.make("google", "export G_ID='%s'\nexport G_SECRET=''\n" % "abcdefgh")
    vault.make("dropbox", "export D_TOKEN='zyxwvuts'\n", file_mode=0o644)
    (vault.root / "stray").mkdir()
    code, out, err = vault.run("list", *vault.r)
    assert (code, err) == (0, "")
    assert out == ("dropbox: D_TOKEN (unsafe)\n"
                   "google: G_ID G_SECRET\n"
                   "stray: (no env.sh)\n")


def test_list_an_empty_root_and_a_missing_one(vault):
    assert vault.run("list", *vault.r) == (0, "No sets in %s\n" % vault.root, "")
    assert vault.run("list", "--root", str(vault.tmp / "none"))[0] == 3


def test_list_names_a_set_it_cannot_read_by_line_number(vault):
    vault.make("google", "export G_ID=$X\n")
    assert vault.run("list", *vault.r) == (0, "google: (cannot read line 1)\n", "")


def test_help_names_every_verb(vault):
    code, out, _err = vault.run("--help")
    assert code == 0
    for verb in ("init", "set", "check", "run", "list"):
        assert verb in out
