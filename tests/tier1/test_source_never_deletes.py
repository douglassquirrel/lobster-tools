"""CLAUDE.md non-negotiable 1: the package never deletes and never runs anything, but for the two
exceptions settled: session-check runs git, with reading verbs only, from run_git in check.py and
nowhere else (PLAN.md "Settled" 43); prepare-venv runs `python3 -m venv`, the venv's `pip install -r`
and its import check, from run_program in prepare.py and nowhere else ("Settled" 49); fetch-deb runs
`apt-get download` and `dpkg-deb -x`, from run_program in fetchdeb.py and nowhere else ("Settled"
54). Pinned by reading the source, before any test runs it."""
import pathlib
import re

PACKAGE = pathlib.Path(__file__).resolve().parents[2]
SOURCES = (sorted((PACKAGE / "lobstertools").glob("*.py"))
           + [PACKAGE / "lobster-mail", PACKAGE / "session-check", PACKAGE / "prepare-venv", PACKAGE / "fetch-deb"])
DELETE = re.compile(r"os\.remove\b|os\.unlink\b|shutil\.rmtree\b|\.unlink\(|\brmdir\b")
RUNS = re.compile(r"\bsubprocess\b|\bos\.system\b|\bos\.popen\b|\bos\.exec|\bos\.spawn")


def lines(path):
    return enumerate(path.read_text(encoding="utf-8").splitlines(), 1)


def test_the_source_names_no_delete():
    assert len(SOURCES) >= 6, SOURCES
    found = ["%s:%d: %s" % (p.name, n, t.strip()) for p in SOURCES for n, t in lines(p)
             if DELETE.search(t)]
    assert found == []


def test_nothing_but_check_py_and_prepare_py_names_a_way_to_run_a_program():
    found = ["%s:%d: %s" % (p.name, n, t.strip()) for p in SOURCES
             if p.name not in ("check.py", "prepare.py", "fetchdeb.py")
             for n, t in lines(p) if RUNS.search(t)]
    assert found == []


def runs_outside(name, function):
    inside, outside = False, []
    for number, text in lines(PACKAGE / "lobstertools" / name):
        if re.match(r"(def |class )", text):
            inside = text.startswith("def %s(" % function)
        if RUNS.search(text) and not inside and text != "import subprocess":
            outside.append("%s:%d: %s" % (name, number, text.strip()))
    return outside


def test_check_py_runs_a_program_only_inside_run_git():
    assert runs_outside("check.py", "run_git") == []


def test_fetchdeb_py_runs_a_program_only_inside_run_program():
    assert runs_outside("fetchdeb.py", "run_program") == []
    assert "subprocess.run(" in (PACKAGE / "lobstertools" / "fetchdeb.py").read_text("utf-8")


def test_prepare_py_runs_a_program_only_inside_run_program():
    assert runs_outside("prepare.py", "run_program") == []
    assert "subprocess.run(" in (PACKAGE / "lobstertools" / "prepare.py").read_text("utf-8")


def test_run_git_keeps_to_the_reading_verbs():
    from lobstertools import check
    assert check.GIT_READING == ("status", "remote", "log", "check-ignore", "stash list")


ALLOWED = [["/usr/bin/python3", "-m", "venv", "--system-site-packages", "/v"],
           ["/v/bin/python", "-m", "pip", "install", "-r", "/p/requirements.txt"],
           ["/v/bin/python", "-c", "import numpy, PIL.Image"]]
REFUSED = [["rm", "-rf", "/"],
           ["/v/bin/python", "-c", "print(1)"],
           ["/v/bin/python", "-c", "import os; os.system('x')"],
           ["/v/bin/python", "-m", "pip", "uninstall", "-y", "numpy"],
           ["/v/bin/python", "-m", "pip", "install", "numpy"],
           ["/v/bin/python", "-m", "pip", "install", "-r", "/p/r.txt", "--extra"],
           ["/usr/bin/python3", "-m", "venv", "--clear", "/v"],
           ["/usr/bin/python3", "-m", "venv", "--system-site-packages", "/v", "/w"],
           ["/v/bin/python", "script.py"]]


def test_run_program_takes_only_the_three_argument_lists():
    from lobstertools import prepare
    assert [prepare.allowed(argv) for argv in ALLOWED] == [True, True, True]
    assert [prepare.allowed(argv) for argv in REFUSED] == [False] * len(REFUSED)


def test_run_program_refuses_anything_else_before_running_it():
    from lobstertools import prepare
    for argv in REFUSED:
        try:
            prepare.run_program(argv)
        except ValueError as error:
            assert str(error).startswith("prepare-venv runs only")
        else:
            raise AssertionError("ran %r" % argv)


FETCH_ALLOWED = [["/usr/bin/apt-get", "download", "librsvg2-bin", "librsvg2-2"],
                 ["/usr/bin/dpkg-deb", "-x", "/w/d/librsvg2-2_1.0_arm64.deb", "/w/root"]]
FETCH_REFUSED = [["/usr/bin/apt-get", "install", "librsvg2-bin"],
                 ["/usr/bin/apt-get", "download"],
                 ["/usr/bin/apt-get", "download", "-o", "Dir=/x"],
                 ["/usr/bin/apt-get", "download", "x;rm"],
                 ["/usr/bin/dpkg-deb", "-x", "/w/a.deb"],
                 ["/usr/bin/dpkg-deb", "--build", "/w/a", "/w/b"],
                 ["/usr/bin/dpkg", "-i", "/w/a.deb"],
                 ["rm", "-rf", "/"]]


def test_fetch_deb_runs_only_its_two_argument_lists():
    from lobstertools import fetchdeb
    assert [fetchdeb.allowed(a) for a in FETCH_ALLOWED] == [True, True]
    assert [fetchdeb.allowed(a) for a in FETCH_REFUSED] == [False] * len(FETCH_REFUSED)
    for argv in FETCH_REFUSED:
        try:
            fetchdeb.run_program(argv)
        except ValueError as error:
            assert str(error).startswith("fetch-deb runs only")
        else:
            raise AssertionError("ran %r" % argv)

