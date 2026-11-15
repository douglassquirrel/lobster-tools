"""prepare-venv against an invented project and the stand-in python3 in tests/stubs/ (Request 01
from training-video-tools; PLAN.md "`prepare-venv`"). The stand-in records every call and fakes
`-m venv`, the import check and `-m pip install`; no real venv, no pip, no network."""
import contextlib
import hashlib
import io
import os
import pathlib
import shlex
import stat
import subprocess
import sys

import pytest

from lobstertools import prepare

HERE = pathlib.Path(__file__).resolve().parent
STUB = HERE.parent / "stubs" / "python3"
COMMAND = HERE.parents[1] / "prepare-venv"
IMPORT = "import cairo, numpy, kokoro_onnx"
PROJECT_FILE = ("# an invented tools project\n"
                "ENV_PREFIX=DEMO_TOOLS\n"
                "REQUIREMENTS=requirements-linux.txt\n"
                "IMPORTS=cairo numpy kokoro_onnx\n"
                "MODEL_FILES=model.onnx voices.npz\n"
                "MODEL_SETTING=SPEECH_MODEL_DIR\n"
                "MODEL_HELP=the README's \"Speech model\"\n")
PACKAGES_ONLY = "ENV_PREFIX=PLAIN\nREQUIREMENTS=requirements.txt\nIMPORTS=numpy\n"
HOSTILE = "it's \"q\" $HOME `x` \\ café"


@pytest.fixture(scope="module", autouse=True)
def stand_in_is_never_written_over():
    before = hashlib.sha256(STUB.read_bytes()).hexdigest()
    yield
    assert hashlib.sha256(STUB.read_bytes()).hexdigest() == before, "the shared stand-in changed"


class Scene:
    """An invented project, a venv, model and config path outside it, and the stand-in on PATH."""

    def __init__(self, tmp_path, name="demo-tools"):
        self.tmp = tmp_path
        self.project = tmp_path / name
        self.project.mkdir()
        (self.project / "prepare-venv.conf").write_text(PROJECT_FILE, encoding="utf-8")
        (self.project / "requirements-linux.txt").write_text("numpy\n", encoding="utf-8")
        self.venv = tmp_path / "venvs" / "demo"
        self.model = tmp_path / "models" / "kokoro"
        self.conf = tmp_path / "conf" / "demo-tools.conf"
        self.stub = tmp_path / "stub"
        self.stub.mkdir()

    @property
    def python(self):
        return str(self.venv / "bin" / "python")

    def model_in_place(self):
        self.model.mkdir(parents=True)
        for name in ("model.onnx", "voices.npz"):
            (self.model / name).write_bytes(b"invented")

    def flags(self, model=True, conf=True):
        return (["--project", str(self.project), "--venv", str(self.venv)]
                + (["--model", str(self.model)] if model else [])
                + (["--conf", str(self.conf)] if conf else []))

    def mark(self, name, text=""):
        (self.stub / name).write_text(text, encoding="utf-8")

    def calls(self):
        path = self.stub / "calls"
        if not path.exists():
            return []
        found, current = [], []
        for item in path.read_bytes().decode("utf-8").split("\0")[:-1]:
            if item == "--end--":
                found.append(current)
                current = []
            else:
                current.append(item)
        return found

    def venv_call(self):
        return [str(self.tmp / "bin" / "python3"), "-m", "venv", "--system-site-packages",
                str(self.venv)]

    def import_call(self, line=IMPORT):
        return [self.python, "-c", line]

    def pip_call(self, requirements="requirements-linux.txt"):
        return [self.python, "-m", "pip", "install", "-r", str(self.project / requirements)]

    def exports(self, conf=True, prefix="DEMO_TOOLS"):
        return prepare.export_lines(prefix, self.python, str(self.conf) if conf else None)


@pytest.fixture
def scene(tmp_path, monkeypatch):
    s = Scene(tmp_path)
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    os.symlink(str(STUB), str(bin_ / "python3"))
    monkeypatch.setenv("PATH", str(bin_) + os.pathsep + "/usr/bin:/bin")
    monkeypatch.setenv("PYSTUB_DIR", str(s.stub))
    monkeypatch.setenv("PYSTUB_FILE", str(STUB))
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return s


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = prepare.main([str(a) for a in argv])
        except SystemExit as exit_:
            code = exit_.code if isinstance(exit_.code, int) else 1
    return code, out.getvalue(), err.getvalue()


