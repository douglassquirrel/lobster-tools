"""Shared by script-guard's tier 2 tests: invented projects with invented lobster.conf files, a
scratch mail root, and the hook called in-process with its JSON on standard input."""
import contextlib
import io
import json
import pathlib

import pytest

from lobstertools import guard

HERE = pathlib.Path(__file__).resolve().parent
COMMAND = str(HERE.parents[1] / "script-guard")
NOW = "2026-11-28T08:30:00Z"


class Desk:
    def __init__(self, tmp_path, monkeypatch):
        self.tmp = tmp_path
        self.root = tmp_path / "mail"
        self.root.mkdir()
        self.home = tmp_path / "home"
        self.home.mkdir()
        monkeypatch.setenv("HOME", str(self.home))
        monkeypatch.setenv("LOBSTER_MAIL_ROOT", str(self.root))
        monkeypatch.setenv("LOBSTER_GUARD_NOW", NOW)
        monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
        self.monkeypatch = monkeypatch

    def project(self, name, conf):
        folder = self.tmp / name
        folder.mkdir()
        if conf is not None:
            (folder / "lobster.conf").write_text(conf, "utf-8")
        return folder

    def ganglion(self, name="pond"):
        return self.project(name, "# an invented ganglion\nKIND=non-code\nSELF=%s\n" % name)

    def claw(self, name="pond-tools"):
        return self.project(name, "KIND=code\nSELF=%s\n" % name)

    def call(self, *argv, stdin=""):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = guard.main(list(argv), stdin=io.StringIO(stdin))
            except SystemExit as exit_:
                code = exit_.code
        return code, out.getvalue(), err.getvalue()

    def hook(self, command, project, tool="Bash", **more):
        self.monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
        data = {"session_id": "s-1", "transcript_path": "/x/t.jsonl", "cwd": str(project),
                "hook_event_name": "PreToolUse", "tool_name": tool,
                "tool_input": {"command": command, "description": "invented"}}
        data.update(more)
        return self.call(stdin=json.dumps(data))

    def log(self, name):
        path = self.root / ".script-guard" / ("%s.log" % name)
        if not path.exists():
            return None
        return [json.loads(line) for line in path.read_text("utf-8").splitlines()]


@pytest.fixture
def desk(tmp_path, monkeypatch):
    return Desk(tmp_path, monkeypatch)
