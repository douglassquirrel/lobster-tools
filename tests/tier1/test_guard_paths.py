"""The two easiest ways round script-guard are refused too ("Settled" 79): in a ganglion, a file
starting with #! run by its path from the project folder or a temporary folder; in a claw, a script
in a temporary folder, run by an interpreter or by its path."""
import pytest

from lobstertools.guard import judge


@pytest.fixture
def places(tmp_path, monkeypatch):
    project, temp, elsewhere = tmp_path / "project", tmp_path / "temp", tmp_path / "elsewhere"
    for folder in (project / "tools", project / "kept-scripts", temp, elsewhere):
        folder.mkdir(parents=True)
    for path in (project / "tools" / "run.sh", project / "kept-scripts" / "k.sh",
                 temp / "x.sh", elsewhere / "tool"):
        path.write_text("#!/bin/sh\necho hello\n")
    (project / "tools" / "binary").write_bytes(b"\xcf\xfa\xed\xfe")
    (temp / "binary").write_bytes(b"\xcf\xfa\xed\xfe")
    (temp / "x.py").write_text("print(1)\n")
    monkeypatch.setenv("TMPDIR", str(temp))
    monkeypatch.setenv("HOME", str(tmp_path))

    def run(command, kind):
        return judge(command, kind, project=str(project), cwd=str(project), temp=(str(temp),))
    run.temp, run.elsewhere = temp, elsewhere
    return run


def test_a_ganglion_refuses_a_hash_bang_file_run_by_its_path_from_the_project(places):
    for command in ("./tools/run.sh", "tools/run.sh a b", "X=1 ./tools/run.sh"):
        assert places(command, "non-code") == (
            "a script run by its path from the project or a temporary folder (%s)"
            % command.replace("X=1 ", "").split()[0])


def test_a_ganglion_refuses_one_from_a_temporary_folder_however_it_is_written(places):
    for written in (str(places.temp / "x.sh"), "$TMPDIR/x.sh", "${TMPDIR}/x.sh", "~/temp/x.sh"):
        assert places(written, "non-code") == (
            "a script run by its path from the project or a temporary folder (%s)" % written)


def test_a_ganglion_allows_a_tool_elsewhere_a_binary_a_missing_file_and_a_bare_name(places):
    for command in (str(places.elsewhere / "tool"), "./tools/binary", "./tools/missing.sh",
                    "run.sh", "nohup %s" % (places.elsewhere / "tool")):
        assert places(command, "non-code") is None, command


def test_a_ganglion_refuses_it_inside_a_wrapper_too(places):
    assert places("nohup ./tools/run.sh", "non-code") == (
        "a script run by its path from the project or a temporary folder (./tools/run.sh)")


def test_a_claw_refuses_a_script_in_a_temporary_folder_by_interpreter_or_by_path(places):
    temp = str(places.temp)
    assert places("python3 %s/x.py" % temp, "code") == (
        "a script in a temporary folder (%s/x.py)" % temp)
    assert places("python3 -u $TMPDIR/x.py", "code") == (
        "a script in a temporary folder ($TMPDIR/x.py)")
    assert places("sh %s/x.sh" % temp, "code") == "a script in a temporary folder (%s/x.sh)" % temp
    assert places("%s/x.sh" % temp, "code") == "a script in a temporary folder (%s/x.sh)" % temp
    assert places("python3 < $TMPDIR/x.py", "code") == (
        "a script in a temporary folder ($TMPDIR/x.py)")


def test_a_claw_allows_kept_scripts_and_its_own_files_and_a_binary_in_temp(places):
    for command in ("python3 kept-scripts/k.sh", "./kept-scripts/k.sh", "./tools/run.sh",
                    "sh kept-scripts/k.sh", "%s/binary" % places.temp, "python3 -m venv %s/v"
                    % places.temp):
        assert places(command, "code") is None, command


def test_the_default_temporary_folders_include_tmp_and_the_scratchpads_folder():
    assert judge("python3 /tmp/x.py", "code", temp=None) == "a script in a temporary folder (/tmp/x.py)"
    assert judge("python3 /private/var/folders/ab/T/x.py", "code", temp=None) == (
        "a script in a temporary folder (/private/var/folders/ab/T/x.py)")