def lines(text):
    return text.splitlines()


# The first run and the second.

def test_the_first_run_makes_the_venv_installs_writes_the_config_and_prints_the_lines(scene):
    scene.model_in_place()
    code, out, err = run(*scene.flags())
    assert (code, lines(out)) == (0, scene.exports())
    assert scene.calls() == [scene.venv_call(), scene.import_call(), scene.pip_call(),
                             scene.import_call()]
    assert lines(err) == [
        "prepare-venv: made the venv at %s" % scene.venv,
        "prepare-venv: installed the packages in %s into %s"
        % (scene.project / "requirements-linux.txt", scene.venv),
        "prepare-venv: wrote %s" % scene.conf]
    assert scene.conf.read_text(encoding="utf-8") == "SPEECH_MODEL_DIR=%s\n" % scene.model


def test_the_second_run_runs_only_the_import_check_and_says_nothing(scene):
    scene.model_in_place()
    assert run(*scene.flags())[0] == 0
    before = scene.conf.stat().st_mtime_ns
    (scene.stub / "calls").unlink()
    code, out, err = run(*scene.flags())
    assert (code, lines(out), err) == (0, scene.exports(), "")
    assert scene.calls() == [scene.import_call()]
    assert scene.conf.stat().st_mtime_ns == before


def test_a_venv_made_by_hand_is_reused_and_only_installed_into(scene):
    scene.model_in_place()
    (scene.venv / "bin").mkdir(parents=True)
    os.symlink(str(STUB), scene.python)
    code, out, _ = run(*scene.flags())
    assert (code, lines(out)) == (0, scene.exports())
    assert scene.calls() == [scene.import_call(), scene.pip_call(), scene.import_call()]


def test_a_project_with_packages_only_needs_no_model_and_no_config(scene):
    (scene.project / "prepare-venv.conf").write_text(PACKAGES_ONLY, encoding="utf-8")
    (scene.project / "requirements.txt").write_text("numpy\n", encoding="utf-8")
    code, out, err = run(*scene.flags(model=False, conf=False))
    assert (code, lines(out)) == (0, scene.exports(conf=False, prefix="PLAIN"))
    assert scene.calls() == [scene.venv_call(), scene.import_call("import numpy"),
                             scene.pip_call("requirements.txt"), scene.import_call("import numpy")]
    assert "wrote" not in err


def test_a_model_setting_without_model_files_only_needs_the_folder(scene):
    (scene.project / "prepare-venv.conf").write_text(
        PROJECT_FILE.replace("MODEL_FILES=model.onnx voices.npz\n", ""), encoding="utf-8")
    scene.model.mkdir(parents=True)
    code, out, _ = run(*scene.flags())
    assert (code, lines(out)) == (0, scene.exports())


def test_relative_paths_are_made_absolute(scene, monkeypatch):
    scene.model_in_place()
    monkeypatch.chdir(scene.tmp)
    code, out, _ = run("--project", "demo-tools", "--venv", "venvs/demo", "--model",
                       "models/kokoro", "--conf", "conf/demo-tools.conf")
    assert (code, lines(out)) == (0, scene.exports())


# The checkout rule, before anything runs.

@pytest.mark.parametrize("where", ["venv", ".", "a/../b"])
def test_a_venv_inside_the_checkout_or_the_checkout_itself_is_refused_before_anything_runs(
        scene, where):
    venv = os.path.normpath(str(scene.project / where))
    code, out, err = run("--project", scene.project, "--venv", venv, "--model", scene.model,
                         "--conf", scene.conf)
    assert (code, out) == (2, "")
    assert err == ("prepare-venv: --venv %s is inside the checkout %s; make the venv outside it "
                   "(in a connected checkout it would shadow the project's own .venv)\n"
                   % (venv, scene.project))
    assert scene.calls() == []
    assert not scene.conf.exists()


# The project's file and the flags it calls for.

def test_a_project_without_the_file_is_refused(scene):
    (scene.project / "prepare-venv.conf").unlink()
    code, out, err = run(*scene.flags())
    assert (code, out) == (2, "")
    assert err == ("prepare-venv: %s has no prepare-venv.conf; a project that uses prepare-venv "
                   "keeps its own details there (README, \"prepare-venv\")\n" % scene.project)
    assert scene.calls() == []


