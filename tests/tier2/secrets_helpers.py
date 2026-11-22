"""Fixtures for secrets' tests (Request 30 from bernstein): main() run in-process against a scratch
root of sets, with HOME in the test's own folder. Every name and value is invented."""
import contextlib
import io
import os
import stat

import pytest

from lobstertools import secrets

HOSTILE = "s3cr3t-$\"'\\ `x` é…\tend"


def mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


class Bytes(io.BytesIO):
    def __init__(self, data=b"", tty=False):
        super().__init__(data)
        self.tty = tty

    def isatty(self):
        return self.tty


@pytest.fixture
def vault(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("LOBSTER_SECRETS_ROOT", raising=False)
    root = tmp_path / "secrets"
    root.mkdir(mode=0o700)
    os.chmod(root, 0o700)

    class World:
        pass

    w = World()
    w.home, w.root, w.tmp = home, root, tmp_path

    def run(*argv, stdin=b"", tty=False, ask=None):
        if ask is not None:
            monkeypatch.setattr(secrets, "ask", ask)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = secrets.main(list(argv), stdin=Bytes(stdin, tty))
            except SystemExit as exit_:
                code = exit_.code if isinstance(exit_.code, int) else 1
        return code, out.getvalue(), err.getvalue()

    def make(name, text, folder_mode=0o700, file_mode=0o600):
        folder = root / name
        folder.mkdir()
        (folder / "env.sh").write_text(text, encoding="utf-8")
        os.chmod(folder / "env.sh", file_mode)
        os.chmod(folder, folder_mode)
        return folder

    def files():
        """Every file under the test's folder, with its bytes."""
        found = {}
        for top, _, names in os.walk(tmp_path):
            for name in names:
                path = os.path.join(top, name)
                with open(path, "rb") as handle:
                    found[os.path.relpath(path, tmp_path)] = handle.read()
        return found

    w.run, w.make, w.files = run, make, files
    w.r = ("--root", str(root))
    return w
