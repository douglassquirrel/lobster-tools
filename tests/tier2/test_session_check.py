"""session-check against an invented project and a stub `git` on PATH (Request 16; PLAN.md
"`session-check`: a session's start and end checks"). The stub records every call it is given and
answers from a spec the test writes; no real git, no network."""
import contextlib
import hashlib
import io
import json
import os
import pathlib
import sys

import pytest

from lobstertools import check, mail

NOW = "2026-10-10T10:00:00+01:00"
STAMP = "2026-10-10T09:00:00Z"

STUB = r'''#!%s
import json, os, sys, time
args = sys.argv[1:]
with open(os.environ["GIT_STUB_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps({"args": args, "locks": os.environ.get("GIT_OPTIONAL_LOCKS")}) + "\n")
with open(os.environ["GIT_STUB_SPEC"], encoding="utf-8") as handle:
    spec = json.load(handle)
if spec.get("hang"):
    time.sleep(5)
repo, verb, rest = args[1], args[2], args[3:]
mine = spec["repos"].get(repo)
if mine is None:
    sys.stderr.write("fatal: not a git repository\n")
    sys.exit(128)
if verb == "status":
    sys.stdout.write(mine.get("status", "# branch.oid 1\0# branch.head main\0"))
elif verb == "remote":
    sys.stdout.write(mine.get("remote", ""))
elif verb == "log":
    if mine.get("log") is None:
        sys.stderr.write("fatal: ambiguous argument\n")
        sys.exit(128)
    sys.stdout.write(mine["log"])
elif verb == "check-ignore":
    sys.exit(0 if rest[-1] in mine.get("ignored", []) else 1)
elif verb == "stash" and rest[:1] == ["list"]:
    if mine.get("stash_hangs"):
        time.sleep(5)
    if mine.get("stash_fails"):
        sys.stderr.write("fatal: stash list went wrong\n")
        sys.exit(128)
    sys.stdout.write("".join("\0".join(s) + "\n" for s in mine.get("stashes", [])))
else:
    sys.stderr.write("stub git: unexpected verb %%s\n" %% verb)
    sys.exit(2)
'''


def branch(upstream="origin/main", ahead=0, paths=()):
    """A porcelain v2 status, as "Things checked" 10 records it."""
    items = ["# branch.oid 250c95", "# branch.head main"]
    if upstream:
        items.append("# branch.upstream " + upstream)
        if ahead is not None:
            items.append("# branch.ab +%d -0" % ahead)
    items += ["? " + p for p in paths]
    return "".join(i + "\0" for i in items)


STASH_0 = ["stash@{0}", "2026-11-02 08:15:00 +0000", "WIP on main: 250c951 Two"]
STASH_1 = ["stash@{1}", "2026-11-01 09:30:00 +0100", "On main: café notes, \"quoted\" $HOME"]

LEVEL = {"status": branch(), "remote": "origin\n"}
LOCAL = {"status": branch(upstream=None), "remote": ""}