def test_a_project_file_that_is_wrong_is_refused_in_words(scene):
    (scene.project / "prepare-venv.conf").write_text("ENV_PREFIX=X\nREQUIREMENTS=r.txt\n",
                                                     encoding="utf-8")
    code, out, err = run(*scene.flags())
    assert (code, out) == (2, "")
    assert err == ("prepare-venv: %s cannot be used: it has no IMPORTS line\n"
                   % (scene.project / "prepare-venv.conf"))
    assert scene.calls() == []


def test_a_project_file_that_is_not_text_is_refused_in_words(scene):
    (scene.project / "prepare-venv.conf").write_bytes(b"ENV_PREFIX=\xff\n")
    code, _, err = run(*scene.flags())
    assert code == 2
    assert err.startswith("prepare-venv: %s cannot be read: "
                          % (scene.project / "prepare-venv.conf"))


def test_a_missing_requirements_file_is_refused(scene):
    (scene.project / "requirements-linux.txt").unlink()
    code, out, err = run(*scene.flags())
    assert (code, out) == (2, "")
    assert err == ("prepare-venv: the requirements file %s, named by REQUIREMENTS in "
                   "prepare-venv.conf, does not exist\n"
                   % (scene.project / "requirements-linux.txt"))
    assert scene.calls() == []


def test_model_files_call_for_the_model_folder(scene):
    (scene.project / "prepare-venv.conf").write_text(
        PROJECT_FILE.replace("MODEL_SETTING=SPEECH_MODEL_DIR\n", ""), encoding="utf-8")
    code, _, err = run(*scene.flags(model=False, conf=False))
    assert code == 2
    assert err == ("prepare-venv: %s names model files (MODEL_FILES); give the model folder with "
                   "--model\n" % (scene.project / "prepare-venv.conf"))
    assert scene.calls() == []


@pytest.mark.parametrize("model, conf", [(False, True), (True, False), (False, False)])
def test_a_model_setting_calls_for_the_model_folder_and_the_config(scene, model, conf):
    code, _, err = run(*scene.flags(model=model, conf=conf))
    assert code == 2
    assert err == ("prepare-venv: %s names a model setting (MODEL_SETTING); give the model folder "
                   "with --model and the config file with --conf\n"
                   % (scene.project / "prepare-venv.conf"))


def test_a_model_folder_for_a_project_with_no_model_is_refused(scene):
    (scene.project / "prepare-venv.conf").write_text(PACKAGES_ONLY, encoding="utf-8")
    (scene.project / "requirements.txt").write_text("numpy\n", encoding="utf-8")
    code, _, err = run(*scene.flags(conf=False))
    assert code == 2
    assert err == ("prepare-venv: --model is given, but %s names no model (MODEL_FILES or "
                   "MODEL_SETTING)\n" % (scene.project / "prepare-venv.conf"))


def test_a_config_for_a_project_with_no_setting_is_refused(scene):
    (scene.project / "prepare-venv.conf").write_text(
        PROJECT_FILE.replace("MODEL_SETTING=SPEECH_MODEL_DIR\n", ""), encoding="utf-8")
    code, _, err = run(*scene.flags())
    assert code == 2
    assert err == ("prepare-venv: --conf is given, but %s names no setting to write in it "
                   "(MODEL_SETTING)\n" % (scene.project / "prepare-venv.conf"))


def test_a_model_folder_with_a_line_break_is_refused(scene):
    code, _, err = run("--project", scene.project, "--venv", scene.venv, "--model",
                       str(scene.model) + "\nX=1", "--conf", scene.conf)
    assert code == 2
    assert err == ("prepare-venv: --model holds a line break, which one line of a config file "
                   "cannot hold\n")
    assert scene.calls() == []


# The model check: after the venv and the config, so one run reports all it can. When it is the
# only failure the export lines are printed as well, still exit 3, since the venv and the config are
# good (Request 02 from training-video-tools, "Settled" 51).

def test_each_missing_model_file_is_named_after_the_venv_and_the_config_are_done(scene):
    scene.model.mkdir(parents=True)
    (scene.model / "voices.npz").write_bytes(b"x")
    code, out, err = run(*scene.flags())
    assert (code, lines(out)) == (3, scene.exports())
    assert lines(err)[-1] == ("prepare-venv: the model folder %s has no model.onnx; get it as the "
                              "README's \"Speech model\" says" % scene.model)
    assert len(scene.calls()) == 4
    assert scene.conf.read_text(encoding="utf-8") == "SPEECH_MODEL_DIR=%s\n" % scene.model


