"""CLAUDE.md non-negotiable 1: the package never deletes and never runs anything, but for the one
exception settled for session-check (PLAN.md "Settled" 43): it runs git, with reading verbs only,
from run_git in check.py and nowhere else. Pinned by reading the source, before any test runs it."""
import pathlib
import re

PACKAGE = pathlib.Path(__file__).resolve().parents[2]
SOURCES = (sorted((PACKAGE / "lobstertools").glob("*.py"))
           + [PACKAGE / "lobster-mail", PACKAGE / "session-check"])
DELETE = re.compile(r"os\.remove\b|os\.unlink\b|shutil\.rmtree\b|\.unlink\(|\brmdir\b")
RUNS = re.compile(r"\bsubprocess\b|\bos\.system\b|\bos\.popen\b|\bos\.exec|\bos\.spawn")


def lines(path):
    return enumerate(path.read_text(encoding="utf-8").splitlines(), 1)


def test_the_source_names_no_delete():
    assert len(SOURCES) >= 6, SOURCES
    found = ["%s:%d: %s" % (p.name, n, t.strip()) for p in SOURCES for n, t in lines(p)
             if DELETE.search(t)]
    assert found == []


def test_nothing_but_check_py_names_a_way_to_run_a_program():
    found = ["%s:%d: %s" % (p.name, n, t.strip()) for p in SOURCES if p.name != "check.py"
             for n, t in lines(p) if RUNS.search(t)]
    assert found == []


def test_check_py_runs_a_program_only_inside_run_git():
    inside, outside = False, []
    for number, text in lines(PACKAGE / "lobstertools" / "check.py"):
        if re.match(r"(def |class )", text):
            inside = text.startswith("def run_git(")
        if RUNS.search(text) and not inside and text != "import subprocess":
            outside.append("check.py:%d: %s" % (number, text.strip()))
    assert outside == []


def test_run_git_keeps_to_the_reading_verbs():
    from lobstertools import check
    assert check.GIT_READING == ("status", "remote", "log", "check-ignore", "stash list")
