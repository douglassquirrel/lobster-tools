"""secrets set (Request 30 from bernstein; PLAN.md "Settled" 70-73)."""
import os
import subprocess

from secrets_helpers import HOSTILE, mode

from lobstertools import secrets

BEFORE = "# a note\nexport G_ID='keep-me'\nexport G_TOKEN=''\n\nexport G_LAST=\"x\"\n"


def asker(value, seen):
    def ask(prompt):
        seen.append(prompt)
        return value
    return ask


def test_set_asks_on_the_terminal_and_replaces_only_that_line(vault):
    folder = vault.make("google", BEFORE)
    seen = []
    code, out, err = vault.run("set", "google", "G_TOKEN", *vault.r, tty=True,
                               ask=asker(HOSTILE, seen))
    assert (code, err) == (0, "")
    assert out == "G_TOKEN set in google (it was empty, %d characters)\n" % len(HOSTILE)
    assert seen == ["Value for G_TOKEN in google (not shown): "]
    after = (folder / "env.sh").read_text(encoding="utf-8")
    assert after == BEFORE.replace("export G_TOKEN=''\n", secrets.env_line("G_TOKEN", HOSTILE))
    assert mode(folder / "env.sh") == 0o600
    assert "s3cr3t" not in out + err


def test_set_says_replaced_when_there_was_a_value(vault):
    vault.make("google", BEFORE)
    code, out, _err = vault.run("set", "google", "G_ID", *vault.r, tty=True,
                               ask=asker("new-value", []))
    assert (code, out) == (0, "G_ID set in google (replaced, 9 characters; was 7)\n")


def test_set_keeps_a_mode_it_finds_and_says_it_is_unsafe(vault):
    folder = vault.make("google", BEFORE, file_mode=0o640)
    code, out, _err = vault.run("set", "google", "G_ID", *vault.r, tty=True,
                               ask=asker("new-value", []))
    assert code == 0
    assert mode(folder / "env.sh") == 0o640
    assert "unsafe: %s is mode 640" % (folder / "env.sh") in out


def test_set_reads_standard_input_with_stdin_dropping_one_final_newline(vault):
    folder = vault.make("google", BEFORE)
    code, _out, err = vault.run("set", "google", "G_TOKEN", "--stdin", *vault.r,
                               stdin=(HOSTILE + "\n").encode())
    assert (code, err) == (0, "")
    assert secrets.env_line("G_TOKEN", HOSTILE) in (folder / "env.sh").read_text(encoding="utf-8")


def test_set_refuses_with_no_terminal_and_no_stdin_flag(vault):
    vault.make("google", BEFORE)
    before = vault.files()
    code, _out, err = vault.run("set", "google", "G_TOKEN", *vault.r, stdin=b"piped\n")
    assert code == 2
    assert err == ("secrets: no terminal to ask on; give --stdin to read the value from "
                   "standard input\n")
    assert vault.files() == before


def test_set_refuses_a_name_the_set_lacks_unless_add(vault):
    folder = vault.make("google", BEFORE)
    before = vault.files()
    code, out, err = vault.run("set", "google", "NEW_ONE", "--stdin", *vault.r, stdin=b"v")
    assert code == 4
    assert err == "secrets: google has no NEW_ONE; give --add to add it\n"
    assert vault.files() == before
    code, out, err = vault.run("set", "google", "NEW_ONE", "--stdin", "--add", *vault.r,
                               stdin=b"v1")
    assert (code, out) == (0, "NEW_ONE set in google (added, 2 characters)\n")
    assert (folder / "env.sh").read_text() == BEFORE + "export NEW_ONE='v1'\n"


def test_set_adds_a_newline_before_an_added_line_when_the_file_lacks_one(vault):
    folder = vault.make("google", "export A='1'")
    vault.run("set", "google", "B", "--stdin", "--add", *vault.r, stdin=b"2")
    assert (folder / "env.sh").read_text() == "export A='1'\nexport B='2'\n"


def test_set_refuses_an_empty_value_a_newline_or_a_nul(vault):
    vault.make("google", BEFORE)
    before = vault.files()
    for value in (b"", b"\n", b"two\nlines", b"nul\x00here", b"cr\rhere"):
        code, _out, err = vault.run("set", "google", "G_ID", "--stdin", *vault.r, stdin=value)
        assert code == 2, value
        assert "nothing changed" in err
    assert vault.files() == before