def test_a_missing_model_folder_is_one_message(scene):
    code, out, err = run(*scene.flags())
    assert (code, lines(out)) == (3, scene.exports())
    assert lines(err)[3:] == ["prepare-venv: the model folder %s does not exist; get the model as "
                              "the README's \"Speech model\" says" % scene.model]


# The config.

def test_a_config_with_other_settings_keeps_them(scene):
    scene.model_in_place()
    scene.conf.parent.mkdir(parents=True)
    scene.conf.write_text("# mine\nVOICE=af_heart\n\nSPEED=1.1", encoding="utf-8")
    assert run(*scene.flags())[0] == 0
    assert scene.conf.read_text(encoding="utf-8") == (
        "# mine\nVOICE=af_heart\n\nSPEED=1.1\nSPEECH_MODEL_DIR=%s\n" % scene.model)


def test_a_config_naming_another_model_is_rewritten_in_place_and_keeps_its_mode(scene):
    scene.model_in_place()
    scene.conf.parent.mkdir(parents=True)
    scene.conf.write_text("A=1\nSPEECH_MODEL_DIR=/old/model\nB=2\n", encoding="utf-8")
    scene.conf.chmod(0o640)
    code, _, err = run(*scene.flags())
    assert code == 0
    assert scene.conf.read_text(encoding="utf-8") == "A=1\nSPEECH_MODEL_DIR=%s\nB=2\n" % scene.model
    assert stat.S_IMODE(scene.conf.stat().st_mode) == 0o640
    assert "prepare-venv: wrote %s" % scene.conf in lines(err)
    assert sorted(p.name for p in scene.conf.parent.iterdir()) == ["demo-tools.conf"]


def test_a_config_that_already_says_it_is_left_alone(scene):
    scene.model_in_place()
    scene.conf.parent.mkdir(parents=True)
    scene.conf.write_text("SPEECH_MODEL_DIR=\"%s\"\n" % scene.model, encoding="utf-8")
    before = scene.conf.stat().st_mtime_ns
    code, _, err = run(*scene.flags())
    assert code == 0
    assert scene.conf.stat().st_mtime_ns == before
    assert "wrote" not in err


@pytest.mark.parametrize("content", [b"A=1\nnot a setting\n", b"A=\xff\n"])
def test_a_config_that_cannot_be_used_is_refused_and_left_byte_for_byte(scene, content):
    scene.model_in_place()
    scene.conf.parent.mkdir(parents=True)
    scene.conf.write_bytes(content)
    code, out, err = run(*scene.flags())
    assert (code, out) == (3, "")
    assert lines(err)[-2] == ("prepare-venv: %s cannot be used as it is; fix it or name another "
                              "file with --conf:" % scene.conf)
    assert scene.conf.read_bytes() == content


def test_a_config_that_is_a_folder_is_refused(scene):
    scene.model_in_place()
    scene.conf.mkdir(parents=True)
    code, _, err = run(*scene.flags())
    assert code == 3
    assert ("prepare-venv: %s cannot be used as it is; fix it or name another file with --conf:"
            % scene.conf) in lines(err)


def test_a_config_that_cannot_be_written_is_reported_and_left_alone(scene):
    scene.model_in_place()
    scene.conf.parent.mkdir(parents=True)
    scene.conf.write_text("A=1\n", encoding="utf-8")
    scene.conf.parent.chmod(0o555)
    try:
        code, out, err = run(*scene.flags())
        assert (code, out) == (3, "")
        assert lines(err)[-1].startswith("prepare-venv: cannot write %s: " % scene.conf)
        assert scene.conf.read_text(encoding="utf-8") == "A=1\n"
        assert sorted(p.name for p in scene.conf.parent.iterdir()) == ["demo-tools.conf"]
    finally:
        scene.conf.parent.chmod(0o755)


# The dry run.

def test_a_dry_run_with_nothing_in_place_says_what_it_would_do_and_runs_nothing(scene):
    scene.model_in_place()
    code, out, err = run(*scene.flags(), "--dry-run")
    assert code == 0
    assert lines(out) == [
        "Would make the venv at %s" % scene.venv,
        "Would install the packages in %s into %s"
        % (scene.project / "requirements-linux.txt", scene.venv),
        "Would write %s with SPEECH_MODEL_DIR=%s" % (scene.conf, scene.model)] + scene.exports()
    assert (err, scene.calls()) == ("", [])
    assert not scene.venv.exists() and not scene.conf.exists()


