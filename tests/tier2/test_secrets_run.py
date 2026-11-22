"""secrets run (Request 30 from bernstein; PLAN.md "Settled" 70-73). Called in-process; the command
it runs is the stand-in tests/stubs/secretstub, by its full path. Two tests start secrets itself as
a program."""
import pathlib
import subprocess
import sys

from secrets_helpers import HOSTILE

from lobstertools import secrets

CHECKOUT = pathlib.Path(__file__).resolve().parents[2]
STUB = str(CHECKOUT / "tests" / "stubs" / "secretstub")
COMMAND = CHECKOUT / "secrets"
VALUE = "tok-%s-1234" % HOSTILE.replace("'", "")


def quoted(value):
    return value.replace("'", "'\\''")


def sets(vault):
    vault.make("one", "export ONE_A='%s'\nexport ONE_EMPTY=''\n" % quoted(VALUE))
    vault.make("two", "export TWO_A='second-set-value'\n")


def test_gives_the_command_its_sets_variables_and_none_from_another_set(vault, capfd):
    sets(vault)
    code, out, err = vault.run("run", "one", *vault.r, "--", STUB, "env", "ONE_A", "ONE_EMPTY",
                               "TWO_A")
    assert (code, out, err) == (0, "", "")
    seen = capfd.readouterr()
    assert seen.out == "ONE_A=[secret]\nONE_EMPTY=\nTWO_A unset\n"


def test_two_sets_together(vault, capfd):
    sets(vault)
    vault.run("run", "one", "two", *vault.r, "--no-mask", "--", STUB, "env", "TWO_A")
    assert capfd.readouterr().out == "TWO_A=second-set-value\n"


def test_masks_values_on_both_streams(vault, capfd):
    sets(vault)
    assert vault.run("run", "one", *vault.r, "--", STUB, "leak", "ONE_A")[0] == 0
    seen = capfd.readouterr()
    assert (seen.out, seen.err) == ("out:[secret]\n", "err:[secret]\n")


def test_no_mask_passes_the_output_as_it_is(vault, capfd):
    sets(vault)
    assert vault.run("run", "one", *vault.r, "--no-mask", "--", STUB, "leak", "ONE_A")[0] == 0
    seen = capfd.readouterr()
    assert (seen.out, seen.err) == ("out:%s\n" % VALUE, "err:%s\n" % VALUE)


def test_keeps_each_argument_word_for_word(vault, capfd):
    sets(vault)
    odd = ["two words", "$HOME", "'single'", '"double"', "back\\slash", "new\nline", "é…", ""]
    assert vault.run("run", "one", *vault.r, "--", STUB, "args", *odd)[0] == 0
    assert capfd.readouterr().out == "".join(a + "\0" for a in odd)


def test_passes_on_the_commands_exit_code_and_a_signal(vault, capfd):
    sets(vault)
    assert vault.run("run", "one", *vault.r, "--", STUB, "exit", "7")[0] == 7
    assert vault.run("run", "one", *vault.r, "--no-mask", "--", STUB, "exit", "3")[0] == 3
    assert vault.run("run", "one", *vault.r, "--", STUB, "term")[0] == 143


def test_refuses_with_125_when_a_needed_name_is_empty_naming_it_only(vault, capfd):
    sets(vault)
    code, out, err = vault.run("run", "one", "--need", "ONE_A", "ONE_EMPTY", *vault.r, "--",
                               STUB, "env", "ONE_A")
    assert (code, out) == (125, "")
    assert err == "secrets: ONE_EMPTY is empty in one; put a value in with: secrets set one ONE_EMPTY\n"
    assert capfd.readouterr().out == ""


def test_refuses_with_125_when_a_needed_name_is_in_no_set(vault, capfd):
    sets(vault)
    code, _out, err = vault.run("run", "one", "--need", "NOWHERE", *vault.r, "--", STUB, "exit", "0")
    assert (code, err) == (125, "secrets: NOWHERE is in none of the sets: one\n")


def test_refuses_with_125_a_set_that_is_not_there_or_unsafe(vault, capfd):
    sets(vault)
    code, _out, err = vault.run("run", "nothere", *vault.r, "--", STUB, "exit", "0")
    assert code == 125 and "no set nothere" in err
    vault.make("open", "export X='1'\n", file_mode=0o644)
    code, _out, err = vault.run("run", "open", *vault.r, "--", STUB, "exit", "0")
    assert code == 125
    assert err == ("secrets: open is not safe to use: %s is mode 644; make it private with: "
                   "chmod 600 %s\n" % (vault.root / "open" / "env.sh", vault.root / "open" / "env.sh"))
    assert capfd.readouterr().out == ""


def test_refuses_with_125_a_name_given_by_two_sets(vault, capfd):
    sets(vault)
    vault.make("three", "export ONE_A='other'\n")
    code, _out, err = vault.run("run", "one", "three", *vault.r, "--", STUB, "exit", "0")
    assert (code, err) == (125, "secrets: ONE_A is in both one and three; name only one of them\n")


def test_127_for_a_command_not_found_and_126_for_one_that_cannot_run(vault, capfd):
    sets(vault)
    code, _out, err = vault.run("run", "one", *vault.r, "--", str(vault.tmp / "no-such-program"))
    assert (code, err) == (127, "secrets: %s: command not found\n" % (vault.tmp / "no-such-program"))
    plain = vault.tmp / "not-executable"
    plain.write_text("echo hi\n")
    plain.chmod(0o644)
    code, _out, err = vault.run("run", "one", *vault.r, "--no-mask", "--", str(plain))
    assert code == 126 and err.startswith("secrets: %s cannot be run: " % plain)


def test_its_own_usage_errors_are_125_so_they_rarely_meet_a_commands_own(vault, capfd):
    sets(vault)
    assert vault.run("run", "one", *vault.r, STUB, "exit", "0")[0] == 125
    assert vault.run("run", "one", *vault.r, "--")[0] == 125
    assert vault.run("run", "one", "--bogus", *vault.r, "--", STUB, "exit", "0")[0] == 125
    assert vault.run("run", *vault.r, "--", STUB, "exit", "0")[0] == 125


def test_run_writes_nothing(vault, capfd):
    sets(vault)
    before = vault.files()
    vault.run("run", "one", *vault.r, "--", STUB, "leak", "ONE_A")
    assert vault.files() == before


def test_the_pump_keeps_draining_when_its_reader_has_gone(monkeypatch):
    written = []

    def gone(fd, data):
        written.append(data)
        raise BrokenPipeError(32, "Broken pipe")

    monkeypatch.setattr(secrets.os, "write", gone)
    reads = iter([b"first ", b"second", b""])
    monkeypatch.setattr(secrets.os, "read", lambda fd, size: next(reads))

    class Stream:
        def fileno(self):
            return 99

    secrets.pump(Stream(), 1, secrets.Masker([]))
    assert written == [b"first "]


def test_runs_as_a_program_masking_what_the_command_prints(vault):
    sets(vault)
    done = subprocess.run([sys.executable, str(COMMAND), "run", "one", *vault.r, "--", STUB,
                           "leak", "ONE_A"], capture_output=True, check=False)
    assert (done.returncode, done.stdout, done.stderr) == (0, b"out:[secret]\n", b"err:[secret]\n")


def test_help_as_a_program(vault):
    done = subprocess.run([str(COMMAND), "run", "--help"], capture_output=True, text=True, check=False)
    assert done.returncode == 0
    assert "--no-mask" in done.stdout and "125" in done.stdout
