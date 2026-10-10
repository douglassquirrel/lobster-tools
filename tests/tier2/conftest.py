"""Runs lobster-mail's main() in-process against a scratch mail root, with the clock fixed."""
import contextlib
import io

import pytest

from lobstertools import mail

NOW = "2026-10-10T10:00:00+01:00"


@pytest.fixture
def root(tmp_path):
    return tmp_path / "mail"


@pytest.fixture
def run(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for name in ("LOBSTER_MAIL_ROOT", "LOBSTER_MAIL_AS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LOBSTER_MAIL_NOW", NOW)

    def _run(*argv, stdin=""):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = mail.main(list(argv), stdin=io.StringIO(stdin))
            except SystemExit as exit_:
                code = exit_.code if isinstance(exit_.code, int) else 1
        return code, out.getvalue(), err.getvalue()

    return _run