def test_a_dry_run_with_everything_in_place_runs_only_the_import_check(scene):
    scene.model_in_place()
    assert run(*scene.flags())[0] == 0
    (scene.stub / "calls").unlink()
    code, out, err = run(*scene.flags(), "--dry-run")
    assert (code, lines(out), err) == (0, scene.exports(), "")
    assert scene.calls() == [scene.import_call()]


def test_a_dry_run_with_the_venv_but_not_the_packages(scene):
    scene.model_in_place()
    (scene.venv / "bin").mkdir(parents=True)
    os.symlink(str(STUB), scene.python)
    code, out, _ = run(*scene.flags(), "--dry-run")
    assert code == 0
    assert lines(out)[0] == ("Would install the packages in %s into %s"
                             % (scene.project / "requirements-linux.txt", scene.venv))
    assert scene.calls() == [scene.import_call()]


def test_a_dry_run_still_names_what_the_model_lacks_and_prints_the_lines(scene):
    code, out, err = run(*scene.flags(), "--dry-run")
    assert code == 3
    assert lines(out) == [
        "Would make the venv at %s" % scene.venv,
        "Would install the packages in %s into %s"
        % (scene.project / "requirements-linux.txt", scene.venv),
        "Would write %s with SPEECH_MODEL_DIR=%s" % (scene.conf, scene.model)] + scene.exports()
    assert "does not exist" in err
    assert scene.calls() == []


@pytest.mark.parametrize("trouble", ["pip-fails", "pip-useless", "unusable-config"])
def test_another_failure_with_the_model_missing_too_prints_no_lines(scene, trouble):
    if trouble == "unusable-config":
        scene.conf.parent.mkdir(parents=True)
        scene.conf.write_text("not a setting\n", encoding="utf-8")
    else:
        scene.mark(trouble, "ERROR: no\n")
    code, out, _ = run(*scene.flags())
    assert (code, out) == (3, "")


# Failures.

def test_a_failed_venv_is_reported_with_its_last_lines(scene):
    scene.mark("venv-fails", "".join("line %d\n" % n for n in range(1, 9))
               + "Error: ensurepip is not available\n")
    code, out, err = run(*scene.flags())
    assert (code, out) == (3, "")
    assert err == ("prepare-venv: %s -m venv --system-site-packages %s failed (exit 1); its last "
                   "lines:\n  line 5\n  line 6\n  line 7\n  line 8\n  Error: ensurepip is not "
                   "available\nFix that (the venv module and pip must work on this machine) and "
                   "run again\n" % (scene.tmp / "bin" / "python3", scene.venv))
    assert not scene.conf.exists()


def test_a_failed_install_is_reported_and_the_venv_is_kept(scene):
    scene.mark("pip-fails", "ERROR: Could not find a version that satisfies kokoro-onnx\n")
    code, out, err = run(*scene.flags())
    assert (code, out) == (3, "")
    assert lines(err)[1:] == [
        "prepare-venv: %s -m pip install -r %s failed (exit 1); its last lines:"
        % (scene.python, scene.project / "requirements-linux.txt"),
        "  ERROR: Could not find a version that satisfies kokoro-onnx",
        "Fix that (the network, or a package's build needs) and run again; the venv is kept"]
    assert os.path.islink(scene.python)
    (scene.stub / "pip-fails").unlink()
    (scene.stub / "calls").unlink()
    scene.model_in_place()
    assert run(*scene.flags())[0] == 0
    assert scene.calls() == [scene.import_call(), scene.pip_call(), scene.import_call()]


def test_packages_that_install_but_do_not_import_are_reported(scene):
    scene.mark("pip-useless")
    code, out, err = run(*scene.flags())
    assert (code, out) == (3, "")
    assert lines(err)[2:] == [
        "prepare-venv: the packages in %s are installed in %s, but `%s` still fails; its last "
        "lines:" % (scene.project / "requirements-linux.txt", scene.venv, IMPORT),
        "  ModuleNotFoundError: No module named 'stand_in'",
        "Check that REQUIREMENTS and IMPORTS in prepare-venv.conf agree"]


