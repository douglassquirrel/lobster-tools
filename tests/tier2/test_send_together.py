"""Request 5: sends from one mailbox at the same moment take turns, so no two share an id, and a
message that was delivered is never reported as not sent."""
import fcntl
import io
import os
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


def test_a_delivered_message_whose_sent_copy_fails_exits_7_and_says_not_to_send_again(
        run, root, two, monkeypatch):
    real = os.rename

    def refuse_sent(src, dst):
        if os.path.dirname(dst) == str(root / "a" / "sent"):
            raise OSError(28, "No space left on device")
        real(src, dst)

    monkeypatch.setattr(os, "rename", refuse_sent)
    code, out, err = run("send", "--root", str(root), "--as", "a", "--to", "b", "--subject", "Hi",
                         str(two))
    hi = "2026-10-10-0900-a-hi"
    delivered, left = root / "b" / "new" / (hi + ".md"), root / "a" / "tmp" / (hi + ".md")
    assert (code, out) == (7, "")
    assert err == ("lobster-mail send: delivered %s to b (%s), but its copy could not be written "
                   "to a/sent/: No space left on device; the copy is left in %s. The message was "
                   "sent: do not send it again.\n" % (hi, delivered, left))
    assert delivered.read_bytes() == left.read_bytes()
    assert message.parse(delivered.read_bytes()).body == HOSTILE
    assert files_in(root / "a" / "sent") == []


HI = "2026-10-10-0900-a-hi"


def send_hi(run, root, two):
    return run("send", "--root", str(root), "--as", "a", "--to", "b", "--subject", "Hi", str(two))


def test_a_name_already_taken_in_the_recipients_tmp_names_no_partial_file(run, root, two,
                                                                          monkeypatch):
    """A send whose view of the taken ids is out of date, as one racing another would have."""
    theirs = root / "b" / "tmp" / (HI + ".md")
    theirs.write_bytes(b"someone else's\n")
    monkeypatch.setattr(mail.Mailbox, "ids", lambda self, boxes=None: set())
    code, out, err = send_hi(run, root, two)
    assert (code, out) == (4, "")
    assert err == ("lobster-mail send: could not deliver %s to b/new/: a file named %s.md is "
                   "already in b/tmp/, not written by this run; this run left nothing in b/tmp/\n"
                   % (HI, HI))
    assert theirs.read_bytes() == b"someone else's\n"
    assert files_in(root / "b" / "new") == [] and files_in(root / "a" / "sent") == []


def test_a_name_already_taken_in_the_senders_tmp_after_delivery_exits_7_naming_no_file(
        run, root, two, monkeypatch):
    """Request 5's case: delivered, then the sent copy's name in tmp/ was another send's."""
    theirs = root / "a" / "tmp" / (HI + ".md")
    theirs.write_bytes(b"another send's\n")
    monkeypatch.setattr(mail.Mailbox, "ids", lambda self, boxes=None: set())
    code, out, err = send_hi(run, root, two)
    delivered = root / "b" / "new" / (HI + ".md")
    assert (code, out) == (7, "")
    assert err == ("lobster-mail send: delivered %s to b (%s), but its copy could not be written "
                   "to a/sent/: a file named %s.md is already in a/tmp/, not written by this run; "
                   "this run left nothing in a/tmp/. The message was sent: do not send it again.\n"
                   % (HI, delivered, HI))
    assert message.parse(delivered.read_bytes()).body == HOSTILE
    assert theirs.read_bytes() == b"another send's\n"


def test_a_write_refused_before_the_file_exists_names_no_partial_file(run, root, two,
                                                                     monkeypatch):
    def refuse(path, data):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(mail, "write_new_file", refuse)
    code, out, err = send_hi(run, root, two)
    assert (code, out) == (4, "")
    assert err == ("lobster-mail send: could not deliver %s to b/new/: Permission denied; this "
                   "run left nothing in b/tmp/\n" % HI)
    assert files_in(root / "b" / "tmp") == [] and files_in(root / "b" / "new") == []


def test_a_write_that_fails_part_way_names_the_partial_file(run, root, two, monkeypatch):
    def part_way(path, data):
        with open(path, "xb") as handle:
            handle.write(data[:10])
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(mail, "write_new_file", part_way)
    code, out, err = send_hi(run, root, two)
    partial = root / "b" / "tmp" / (HI + ".md")
    assert (code, out) == (4, "")
    assert err == ("lobster-mail send: could not deliver %s to b/new/: No space left on device; "
                   "the partial file is %s\n" % (HI, partial))
    assert partial.read_bytes() == b"From: a\nTo"