def test_set_refuses_a_value_that_is_not_utf_8(vault):
    vault.make("google", BEFORE)
    assert vault.run("set", "google", "G_ID", "--stdin", *vault.r, stdin=b"\xff\xfe")[0] == 2


def test_set_dry_run_asks_nothing_and_writes_nothing(vault):
    vault.make("google", BEFORE)
    before = vault.files()
    code, out, err = vault.run("set", "google", "G_TOKEN", "--dry-run", *vault.r, tty=True,
                               ask=asker("never", []))
    assert (code, out, err) == (0, "Would set G_TOKEN in google (it is empty)\n", "")
    assert vault.files() == before


def test_set_on_a_set_that_is_not_there_or_unreadable(vault):
    assert vault.run("set", "google", "A", "--stdin", *vault.r, stdin=b"v")[0] == 3
    vault.make("bad", "export A=$X\n")
    assert vault.run("set", "bad", "A", "--stdin", *vault.r, stdin=b"v")[0] == 3


def test_set_writes_the_value_nowhere_but_env_sh(vault):
    folder = vault.make("google", BEFORE)
    vault.run("set", "google", "G_TOKEN", "--stdin", *vault.r, stdin=HOSTILE.encode())
    # env.sh holds the value with its quote escaped, so look for the part before the quote
    holding = [p for p, data in vault.files().items() if b"s3cr3t-$" in data]
    assert holding == [os.path.relpath(folder / "env.sh", vault.tmp)]
    assert sorted(os.listdir(folder)) == ["env.sh"]


def test_set_leaves_env_sh_as_it_was_when_the_write_fails(vault, monkeypatch):
    folder = vault.make("google", BEFORE)
    before = vault.files()

    def broken(source, target):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(secrets.os, "replace", broken)
    code, _out, err = vault.run("set", "google", "G_TOKEN", "--stdin", *vault.r, stdin=b"value")
    assert code == 3
    assert err.startswith("secrets: could not write %s: No space left on device" % (folder / "env.sh"))
    assert (folder / "env.sh").read_text() == BEFORE
    assert set(vault.files()) >= set(before)


def test_a_shell_reads_back_exactly_what_set_wrote(vault):
    folder = vault.make("google", BEFORE)
    vault.run("set", "google", "G_TOKEN", "--stdin", *vault.r, stdin=HOSTILE.encode())
    shown = subprocess.run(["/bin/sh", "-c", '. "$1"; printf %s "$G_TOKEN"', "sh",
                            str(folder / "env.sh")], capture_output=True, check=True)
    assert shown.stdout.decode("utf-8") == HOSTILE


def test_set_says_how_long_an_added_value_is_in_characters_not_bytes(vault):
    vault.make("google", BEFORE)
    code, out, _err = vault.run("set", "google", "G_NEW", "--add", *vault.r, tty=True,
                               ask=asker("caf\u00e9-\u00e9t\u00e9", []))
    assert (code, out) == (0, "G_NEW set in google (added, 8 characters)\n")


def test_set_says_the_lengths_for_a_value_read_with_stdin(vault):
    vault.make("google", BEFORE)
    code, out, _err = vault.run("set", "google", "G_ID", "--stdin", *vault.r,
                               stdin=b"x" * 100 + b"\n")
    assert (code, out) == (0, "G_ID set in google (replaced, 100 characters; was 7)\n")


def test_set_min_length_refuses_a_shorter_value_and_writes_nothing(vault):
    vault.make("google", BEFORE)
    before = vault.files()
    code, out, err = vault.run("set", "google", "G_ID", "--stdin", "--min-length", "1000",
                               *vault.r, stdin=b"x" * 100)
    assert (code, out) == (2, "")
    assert err == ("secrets: the value is 100 characters, fewer than --min-length 1000; "
                   "nothing changed\n")
    assert vault.files() == before


def test_set_min_length_takes_a_value_of_exactly_that_length(vault):
    vault.make("google", BEFORE)
    code, out, _err = vault.run("set", "google", "G_ID", "--min-length", "5", *vault.r,
                               tty=True, ask=asker("12345", []))
    assert (code, out) == (0, "G_ID set in google (replaced, 5 characters; was 7)\n")


def test_set_min_length_must_be_a_whole_number_of_at_least_one(vault):
    vault.make("google", BEFORE)
    for bad in ("0", "-3", "many"):
        code, out, err = vault.run("set", "google", "G_ID", "--stdin", "--min-length", bad,
                                   *vault.r, stdin=b"value")
        assert (code, out) == (2, "")
        assert "--min-length" in err and "at least 1" in err, err
