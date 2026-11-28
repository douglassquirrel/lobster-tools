"""each's pure parts: reading the list, putting the item into the command, what it refuses."""
from lobstertools import each


def test_one_item_per_line_blank_lines_skipped_and_spaces_kept():
    text = "first\n\n  \n two words \n\t\nlast"
    assert each.items_from(text) == ["first", " two words ", "last"]


def test_a_carriage_return_before_the_newline_is_dropped_and_nothing_else():
    assert each.items_from("a\r\nb\r\n c\r\r\n") == ["a", "b", " c\r"]


def test_an_empty_list_is_no_items():
    assert each.items_from("") == []
    assert each.items_from("\n\n") == []


def test_the_item_goes_last_when_no_argument_holds_braces():
    assert each.filled(["archive-ask", "--quiet"], "2026-11-20") == [
        "archive-ask", "--quiet", "2026-11-20"]


def test_braces_are_replaced_wherever_they_stand_and_as_often_as_they_appear():
    assert each.filled(["tool", "--date={}", "{}", "x{}y{}"], "a b") == [
        "tool", "--date=a b", "a b", "xa bya b"]


def test_braces_in_the_command_word_itself_are_left_and_the_item_goes_last():
    assert each.filled(["{}tool", "-v"], "i") == ["{}tool", "-v", "i"]


def test_an_item_is_put_in_as_it_is_never_read_for_braces_or_shell_characters():
    item = "$(rm -rf /) `x` ; | \\ \"q\" 'q' {} café"
    assert each.filled(["tool", "<{}>"], item) == ["tool", "<%s>" % item]


REFUSED = ["sh", "bash", "zsh", "dash", "ksh", "fish", "csh", "tcsh", "python", "python3",
           "python3.9", "/usr/bin/python3", ".venv/bin/python", "perl", "ruby", "node", "osascript",
           "php", "lua", "Rscript", "/bin/sh", "env", "/usr/bin/env", "xargs"]


def test_shells_interpreters_env_and_xargs_are_refused_naming_rule_11():
    for word in REFUSED:
        reason = each.refusal(word)
        assert reason is not None, word
        assert "rule 11" in reason, reason


def test_the_refusal_says_what_was_refused_and_what_to_do():
    assert each.refusal("/usr/bin/python3") == (
        "python3 refused: each runs one tool over a list, never a shell or an interpreter "
        "(a ganglion's rule 11). Name the tool itself after --; a job no tool does yet is a "
        "request to a claw.")


def test_ordinary_tools_are_not_refused():
    for word in ["archive-ask", "ffprobe", "ls", "git", "./lobster-mail", "pythonic-tool",
                 "shasum", "envy", "xargsish", "job", "measure"]:
        assert each.refusal(word) is None, word