def test_no_python3_on_path_is_reported(scene, monkeypatch):
    monkeypatch.setenv("PATH", str(scene.tmp / "nothing"))
    code, out, err = run(*scene.flags())
    assert (code, out) == (3, "")
    assert err == ("prepare-venv: no python3 on PATH to make the venv with; install Python 3 or "
                   "put it on PATH\n")


# Paths a shell would split, and text that must stay data.

def test_hostile_paths_are_handed_over_as_they_are_and_quoted_in_the_lines(tmp_path, monkeypatch):
    s = Scene(tmp_path, name="proj " + HOSTILE)
    s.venv = tmp_path / ("venv " + HOSTILE)
    s.model = tmp_path / ("model " + HOSTILE)
    s.conf = tmp_path / ("conf " + HOSTILE) / "c.conf"
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    os.symlink(str(STUB), str(bin_ / "python3"))
    monkeypatch.setenv("PATH", str(bin_) + os.pathsep + "/usr/bin:/bin")
    monkeypatch.setenv("PYSTUB_DIR", str(s.stub))
    monkeypatch.setenv("PYSTUB_FILE", str(STUB))
    s.model_in_place()
    code, out, err = run(*s.flags())
    assert code == 0, err
    assert s.calls() == [s.venv_call(), s.import_call(), s.pip_call(), s.import_call()]
    exported = [shlex.split(line) for line in lines(out)]
    assert exported == [["export", "DEMO_TOOLS_PYTHON=" + s.python],
                        ["export", "DEMO_TOOLS_CONF=" + str(s.conf)],
                        ["export", "PYTHONDONTWRITEBYTECODE=1"]]
    assert s.conf.read_text(encoding="utf-8") == "SPEECH_MODEL_DIR=%s\n" % s.model


# The command-line surface.

def test_help_names_every_flag(scene):
    code, out, _ = run("--help")
    assert code == 0
    for flag in ("--project", "--venv", "--model", "--conf", "--dry-run"):
        assert flag in out
    assert "prepare-venv.conf" in out


def test_the_project_and_the_venv_are_required(scene):
    code, _, err = run("--venv", scene.venv)
    assert code == 2
    assert "--project" in err


def run_program(scene, *argv):
    env = dict(os.environ)
    return subprocess.run([sys.executable, str(COMMAND)] + [str(a) for a in argv],
                          check=False, capture_output=True, text=True, env=env,
                          cwd=str(scene.tmp))


def test_as_a_program_the_first_run_prints_only_the_lines(scene):
    scene.model_in_place()
    done = run_program(scene, *scene.flags())
    assert (done.returncode, lines(done.stdout)) == (0, scene.exports())
    assert lines(done.stderr)[0] == "prepare-venv: made the venv at %s" % scene.venv


def test_as_a_program_a_refusal_is_words_and_exit_2_never_a_traceback(scene):
    done = run_program(scene, "--project", scene.project, "--venv", scene.project / "v")
    assert done.returncode == 2
    assert "Traceback" not in done.stderr
    assert done.stderr.startswith("prepare-venv: --venv ")


def test_a_venv_python_that_cannot_be_started_is_reported_not_a_traceback(scene):
    (scene.venv / "bin").mkdir(parents=True)
    (scene.venv / "bin" / "python").write_text("not a program\n", encoding="utf-8")
    code, out, err = run(*scene.flags())
    assert (code, out) == (3, "")
    assert lines(err)[0] == ("prepare-venv: %s -m pip install -r %s failed (exit 127); its last "
                             "lines:" % (scene.python, scene.project / "requirements-linux.txt"))
    assert "Permission denied" in lines(err)[1]


def test_as_a_program_eval_in_sh_sets_the_variables_when_only_the_model_is_missing(scene):
    script = ('eval "$("$PV_PYTHON" "$PV" "$@")"; echo "exit=$?"; '
              'printf "%s\\n" "$DEMO_TOOLS_PYTHON" "$DEMO_TOOLS_CONF"')
    env = dict(os.environ, PV_PYTHON=sys.executable, PV=str(COMMAND))
    done = subprocess.run(["/bin/sh", "-c", script, "sh"] + scene.flags(), check=False,
                          capture_output=True, text=True, env=env, cwd=str(scene.tmp))
    assert lines(done.stdout) == ["exit=0", scene.python, str(scene.conf)]
    assert "does not exist" in done.stderr

