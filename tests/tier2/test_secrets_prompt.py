"""secrets set's prompt: a hidden value of any length, read through a pseudo-terminal (Request 61
from archivist; PLAN.md "Settled" 74)."""
import os
import pty
import select
import termios
import threading

import pytest

from lobstertools import secrets

PROMPT = "Value (not shown): "


def drive(keys, call, prompt=PROMPT):
    """Run CALL(slave_fd) in a thread on a fresh pseudo-terminal; once the prompt has appeared
    (so the terminal is in the prompt's mode), type KEYS. Return what CALL returned or raised,
    everything the terminal showed, and the slave's settings before and after."""
    master, slave = pty.openpty()
    before = termios.tcgetattr(slave)
    got = {}

    def work():
        try:
            got["value"] = call(slave)
        except BaseException as error:  # noqa: BLE001 - handed back to the test
            got["error"] = error

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    shown = b""
    waited = 0
    while not shown.endswith(prompt.encode("utf-8")):
        if not thread.is_alive():
            raise AssertionError("ended before its prompt: %r; the terminal showed %r"
                                 % (got, shown))
        ready, _, _ = select.select([master], [], [], 0.05)
        waited += 1
        assert waited < 100, "no prompt; the terminal showed %r" % shown
        if ready:
            shown += os.read(master, 1024)
    def drain():
        found = b""
        while select.select([master], [], [], 0)[0]:
            chunk = os.read(master, 1024)
            if not chunk:
                break
            found += chunk
        return found

    os.set_blocking(master, False)
    left = keys
    while left:
        shown += drain()  # read as it types, so a prompt that echoes cannot fill the terminal
        if not select.select([], [master], [], 2)[1]:
            raise AssertionError("the terminal takes no more input after %d of %d bytes"
                                 % (len(keys) - len(left), len(keys)))
        try:
            left = left[os.write(master, left[:256]):]
        except BlockingIOError:
            if not thread.is_alive():
                break
    thread.join(2)
    assert not thread.is_alive(), "the prompt is still waiting; the terminal showed %r" % shown
    shown += drain()
    after = termios.tcgetattr(slave)
    # The kernel sets PENDIN itself when line mode is switched back on (BSD, macOS): not a setting.
    after[3] &= ~getattr(termios, "PENDIN", 0)
    before[3] &= ~getattr(termios, "PENDIN", 0)
    os.close(master)
    os.close(slave)
    return got, shown.decode("utf-8"), before, after


def hidden(keys):
    return drive(keys, lambda fd: secrets.read_hidden(fd, PROMPT))


def test_prompt_takes_a_2000_character_value_whole_and_shows_none_of_it():
    value = "".join("abcdefghij"[i % 10] for i in range(2000))
    got, shown, before, after = hidden(value.encode() + b"\r")
    assert got == {"value": value}
    assert shown == PROMPT + "\r\n"
    assert after == before


def test_prompt_ends_at_a_newline_or_ctrl_d_too():
    assert hidden(b"one\n")[0] == {"value": "one"}
    assert hidden(b"two\x04")[0] == {"value": "two"}


def test_prompt_backspace_takes_back_a_whole_character_and_ctrl_u_clears():
    got, _shown, _before, _after = hidden("abé\x7f\x7fc\x08d\r".encode())
    assert got == {"value": "ad"}
    got, _shown, _before, _after = hidden(b"wrong\x15right\r")
    assert got == {"value": "right"}
    got, _shown, _before, _after = hidden(b"\x7f\x7fok\r")
    assert got == {"value": "ok"}


def test_prompt_ctrl_c_stops_with_nothing_given_and_puts_the_terminal_back():
    got, shown, before, after = hidden(b"half-typed\x03more\r")
    error = got["error"]
    assert isinstance(error, secrets.Refusal)
    assert (error.code, str(error)) == (130, "stopped at the prompt; nothing changed")
    assert shown == PROMPT + "\r\n"
    assert after == before


def test_prompt_refuses_bytes_that_are_not_utf_8():
    got, _shown, before, after = hidden(b"\xff\xfe\r")
    error = got["error"]
    assert (error.code, str(error)) == (2, "the value is not UTF-8 text; nothing changed")
    assert after == before


def test_set_asks_on_the_terminal_with_no_line_limit(vault, monkeypatch):
    folder = vault.make("dropbox", "export D_TOKEN='old'\n")
    value = "t" * 1373
    result = {}

    def call(slave):
        monkeypatch.setattr(secrets, "TTY", os.ttyname(slave))
        result["run"] = vault.run("set", "dropbox", "D_TOKEN", "--min-length", "1000",
                                  *vault.r, tty=True)

    got, shown, _before, _after = drive(value.encode() + b"\r", call,
                                        prompt="Value for D_TOKEN in dropbox (not shown): ")
    assert got == {"value": None}
    assert result["run"] == (0, "D_TOKEN set in dropbox (replaced, 1373 characters; was 3)\n", "")
    assert value not in shown
    assert (folder / "env.sh").read_text(encoding="utf-8") == "export D_TOKEN='%s'\n" % value


def test_set_with_no_terminal_to_open_says_so(vault, monkeypatch, tmp_path):
    vault.make("dropbox", "export D_TOKEN='old'\n")
    monkeypatch.setattr(secrets, "TTY", str(tmp_path / "no-such-terminal"))
    code, out, err = vault.run("set", "dropbox", "D_TOKEN", *vault.r, tty=True)
    assert (code, out) == (2, "")
    assert err == ("secrets: no terminal to ask on; give --stdin to read the value from "
                   "standard input\n")


@pytest.fixture(autouse=True)
def _no_real_terminal(monkeypatch):
    """No test here may reach the session's own terminal."""
    monkeypatch.setattr(secrets, "TTY", os.devnull + "-not-a-terminal", raising=False)
