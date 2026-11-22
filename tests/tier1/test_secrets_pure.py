"""secrets, the pure parts: reading and writing env.sh lines, and masking (Request 30 from bernstein;
PLAN.md "Settled" 70-73). Every value here is invented."""
import pytest

from lobstertools import secrets

HOSTILE = "s3cr3t-$\"'\\ `x` é…\tend"


def names_values(text):
    return [(e.name, e.value) for e in secrets.parse_env(text) if e.name]


def test_reads_the_lines_secrets_writes_and_the_ones_a_person_typed():
    text = ("# made by hand\n"
            "\n"
            "export ALPHA_ID=''\n"
            "export BETA='a b'\\''c'\n"
            "GAMMA=plain-value_1.2:3@x/y+z,w=v%\n"
            'export DELTA="double quoted"\n'
            "export EPSILON='spaced'   # a note\n")
    assert names_values(text) == [("ALPHA_ID", ""), ("BETA", "a b'c"),
                                  ("GAMMA", "plain-value_1.2:3@x/y+z,w=v%"),
                                  ("DELTA", "double quoted"), ("EPSILON", "spaced")]


def test_keeps_every_line_as_it_was_written():
    text = "# c\r\n\nexport A='1'\nexport B=''"
    assert "".join(e.raw for e in secrets.parse_env(text)) == text
    assert [e.number for e in secrets.parse_env(text)] == [1, 2, 3, 4]


@pytest.mark.parametrize("line", [
    "export A=$HOME",
    "export A=\"has $dollar\"",
    "export A=\"has `tick`\"",
    "export A=\"has \\ backslash\"",
    "export A='unterminated",
    "export A=a;rm",
    "export A=a b",
    "export A=$(id)",
    "A = 'spaced'",
    "export 1A='x'",
    "echo hello",
    "export A=~/x",
])
def test_refuses_a_line_it_cannot_read_naming_only_its_number(line):
    with pytest.raises(secrets.BadLine) as caught:
        secrets.parse_env("export OK='1'\n" + line + "\n")
    assert caught.value.number == 2
    assert line not in str(caught.value)


def test_refuses_a_name_given_twice():
    with pytest.raises(secrets.BadLine) as caught:
        secrets.parse_env("export A='1'\nexport B=''\nexport A='2'\n")
    assert caught.value.number == 3


def test_writes_a_line_the_shell_and_this_parser_both_read_back():
    line = secrets.env_line("TOKEN", HOSTILE)
    assert line == "export TOKEN='s3cr3t-$\"'\\''\\ `x` é…\tend'\n"
    assert names_values(line) == [("TOKEN", HOSTILE)]
    assert secrets.env_line("EMPTY", "") == "export EMPTY=''\n"


@pytest.mark.parametrize("name,ok", [("GOOGLE_ID", True), ("_X", True), ("A1", True),
                                     ("a", False), ("1A", False), ("A-B", False), ("", False),
                                     ("A B", False)])
def test_names_are_capitals_figures_and_underscores(name, ok):
    assert secrets.good_name(name) is ok


@pytest.mark.parametrize("name,ok", [("google", True), ("dropbox-2", True), ("a_b", True),
                                     ("Google", False), ("../x", False), ("a/b", False),
                                     (".hidden", False), ("", False), ("-x", False)])
def test_set_names_cannot_leave_the_root(name, ok):
    assert secrets.good_set_name(name) is ok


def masked(values, chunks):
    masker = secrets.Masker([v.encode() for v in values])
    return b"".join(masker.feed(c) for c in chunks) + masker.flush()


def test_masks_a_value_in_one_piece():
    assert masked(["abcdefgh1"], [b"token=abcdefgh1 ok\n"]) == b"token=[secret] ok\n"


def test_masks_a_value_split_across_reads():
    assert masked(["abcdefgh1"], [b"x abcd", b"efg", b"h1 y\n"]) == b"x [secret] y\n"


def test_masks_the_longer_of_two_overlapping_values_first():
    assert masked(["abcdefgh", "abcdefgh-longer"], [b"<abcdefgh-longer>"]) == b"<[secret]>"


def test_leaves_values_shorter_than_eight_characters_alone():
    assert masked(["short", ""], [b"short and sweet"]) == b"short and sweet"


def test_holds_back_only_what_could_start_a_value():
    masker = secrets.Masker([b"abcdefgh1"])
    assert masker.feed(b"Enter code: ") == b"Enter code: "
    assert masker.feed(b"xx abc") == b"xx "
    assert masker.feed(b"zz") == b"abczz"
    assert masker.flush() == b""


def test_masks_a_non_ascii_value_as_its_bytes():
    value = "clé-très-secrète"
    assert masked([value], [value.encode()[:5], value.encode()[5:] + b"!"]) == b"[secret]!"


class Child:
    def __init__(self):
        self.sent = []

    def send_signal(self, signum):
        self.sent.append(signum)


def test_relay_passes_each_of_the_three_signals_on_when_not_in_a_terminals_foreground():
    import signal
    relay, child = secrets.Relay(lambda: False), Child()
    relay.attach(child)
    for each in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        relay.handle(each, None)
    assert child.sent == [signal.SIGTERM, signal.SIGINT, signal.SIGHUP]


def test_relay_in_a_terminals_foreground_passes_only_sigterm_on():
    import signal
    relay, child = secrets.Relay(lambda: True), Child()
    relay.attach(child)
    for each in (signal.SIGINT, signal.SIGHUP, signal.SIGTERM):
        relay.handle(each, None)
    assert child.sent == [signal.SIGTERM]


def test_relay_keeps_a_signal_that_comes_before_the_command_and_sends_it_once_it_exists():
    import signal
    relay, child = secrets.Relay(lambda: False), Child()
    relay.handle(signal.SIGTERM, None)
    assert child.sent == []
    relay.attach(child)
    assert child.sent == [signal.SIGTERM]
    relay.handle(signal.SIGHUP, None)
    assert child.sent == [signal.SIGTERM, signal.SIGHUP]


def test_in_foreground_is_false_with_no_terminal_to_open(monkeypatch, tmp_path):
    monkeypatch.setattr(secrets, "TTY", str(tmp_path / "no-terminal"))
    assert secrets.in_foreground() is False
