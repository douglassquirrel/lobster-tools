from lobstertools import mail


class Fakes:
    """A clock that advances by each sleep, a look that returns mail on a chosen look."""

    def __init__(self, mail_on_look=None):
        self.time, self.sleeps, self.looks, self.mail_on_look = 0.0, [], 0, mail_on_look

    def now(self):
        return self.time

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.time += seconds

    def look(self):
        self.looks += 1
        return ["mail"] if self.looks == self.mail_on_look else []


def test_returns_at_once_without_sleeping_when_mail_is_there():
    fakes = Fakes(mail_on_look=1)
    assert mail.watch_loop(fakes.look, fakes.now, fakes.sleep, timeout=10, every=2) == ["mail"]
    assert fakes.sleeps == []


def test_looks_every_interval_until_mail_appears():
    fakes = Fakes(mail_on_look=3)
    assert mail.watch_loop(fakes.look, fakes.now, fakes.sleep, timeout=60, every=2) == ["mail"]
    assert fakes.sleeps == [2, 2] and fakes.looks == 3


def test_gives_up_when_the_timeout_passes():
    fakes = Fakes(mail_on_look=None)
    assert mail.watch_loop(fakes.look, fakes.now, fakes.sleep, timeout=5, every=2) is None
    assert fakes.sleeps == [2, 2, 2] and fakes.time >= 5


def test_timeout_zero_means_wait_as_long_as_it_takes():
    fakes = Fakes(mail_on_look=50)
    assert mail.watch_loop(fakes.look, fakes.now, fakes.sleep, timeout=0, every=1) == ["mail"]
    assert len(fakes.sleeps) == 49
