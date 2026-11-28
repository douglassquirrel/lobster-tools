"""script-guard started as a program, as Claude Code starts a hook: one run allowing, one refusing."""
import json
import os
import subprocess
import sys

from guard_helpers import COMMAND


def run(desk, project, command):
    data = {"session_id": "s-9", "cwd": str(project), "hook_event_name": "PreToolUse",
            "tool_name": "Bash", "tool_input": {"command": command}}
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project))
    return subprocess.run([sys.executable, COMMAND], input=json.dumps(data), env=env,
                          capture_output=True, text=True, check=False)


def test_as_a_program_it_allows_with_exit_0_and_says_nothing(desk):
    done = run(desk, desk.ganglion(), "git status")
    assert (done.returncode, done.stdout, done.stderr) == (0, "", "")


def test_as_a_program_it_refuses_with_exit_2_and_logs(desk):
    done = run(desk, desk.ganglion(), "for f in *.m4a; do ffprobe \"$f\"; done")
    assert (done.returncode, done.stdout) == (2, "")
    assert done.stderr.startswith("script-guard refused this command: a loop (for). ")
    assert desk.log("pond")[0]["session"] == "s-9"
