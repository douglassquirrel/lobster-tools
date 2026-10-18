"""Request 5: sends from one mailbox at the same moment take turns, so no two share an id, and a
message that was delivered is never reported as not sent."""
import fcntl
import io
import threading

import pytest
from conftest import HOSTILE, files_in

from lobstertools import mail, message

ID = "2026-10-10-0900-a-stop-hand-over"


@pytest.fixture
def four(run, root, two):
    """Mailboxes a, b, c and d; returns the body file."""
    for name in ("c", "d"):
        code, _, err = run("init", name, "--root", str(root))
        assert code == 0, err
    return two


def send(root, to, codes):
    codes[to] = mail.main(["send", "--root", str(root), "--as", "a", "--to", to, "--subject",
                           "Stop: hand over", "-"], stdin=io.StringIO("Stop, please.\n"))


def test_sends_at_the_same_moment_take_turns_and_each_gets_its_own_id(run, root, four,
                                                                     monkeypatch):
    """The first send has chosen its id and written nothing yet when two more from the same
    mailbox start; each is let go only once it has reached the lock. All three succeed, with
    three ids and three sent copies, as three sends one after another would."""
    at_lock = {"c": threading.Event(), "d": threading.Event()}
    real_flock, real_unique = fcntl.flock, message.unique_id
    threads, codes = [], {}

    def flock(fd, op):
        name = threading.current_thread().name
        if name in at_lock and op & fcntl.LOCK_EX:
            at_lock[name].set()
        return real_flock(fd, op)

    def unique_id(base, taken):
        chosen = real_unique(base, taken)
        if threading.current_thread() is threading.main_thread() and not threads:
            for to in ("c", "d"):
                thread = threading.Thread(target=send, args=(root, to, codes), name=to)
                threads.append(thread)
                thread.start()
                assert at_lock[to].wait(10), "the send to %s never asked for the lock" % to
        return chosen

    monkeypatch.setattr(fcntl, "flock", flock)
    monkeypatch.setattr(message, "unique_id", unique_id)
    code, _, err = run("send", "--root", str(root), "--as", "a", "--to", "b", "--subject",
                       "Stop: hand over", "-", stdin="Stop, please.\n")
    for thread in threads:
        thread.join(10)
    assert (code, codes) == (0, {"c": 0, "d": 0}), err
    assert files_in(root / "b" / "new") == [ID + ".md"]
    ids = {files_in(root / to / "new")[0] for to in ("c", "d")}
    assert ids == {ID + "-2.md", ID + "-3.md"}
    assert files_in(root / "a" / "sent") == sorted([ID + ".md", ID + "-2.md", ID + "-3.md"])
    assert files_in(root / "a" / "tmp") == []
    for to in ("b", "c", "d"):
        (name,) = files_in(root / to / "new")
        assert (root / to / "new" / name).read_bytes() == (root / "a" / "sent" / name).read_bytes()


def test_sends_one_after_another_keep_their_ids(run, root, four):
    for to in ("b", "c", "d"):
        code, _, err = run("send", "--root", str(root), "--as", "a", "--to", to, "--subject",
                           "Stop: hand over", str(four))
        assert code == 0, err
    assert [files_in(root / to / "new") for to in ("b", "c", "d")] == [
        [ID + ".md"], [ID + "-2.md"], [ID + "-3.md"]]
    assert (root / "c" / "new" / (ID + "-2.md")).read_bytes().endswith(HOSTILE)
