"""What each refuses before it runs anything, with the exit code for each."""
import pytest


@pytest.mark.parametrize("word", ["python3", "/bin/sh", "bash", "env", "xargs", "osascript"])
def test_a_shell_or_interpreter_is_refused_with_exit_2_and_nothing_runs(bench, word):
    for dry in ([], ["--dry-run"]):
        code, out, err = bench.run(*dry, "a", "--", word, "-c", "1")
        assert (code, out) == (2, "")
        assert err.startswith("each: %s refused: each runs one tool" % word.rsplit("/", 1)[-1]), err
        assert "rule 11" in err
    assert bench.log() == []


def test_a_command_not_on_path_is_exit_3_and_nothing_runs(bench):
    code, out, err = bench.run("--dry-run", "a", "--", "archive-nope", "{}")
    assert (code, out) == (3, "")
    assert err == "each: archive-nope: no such command on PATH; nothing run\n"


def test_a_command_given_by_a_path_that_is_not_there_is_exit_3(bench):
    code, _, err = bench.run("a", "--", "./not-here")
    assert (code, err) == (3, "each: ./not-here: no such command; nothing run\n")


def test_a_command_given_by_its_path_runs(bench):
    code, _, err = bench.run("a", "--", str(bench.bin / "archive-ask"))
    assert code == 0, err
    assert bench.log() == ["ran 1"]


@pytest.mark.parametrize("argv", [["a", "--"], ["a", "b"], ["--from", "-"]])
def test_nothing_after_the_double_dash_is_exit_2(bench, argv):
    code, out, err = bench.run(*argv)
    assert (code, out) == (2, "")
    assert err.endswith("each: error: nothing after --: give the command to run, as in "
                        "each ITEM ... -- COMMAND [ARG ...]\n"), err


def test_items_and_from_together_are_exit_2(bench):
    code, _, err = bench.run("a", "--from", "-", "--", "archive-ask")
    assert code == 2
    assert err.endswith("each: error: give the items after each or in --from, not both\n"), err


def test_no_items_and_no_from_is_exit_2(bench):
    code, _, err = bench.run("--", "archive-ask")
    assert code == 2
    assert err.endswith("each: error: no items: list them before --, or give --from FILE "
                        "(- for standard input)\n"), err


def test_a_from_file_that_cannot_be_read_is_exit_2(bench):
    code, out, err = bench.run("--from", "missing.txt", "--", "archive-ask")
    assert (code, out) == (2, "")
    assert err == ("each: --from missing.txt cannot be read (No such file or directory); "
                   "nothing run\n")
    assert bench.log() == []


def test_an_item_that_is_not_utf8_reaches_the_command_byte_for_byte(bench):
    listing = bench.tmp / "list.txt"
    listing.write_bytes(b"caf\xe9\n")
    code, _, err = bench.run("--from", str(listing), "--", "archive-ask")
    assert code == 0, err
    assert bench.argv(1) == [b"caf\xe9"]