@pytest.fixture
def env(tmp_path, monkeypatch):
    """HOME, the mail root with the project's mailbox, the stub git on PATH, and an invented
    public tools project: an outer folder with a local history and a checkout inside it."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for name in ("LOBSTER_MAIL_ROOT", "LOBSTER_MAIL_AS", "LOBSTER_MAIL_SESSION"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LOBSTER_MAIL_NOW", NOW)
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "git").write_text(STUB % sys.executable, encoding="utf-8")
    (bin_ / "git").chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_) + os.pathsep + os.environ.get("PATH", ""))
    monkeypatch.setenv("GIT_STUB_LOG", str(tmp_path / "git-calls.jsonl"))
    monkeypatch.setenv("GIT_STUB_SPEC", str(tmp_path / "git-spec.json"))
    root = tmp_path / "mail"
    assert mail.main(["init", "garden-tools", "--root", str(root)]) == 0
    project = tmp_path / "garden-tools-code"
    (project / ".git").mkdir(parents=True)
    (project / "garden-tools" / ".git").mkdir(parents=True)
    (project / "lobster.conf").write_text(
        "# invented\nKIND=code\nSELF=garden-tools\nSISTER=\nCLAWS=\nFOLDERS=\n", encoding="utf-8")
    (project / "DIARY.md").write_text("line\n" * 10, encoding="utf-8")
    (project / "inbox").mkdir()
    (project / "inbox" / "README.md").write_text("drop files here\n", encoding="utf-8")
    (project / "dreams").mkdir()

    class Env:
        pass

    e = Env()
    e.tmp, e.home, e.root, e.project, e.bin = tmp_path, home, root, project, bin_
    e.spec = {"repos": {str(project): dict(LOCAL), str(project / "garden-tools"): dict(LEVEL)}}

    def handover(body, diary=None):
        argv = ["handover", "--root", str(root), "--as", "garden-tools", "-"]
        if diary:
            argv[1:1] = ["--diary", diary]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            assert mail.main(argv, stdin=io.StringIO(body)) == 0
        return out.getvalue()

    def run(*argv, project_dir=None, session="mac"):
        (tmp_path / "git-spec.json").write_text(json.dumps(e.spec), encoding="utf-8")
        full = list(argv) + ["--session", session, "--root", str(root),
                             "--project", str(project_dir or project)]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = check.main(full)
            except SystemExit as exit_:
                code = exit_.code if isinstance(exit_.code, int) else 1
        return code, out.getvalue(), err.getvalue()

    def calls():
        path = tmp_path / "git-calls.jsonl"
        if not path.exists():
            return []
        return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]

    e.handover, e.run, e.calls = handover, run, calls
    return e


def tell(out):
    """The lines under "To tell", in order."""
    lines = out.splitlines()
    if "-- Nothing to tell." in lines:
        return []
    start = next(i for i, x in enumerate(lines) if x.startswith("-- To tell"))
    return lines[start + 1:lines.index("-- Facts:")]


def facts(out):
    lines = out.splitlines()
    return lines[lines.index("-- Facts:") + 1:]


# A clean project

def test_a_clean_project_prints_every_fact_and_exits_0(env):
    env.handover("Stopped. DIARY.md is 10 lines.\n")
    code, out, err = env.run("start")
    assert (code, err) == (0, "")
    p = env.project
    assert out.splitlines() == [
        "== session-check start for garden-tools (mac), %s ==" % STAMP,
        "-- Nothing to tell.",
        "-- Facts:",
        "git, garden-tools-code: nothing uncommitted",
        "git, garden-tools-code: no remote (local only)",
        "git, garden-tools-code: no stash",
        "git, garden-tools-code/garden-tools: nothing uncommitted",
        "git, garden-tools-code/garden-tools: level with origin/main (as last fetched)",
        "git, garden-tools-code/garden-tools: no stash",
        "folder reachable: the mail root (%s)" % env.root,
        "__pycache__: none",
        "_to_delete/: none",
        "DIARY.md: 10 lines; the last handover gave 10",
        "inbox/: nothing new",
        "dreams/: nothing undecided",
    ]
    assert p.exists()


# git, one fault at a time

def test_uncommitted_files_are_counted_and_told(env):
    env.spec["repos"][str(env.project / "garden-tools")]["status"] = branch(
        paths=["a.py", "café notes.md"])
    code, out, _ = env.run("start")
    assert code == 1
    assert tell(out) == ["git, garden-tools-code/garden-tools: 2 files uncommitted"]


def test_commits_not_pushed_are_counted_and_told(env):
    env.spec["repos"][str(env.project / "garden-tools")]["status"] = branch(ahead=3)
    code, out, _ = env.run("start")
    assert code == 1
    assert tell(out) == ["git, garden-tools-code/garden-tools: 3 commits not pushed to origin/main"]


def test_one_commit_not_pushed_is_said_in_the_singular(env):
    env.spec["repos"][str(env.project / "garden-tools")]["status"] = branch(ahead=1,
                                                                            paths=["x"])
    _, out, _ = env.run("start")
    assert tell(out) == ["git, garden-tools-code/garden-tools: 1 file uncommitted",
                         "git, garden-tools-code/garden-tools: 1 commit not pushed to origin/main"]


def test_an_upstream_that_is_gone_is_said_plainly(env):
    env.spec["repos"][str(env.project / "garden-tools")]["status"] = branch(ahead=None)
    code, out, _ = env.run("start")
    assert code == 1
    assert tell(out) == [("git, garden-tools-code/garden-tools: its upstream origin/main is gone "
                         "(deleted on the remote, or never fetched), so what is not pushed "
                         "cannot be counted")]


def test_a_remote_with_no_upstream_is_told(env):
    env.spec["repos"][str(env.project / "garden-tools")]["status"] = branch(upstream=None)
    code, out, _ = env.run("start")
    assert code == 1
    assert tell(out) == [("git, garden-tools-code/garden-tools: branch main has a remote but no "
                         "upstream, so what is not pushed cannot be counted")]


def test_at_the_end_each_commit_not_pushed_is_listed_by_its_line(env):
    checkout = env.spec["repos"][str(env.project / "garden-tools")]
    checkout["status"] = branch(ahead=2)
    checkout["log"] = "250c951 Add the second thing\n1a2b3c4 Add the first thing\n"
    code, out, _ = env.run("end")
    assert code == 1
    assert tell(out) == [
        "git, garden-tools-code/garden-tools: 2 commits not pushed to origin/main",
        "  not pushed: 250c951 Add the second thing",
        "  not pushed: 1a2b3c4 Add the first thing",
    ]


def test_at_the_start_the_commits_are_counted_not_listed(env):
    checkout = env.spec["repos"][str(env.project / "garden-tools")]
    checkout["status"] = branch(ahead=2)
    checkout["log"] = "250c951 Add the second thing\n"
    env.run("start")
    assert not any(c["args"][2] == "log" for c in env.calls())


def test_at_the_end_an_uncommitted_diary_is_told(env):
    env.spec["repos"][str(env.project)]["status"] = branch(upstream=None, paths=["DIARY.md"])
    code, out, _ = env.run("end")
    assert code == 1
    assert tell(out) == ["git, garden-tools-code: 1 file uncommitted",
                         "DIARY.md has changes not committed: commit it before the handover"]


def test_at_the_end_the_diary_length_is_given_for_the_handover(env):
    code, out, _ = env.run("end")
    assert code == 0
    assert out.splitlines()[0] == "== session-check end for garden-tools (mac), %s ==" % STAMP
    assert facts(out)[-1] == ("for the handover: DIARY.md is 10 lines "
                              "(lobster-mail handover --diary DIARY.md records it)")


def test_a_project_folder_that_is_not_a_git_repository_cannot_be_told(env):
    os.rename(env.project / ".git", env.tmp / "elsewhere.git")
    code, out, _ = env.run("start")
    assert code == 3
    assert tell(out) == [("git, garden-tools-code: not a git repository, so nothing about its "
                         "commits can be told")]
    assert "DIARY.md: 10 lines; no handover found to compare with" in facts(out)


def test_git_failing_is_said_with_its_own_words(env):
    del env.spec["repos"][str(env.project / "garden-tools")]
    code, out, _ = env.run("start")
    assert code == 3
    assert tell(out) == [("git, garden-tools-code/garden-tools: git status failed: "
                         "fatal: not a git repository")]


def test_no_git_at_all_cannot_be_told_and_the_rest_is_still_printed(env, monkeypatch):
    empty = env.tmp / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    code, out, _ = env.run("start")
    assert code == 3
    assert tell(out) == ["git was not found on PATH, so nothing about commits can be told"]
    assert "inbox/: nothing new" in facts(out)


def test_git_that_hangs_is_given_up_after_the_timeout(env, monkeypatch):
    monkeypatch.setattr(check, "GIT_TIMEOUT", 2)
    env.spec["hang"] = True
    code, out, _ = env.run("start")
    assert code == 3
    assert tell(out)[0] == ("git, garden-tools-code: git status gave no answer in 2 seconds, "
                            "so nothing about its commits can be told")


# Folders

def test_in_the_device_shell_a_claw_absent_from_mnt_is_named(env):
    (env.project / "lobster.conf").write_text(
        "SELF=garden-tools\nSISTER=garden\nCLAWS=word-tools\nFOLDERS=~/models/kokoro\n",
        encoding="utf-8")
    mnt = env.home / "mnt"
    for name in ("garden", "kokoro", "mail", "lobster-tools"):
        (mnt / name).mkdir(parents=True)
    code, out, _ = env.run("start", session="device")
    assert code == 1
    assert tell(out) == ["folder missing: CLAWS word-tools, expected at %s"
                         % (mnt / "word-tools")]
    assert "folder reachable: SISTER garden (%s)" % (mnt / "garden") in facts(out)
    assert "folder reachable: FOLDERS kokoro (%s)" % (mnt / "kokoro") in facts(out)


def test_on_the_mac_the_named_folders_are_looked_for_at_their_real_paths(env):
    (env.project / "lobster.conf").write_text(
        "SELF=garden-tools\nCLAWS=word-tools\nFOLDERS='~/models/kokoro ~/big'\n",
        encoding="utf-8")
    (env.home / "big").mkdir()
    code, out, _ = env.run("start")
    assert code == 1
    assert tell(out) == ["folder missing: FOLDERS %s, expected at %s"
                         % (env.home / "models" / "kokoro", env.home / "models" / "kokoro")]
    assert "folder reachable: FOLDERS %s (%s)" % (env.home / "big", env.home / "big") in facts(out)


# Leftovers

def test_ignored_pycache_folders_are_a_fact_and_those_not_ignored_are_told(env):
    for folder in ("garden-tools/pkg/__pycache__", "garden-tools/tests/__pycache__",
                   "loose/__pycache__", "garden-tools/.venv/lib/__pycache__",
                   "_to_delete/old/__pycache__"):
        (env.project / folder).mkdir(parents=True)
    env.spec["repos"][str(env.project / "garden-tools")]["ignored"] = ["pkg/__pycache__",
                                                                      "tests/__pycache__"]
    code, out, _ = env.run("start")
    assert code == 1
    assert tell(out) == [("__pycache__: 1 folder not ignored by git: loose/__pycache__ "
                         "(removing it needs the person's OK)")]
    assert "__pycache__: 2 folders ignored by git" in facts(out)


def test_locks_are_looked_at_only_where_the_project_keeps_tickets(env):
    (env.project / "backlog" / ".locks" / "task-1.lock").mkdir(parents=True)
    _, out, _ = env.run("start")
    assert "backlog" not in out
    (env.project / "backlog" / "config.yml").write_text("project_name: x\n", encoding="utf-8")
    code, out, _ = env.run("start")
    assert code == 1
    assert tell(out) == [("backlog/.locks/ is not empty: task-1.lock (removing it needs the "
                         "person's OK)")]
    os.rename(env.project / "backlog" / ".locks" / "task-1.lock", env.tmp / "task-1.lock")
    code, out, _ = env.run("start")
    assert code == 0
    assert "backlog/.locks/: empty" in facts(out)


def test_to_delete_is_counted_with_its_size_and_the_newest(env):
    td = env.project / "_to_delete"
    (td / "before-split").mkdir(parents=True)
    (td / "before-split" / "CLAUDE.md").write_bytes(b"x" * 1200)
    (td / "old diary.md").write_bytes(b"y" * 300)
    os.utime(td / "old diary.md")       # touches times; the newest is the last one moved in
    (env.tmp / "late").mkdir()
    os.rename(env.tmp / "late", td / "late-arrival")
    code, out, _ = env.run("start")
    assert code == 0
    assert "_to_delete/: 3 things, 1.5 kB; put there last: late-arrival" in facts(out)


# The diary

def test_a_diary_shorter_than_the_last_handover_said_is_the_first_line(env):
    env.spec["repos"][str(env.project / "garden-tools")]["status"] = branch(ahead=1)
    env.handover("Where I stopped. DIARY.md's length: 2,383 lines.\n")
    code, out, _ = env.run("start")
    assert code == 1
    assert out.splitlines()[1:3] == [
        "-- To tell the person you work for (2):",
        ("DIARY.md is shorter than the last handover said: 10 lines now, 2383 then. Tell the "
        "person before writing anything in it."),
    ]


def test_a_handover_that_gave_no_length_is_said(env):
    env.handover("Nothing in progress.\n")
    _, out, _ = env.run("start")
    assert "DIARY.md: 10 lines; the last handover gave no length" in facts(out)


def test_the_newest_handover_is_the_one_compared(env, monkeypatch):
    monkeypatch.setenv("LOBSTER_MAIL_NOW", "2026-10-09T10:00:00+01:00")
    env.handover("DIARY.md is 2 lines.\n")
    monkeypatch.setenv("LOBSTER_MAIL_NOW", NOW)
    env.handover("DIARY.md is 9 lines.\n")
    _, out, _ = env.run("start")
    assert "DIARY.md: 10 lines; the last handover gave 9" in facts(out)


def test_a_project_with_no_diary_says_so(env):
    os.rename(env.project / "DIARY.md", env.tmp / "DIARY.md")
    code, out, _ = env.run("start")
    assert code == 0
    assert "DIARY.md: none in the project folder" in facts(out)


def test_a_mailbox_that_does_not_exist_cannot_be_told(env):
    (env.project / "lobster.conf").write_text("SELF=nobody-here\n", encoding="utf-8")
    code, out, _ = env.run("start")
    assert code == 3
    assert tell(out) == ["the mailbox nobody-here could not be read, so the diary cannot be "
                         "compared with the last handover: no mailbox nobody-here in %s "
                         "(lobster-mail init nobody-here makes one)" % env.root]


# What waits

def test_new_inbox_items_and_undecided_dreams_are_counted(env):
    (env.project / "inbox" / "notes from me.md").write_text("x", encoding="utf-8")
    (env.project / "inbox" / "data").mkdir()
    (env.project / "inbox" / "done").mkdir()
    (env.project / "inbox" / ".DS_Store").write_text("x", encoding="utf-8")
    (env.project / "dreams" / "2026-11-08-one.md").write_text("x", encoding="utf-8")
    (env.project / "dreams" / "done").mkdir()
    code, out, _ = env.run("start")
    assert code == 0
    assert "inbox/: 2 new: data, notes from me.md" in facts(out)
    assert "dreams/: 1 undecided" in facts(out)


# lobster.conf

def test_no_lobster_conf_cannot_be_told_and_the_rest_is_printed(env):
    os.rename(env.project / "lobster.conf", env.tmp / "lobster.conf")
    code, out, _ = env.run("start")
    assert code == 3
    assert tell(out) == ["no lobster.conf in %s, so the folders this session should reach cannot "
                         "be told" % env.project]
    assert out.splitlines()[0] == "== session-check start for garden-tools (mac), %s ==" % STAMP
    assert "git, garden-tools-code: nothing uncommitted" in facts(out)


def test_names_with_spaces_and_accents_and_a_conf_with_comments_and_quotes(env):
    project = env.tmp / "jardín tools-code"
    os.rename(env.project, project)
    env.spec = {"repos": {str(project): dict(LOCAL), str(project / "garden-tools"): dict(LEVEL)}}
    (project / "lobster.conf").write_text(
        '# a comment\nSELF="garden-tools"\n  # another\nFOLDERS=\n', encoding="utf-8")
    code, out, _ = env.run("start", project_dir=project)
    assert code == 0
    assert "git, jardín tools-code/garden-tools: nothing uncommitted" in facts(out)


# Reads only

def tree(folder):
    found = {}
    for here, dirs, files in os.walk(folder):
        for name in dirs + files:
            path = os.path.join(here, name)
            data = b"" if os.path.isdir(path) else pathlib.Path(path).read_bytes()
            found[os.path.relpath(path, folder)] = hashlib.sha256(data).hexdigest()
    return found


def test_the_project_and_the_mail_are_byte_for_byte_the_same_and_git_only_read(env):
    (env.project / "garden-tools" / "pkg" / "__pycache__").mkdir(parents=True)
    (env.project / "backlog" / ".locks" / "x").mkdir(parents=True)
    (env.project / "backlog" / "config.yml").write_text("x\n", encoding="utf-8")
    checkout = env.spec["repos"][str(env.project / "garden-tools")]
    checkout["status"], checkout["log"] = branch(ahead=1), "250c951 One\n"
    checkout["stashes"] = [STASH_0]
    for repo in (env.project, env.project / "garden-tools"):
        (repo / ".git" / "refs").mkdir()
        (repo / ".git" / "refs" / "stash").write_text("9f1e2d3\n", encoding="utf-8")
        (repo / ".git" / "logs" / "refs").mkdir(parents=True)
        (repo / ".git" / "logs" / "refs" / "stash").write_text("0 9f1e2d3 t 1 +0000\tx\n",
                                                               encoding="utf-8")
    env.handover("DIARY.md is 10 lines.\n")
    before = (tree(env.project), tree(env.root))
    env.run("start")
    env.run("end")
    assert (tree(env.project), tree(env.root)) == before
    verbs = {c["args"][2] for c in env.calls()}
    assert verbs <= {"status", "remote", "log", "check-ignore", "stash"}
    assert verbs == {"status", "remote", "log", "check-ignore", "stash"}
    stash_calls = {tuple(c["args"][3:]) for c in env.calls() if c["args"][2] == "stash"}
    assert stash_calls == {("list", "--format=%gd%x00%ci%x00%gs")}
    assert {c["locks"] for c in env.calls()} == {"0"}
    assert all(c["args"][0] == "-C" for c in env.calls())


def test_run_git_refuses_any_verb_not_on_the_reading_list():
    with pytest.raises(ValueError):
        check.run_git("/nowhere", ["commit", "-m", "x"])


@pytest.mark.parametrize("args", [["stash"], ["stash", "pop"], ["stash", "drop"], ["stash", "clear"],
                                  ["stash", "push"], ["stash", "apply"], ["stash", "--", "list"]])
def test_run_git_refuses_every_stash_verb_but_list(args):
    with pytest.raises(ValueError):
        check.run_git("/nowhere", args)


def test_run_git_runs_stash_list(env):
    env.spec["repos"][str(env.project)]["stashes"] = [["stash@{0}", "2026-11-01 09:30:00 +0000",
                                                       "On main: x"]]
    (env.tmp / "git-spec.json").write_text(json.dumps(env.spec), encoding="utf-8")
    code, out, error = check.run_git(str(env.project), ["stash", "list"])
    assert (code, out, error) == (0, b"stash@{0}\x002026-11-01 09:30:00 +0000\x00On main: x\n", "")


# The command line

def test_help_names_both_moments_and_the_session(env, capsys):
    with pytest.raises(SystemExit) as exit_:
        check.main(["--help"])
    assert exit_.value.code == 0
    out = capsys.readouterr().out
    assert "usage: session-check" in out
    assert "{start,end}" in out and "--session {mac,device}" in out


@pytest.mark.parametrize("argv, words", [
    (["start"], "--session"),
    (["later", "--session", "mac"], "invalid choice"),
    (["start", "--session", "phone"], "invalid choice"),
])
def test_wrong_arguments_are_exit_2(argv, words, capsys):
    with pytest.raises(SystemExit) as exit_:
        check.main(argv)
    assert exit_.value.code == 2
    assert words in capsys.readouterr().err


def test_the_session_can_come_from_the_environment(env, monkeypatch):
    monkeypatch.setenv("LOBSTER_MAIL_SESSION", "mac")
    (env.tmp / "git-spec.json").write_text(json.dumps(env.spec), encoding="utf-8")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = check.main(["start", "--root", str(env.root), "--project", str(env.project)])
    assert code == 0
    assert "(mac)" in out.getvalue().splitlines()[0]


def test_a_project_folder_that_does_not_exist_is_exit_2(env):
    code, out, err = env.run("start", project_dir=env.tmp / "no-such-project")
    assert (code, out) == (2, "")
    assert err == "session-check: the project folder %s does not exist\n" % (
        env.tmp / "no-such-project")


def test_the_project_is_the_working_folder_when_none_is_given(env, monkeypatch):
    monkeypatch.chdir(env.project)
    (env.tmp / "git-spec.json").write_text(json.dumps(env.spec), encoding="utf-8")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = check.main(["start", "--session", "mac", "--root", str(env.root)])
    assert code == 0
    assert "git, garden-tools-code: nothing uncommitted" in out.getvalue()


def test_as_names_the_mailbox_over_lobster_conf(env):
    (env.project / "lobster.conf").write_text("SELF=other\n", encoding="utf-8")
    code, out, _ = env.run("start", "--as", "garden-tools")
    assert code == 0
    assert "for garden-tools (mac)" in out


# Paths found by the coverage report

def test_a_lobster_conf_that_cannot_be_read_cannot_be_told(env):
    (env.project / "lobster.conf").write_text("SELF=garden-tools\nthis is not a setting\n",
                                              encoding="utf-8")
    code, out, _ = env.run("start")
    assert code == 3
    assert tell(out) == [("lobster.conf could not be read (line 2 of the config file is not "
                         "KEY=value: 'this is not a setting'), so the folders this session should "
                         "reach cannot be told")]


def test_at_the_end_a_log_that_fails_still_leaves_the_count(env):
    env.spec["repos"][str(env.project / "garden-tools")]["status"] = branch(ahead=2)
    code, out, _ = env.run("end")
    assert code == 1
    assert tell(out) == ["git, garden-tools-code/garden-tools: 2 commits not pushed to origin/main"]


def test_without_git_the_pycache_folders_are_counted_but_not_judged(env, monkeypatch):
    (env.project / "garden-tools" / "pkg" / "__pycache__").mkdir(parents=True)
    (env.project / "loose" / "__pycache__").mkdir(parents=True)
    empty = env.tmp / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    _, out, _ = env.run("start")
    assert "__pycache__: 2 folders (whether git ignores them cannot be told)" in facts(out)


def test_no_mail_root_is_said_with_what_to_do(env):
    (env.tmp / "git-spec.json").write_text(json.dumps(env.spec), encoding="utf-8")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = check.main(["start", "--session", "mac", "--project", str(env.project)])
    assert code == 3
    assert tell(out.getvalue()) == [
        ("the mailbox garden-tools could not be read, so the diary cannot be compared with the "
        "last handover: no mail root: give --root DIR, or set LOBSTER_MAIL_ROOT, or put "
        "MAIL_ROOT=~/projects/mail in ~/.lobster-tools.conf (or connect the mail folder so that "
        "~/mnt/mail exists)")]
    assert not any(x.startswith("folder") for x in facts(out.getvalue()))


def test_only_a_message_from_the_mailbox_to_itself_counts_as_a_handover(env, monkeypatch):
    assert mail.main(["init", "neighbour", "--root", str(env.root)]) == 0
    env.handover("DIARY.md is 9 lines.\n")
    monkeypatch.setenv("LOBSTER_MAIL_NOW", "2026-10-10T11:00:00+01:00")
    with contextlib.redirect_stdout(io.StringIO()):
        assert mail.main(["send", "--root", str(env.root), "--as", "garden-tools", "--to",
                          "neighbour", "--subject", "Request 01", "-"],
                         stdin=io.StringIO("DIARY.md is 99 lines.\n")) == 0
    (env.root / "garden-tools" / "sent" / "notes.txt").write_text("DIARY.md is 77 lines\n",
                                                                  encoding="utf-8")
    _, out, _ = env.run("start")
    assert "DIARY.md: 10 lines; the last handover gave 9" in facts(out)


def test_the_diary_lines_header_a_handover_wrote_is_read_back(env):
    diary = env.tmp / "then.md"
    diary.write_bytes(b"x\n" * 12)
    env.handover("DIARY.md is 3 lines, says the text.\n", diary=str(diary))
    code, out, _ = env.run("start")
    assert code == 1
    assert tell(out)[0].startswith("DIARY.md is shorter than the last handover said: 10 lines "
                                   "now, 12 then.")


# Stashes (Request 17; PLAN.md "`session-check` reports any stash")

def test_two_stashes_in_the_checkout_are_told_newest_first_and_make_exit_1(env):
    env.spec["repos"][str(env.project / "garden-tools")]["stashes"] = [STASH_0, STASH_1]
    env.handover("DIARY.md is 10 lines.\n")
    code, out, err = env.run("start")
    assert (code, err) == (1, "")
    assert tell(out) == [
        ("git, garden-tools-code/garden-tools: stash@{0}: WIP on main: 250c951 Two "
        "(made 2026-11-02 08:15:00 +0000)"),
        ("git, garden-tools-code/garden-tools: stash@{1}: On main: café notes, \"quoted\" $HOME "
        "(made 2026-11-01 09:30:00 +0100)"),
    ]
    assert "git, garden-tools-code: no stash" in facts(out)
    assert not any("garden-tools-code/garden-tools: no stash" in x for x in facts(out))


def test_a_stash_in_the_outer_folder_is_named_with_that_folder(env):
    env.spec["repos"][str(env.project)]["stashes"] = [STASH_0]
    env.handover("DIARY.md is 10 lines.\n")
    code, out, err = env.run("start")
    assert (code, err) == (1, "")
    assert tell(out) == [("git, garden-tools-code: stash@{0}: WIP on main: 250c951 Two "
                         "(made 2026-11-02 08:15:00 +0000)")]
    assert "git, garden-tools-code/garden-tools: no stash" in facts(out)


def test_at_the_end_a_stash_line_says_to_put_it_back_or_say_why_it_is_left(env):
    env.spec["repos"][str(env.project / "garden-tools")]["stashes"] = [STASH_0]
    env.handover("DIARY.md is 10 lines.\n")
    code, out, err = env.run("end")
    assert (code, err) == (1, "")
    assert tell(out) == [
        ("git, garden-tools-code/garden-tools: stash@{0}: WIP on main: 250c951 Two "
        "(made 2026-11-02 08:15:00 +0000): put it back before the handover, or tell the person it "
        "is being left and why")]


def test_a_stash_list_that_fails_cannot_be_told_and_the_rest_is_printed(env):
    env.spec["repos"][str(env.project)]["stash_fails"] = True
    env.handover("DIARY.md is 10 lines.\n")
    code, out, err = env.run("start")
    assert (code, err) == (3, "")
    assert tell(out) == [("git, garden-tools-code: git stash list failed: "
                         "fatal: stash list went wrong")]
    assert "git, garden-tools-code: no remote (local only)" in facts(out)
    assert "git, garden-tools-code/garden-tools: no stash" in facts(out)
    assert not any(x == "git, garden-tools-code: no stash" for x in facts(out))


def test_a_stash_list_that_hangs_is_given_up_after_the_timeout(env, monkeypatch):
    monkeypatch.setattr(check, "GIT_TIMEOUT", 2)
    env.spec["repos"][str(env.project / "garden-tools")]["stash_hangs"] = True
    env.handover("DIARY.md is 10 lines.\n")
    code, out, err = env.run("start")
    assert (code, err) == (3, "")
    assert tell(out) == [("git, garden-tools-code/garden-tools: git stash list gave no answer in "
                         "2 seconds, so whether it has a stash cannot be told")]
    assert "git, garden-tools-code: no stash" in facts(out)
