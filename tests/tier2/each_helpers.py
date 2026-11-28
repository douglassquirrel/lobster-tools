"""Shared by each's tier 2 tests: the command called in-process with the stand-in
tests/stubs/eachstub linked onto PATH as archive-ask, and what the stand-in saw."""
import hashlib
import io
import os
import pathlib

import pytest

from lobstertools import each

HERE = pathlib.Path(__file__).resolve().parent
STUB = HERE.parent / "stubs" / "eachstub"
COMMAND = str(HERE.parents[1] / "each")


class Bench:
    def __init__(self, tmp_path, monkeypatch, capfd):
        self.tmp, self.capfd = tmp_path, capfd
        self.stub = tmp_path / "stub"
        self.stub.mkdir()
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        os.symlink(str(STUB), str(self.bin / "archive-ask"))
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("PATH", "%s:/usr/bin:/bin" % self.bin)
        monkeypatch.setenv("EACHSTUB_DIR", str(self.stub))

    def run(self, *argv, stdin=""):
        self.capfd.readouterr()
        try:
            code = each.main(list(argv), stdin=io.StringIO(stdin))
        except SystemExit as exit_:
            code = exit_.code
        out, err = self.capfd.readouterr()
        return code, out, err

    def log(self):
        path = self.stub / "log"
        return path.read_text("utf-8").splitlines() if path.exists() else []

    def argv(self, n):
        return (self.stub / ("argv-%d" % n)).read_bytes().split(b"\0")[:-1]

    def stdin(self, n):
        return (self.stub / ("stdin-%d" % n)).read_bytes()

    def exits(self, n, code):
        (self.stub / ("exit-%d" % n)).write_text(str(code))


@pytest.fixture(scope="session", autouse=True)
def eachstub_is_never_written_over():
    before = hashlib.sha256(STUB.read_bytes()).hexdigest()
    yield
    assert hashlib.sha256(STUB.read_bytes()).hexdigest() == before


@pytest.fixture
def bench(tmp_path, monkeypatch, capfd):
    return Bench(tmp_path, monkeypatch, capfd)
