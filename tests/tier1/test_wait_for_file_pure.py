"""wait-for-file's loop, with a fake clock (Request 29 from bernstein; PLAN.md "Settled" 64)."""
from lobstertools import waitfile


class Fakes:
    """A clock that advances by each sleep, and a look that answers from a list, one per look
    (the last answer repeating)."""

    def __init__(self, answers):
        self.time, self.sleeps, self.answers, self.looks = 0.0, [], list(answers), 0

    def now(self):
        return self.time

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.time += seconds

    def look(self):
        self.looks += 1
        return self.answers[min(self.looks, len(self.answers)) - 1]


def wait(fakes, timeout=60, stable=0, every=1):
    return waitfile.wait_until(fakes.look, fakes.now, fakes.sleep, timeout, stable, every)


def test_returns_at_once_without_sleeping_when_the_file_is_there():
    fakes = Fakes([("f", 3, 1)])
    assert wait(fakes) == ("f", 3, 1)
    assert fakes.sleeps == []


def test_looks_every_second_until_the_file_appears():
    fakes = Fakes([None, None, ("f", 0, 7)])
    assert wait(fakes) == ("f", 0, 7)
    assert fakes.sleeps == [1, 1] and fakes.looks == 3


def test_gives_up_at_the_timeout_with_none():
    fakes = Fakes([None])
    assert wait(fakes, timeout=3) is None
    assert fakes.sleeps == [1, 1, 1] and fakes.time == 3


def test_timeout_zero_waits_as_long_as_it_takes():
    fakes = Fakes([None] * 500 + [("f", 1, 1)])
    assert wait(fakes, timeout=0) == ("f", 1, 1)
    assert fakes.looks == 501


def test_stable_waits_until_the_file_has_not_changed_for_that_long():
    growing = [None, ("f", 1, 1), ("f", 2, 2), ("f", 3, 3), ("f", 3, 3), ("f", 3, 3), ("f", 3, 3)]
    fakes = Fakes(growing)
    assert wait(fakes, stable=2) == ("f", 3, 3)
    # seen whole at time 3, unchanged at 4 and 5: two seconds stable at time 5
    assert fakes.time == 5


def test_stable_starts_again_when_the_file_vanishes():
    fakes = Fakes([("f", 1, 1), None, ("f", 1, 1), ("f", 1, 1), ("f", 1, 1)])
    assert wait(fakes, stable=2) == ("f", 1, 1)
    assert fakes.time == 4


def test_a_file_still_changing_at_the_timeout_is_none():
    fakes = Fakes([("f", n, n) for n in range(1, 100)])
    assert wait(fakes, timeout=5, stable=2) is None


def test_never_sleeps_past_the_timeout():
    fakes = Fakes([None])
    assert wait(fakes, timeout=2.5, every=1) is None
    assert fakes.sleeps == [1, 1, 0.5]


def test_look_for_one_path_takes_it_whole(tmp_path):
    odd = tmp_path / "a file $HOME *.wav"
    look = waitfile.looker(str(odd), glob=False)
    assert look() is None
    (tmp_path / "a file x.wav").write_bytes(b"x")
    assert look() is None
    odd.write_bytes(b"abc")
    assert look() == ((str(odd), 3, odd.stat().st_mtime_ns),)


def test_look_with_glob_matches_the_pattern(tmp_path):
    look = waitfile.looker(str(tmp_path / "*.wav"), glob=True)
    assert look() is None
    (tmp_path / "b.wav").write_bytes(b"bb")
    (tmp_path / "a.wav").write_bytes(b"a")
    (tmp_path / "c.txt").write_bytes(b"c")
    assert [entry[0] for entry in look()] == [str(tmp_path / "a.wav"), str(tmp_path / "b.wav")]
