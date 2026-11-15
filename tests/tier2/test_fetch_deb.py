"""fetch-deb against stand-ins for apt-get and dpkg-deb in tests/stubs/ (Request 24 (a) from
training-video; PLAN.md "Settled" 54). No real apt, no network: the stand-ins record each call and
fake the download and the unpacking."""
import contextlib
import hashlib
import io
import os
import pathlib
import stat
import subprocess
import sys

import pytest

from lobstertools import fetchdeb

HERE = pathlib.Path(__file__).resolve().parent
STUBS = HERE.parent / "stubs"
COMMAND = HERE.parents[1] / "fetch-deb"
PACKAGES = ["librsvg2-bin", "librsvg2-2"]
CONTENTS = {"librsvg2-bin": "usr/bin/rsvg-convert\nusr/share/man/man1/rsvg-convert.1.gz\n",
            "librsvg2-2": "usr/lib/aarch64-linux-gnu/librsvg-2.so.2\n"
                          "usr/share/doc/librsvg2-2/copyright\n"}


@pytest.fixture(scope="module", autouse=True)
def stand_ins_are_never_written_over():
    names = ("apt-get", "dpkg-deb")
    before = {n: hashlib.sha256((STUBS / n).read_bytes()).hexdigest() for n in names}
    yield
    after = {n: hashlib.sha256((STUBS / n).read_bytes()).hexdigest() for n in names}
    assert after == before, "a shared stand-in changed"


class Scene:
    def __init__(self, tmp_path, into_name="work/rsvg"):
        self.tmp = tmp_path
        self.into = tmp_path / into_name
        self.stub = tmp_path / "stub"
        (self.stub / "contents").mkdir(parents=True)
        for name, text in CONTENTS.items():
            (self.stub / "contents" / name).write_text(text, encoding="utf-8")
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        for name in ("apt-get", "dpkg-deb"):
            os.symlink(str(STUBS / name), str(self.bin / name))

    @property
    def wrapper(self):
        return self.into / "bin" / "rsvg-convert"

    @property
    def root(self):
        return self.into / "root"

    def args(self, *more):
        return (["--into", str(self.into), "--program", "rsvg-convert", "--var", "RSVG_CONVERT"]
                + list(more) + PACKAGES)

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

    def downloads(self):
        return sorted(p for p in self.into.iterdir() if p.name.startswith("download-"))

    def export(self):
        return fetchdeb.export_line("RSVG_CONVERT", str(self.wrapper))


@pytest.fixture
def scene(tmp_path, monkeypatch):
    s = Scene(tmp_path)
    monkeypatch.setenv("PATH", str(s.bin) + os.pathsep + "/usr/bin:/bin")
    monkeypatch.setenv("DEBSTUB_DIR", str(s.stub))
    return s


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = fetchdeb.main([str(a) for a in argv])
        except SystemExit as exit_:
            code = exit_.code if isinstance(exit_.code, int) else 1
    return code, out.getvalue(), err.getvalue()


def lines(text):
    return text.splitlines()


def run_wrapper(wrapper, *args):
    done = subprocess.run([str(wrapper)] + list(args), capture_output=True, text=True,
                          env={"PATH": "/usr/bin:/bin"}, check=False)
    return done.returncode, lines(done.stdout)


# The first run and the second.

def test_the_first_run_downloads_unpacks_writes_the_wrapper_and_prints_the_line(scene):
    code, out, err = run(*scene.args())
    assert (code, lines(out)) == (0, [scene.export()])
    [download] = scene.downloads()
    calls = scene.calls()
    assert calls[0] == [str(scene.bin / "apt-get"), str(download), "download"] + PACKAGES
    assert calls[1:] == [[str(scene.bin / "dpkg-deb"), "-x",
                          str(download / ("%s_1.0-1_arm64.deb" % name)), str(scene.root)]
                         for name in sorted(PACKAGES)]
    assert lines(err) == [
        "fetch-deb: downloaded librsvg2-bin librsvg2-2 into %s" % download,
        "fetch-deb: unpacked them into %s" % scene.root,
        "fetch-deb: wrote %s" % scene.wrapper]
    assert stat.S_IMODE(scene.wrapper.stat().st_mode) == 0o755


def test_the_wrapper_runs_the_program_with_the_libraries_and_the_arguments(scene):
    assert run(*scene.args())[0] == 0
    code, output = run_wrapper(scene.wrapper, "--version", "a b")
    assert (code, output) == (0, ["LD=%s" % (scene.root / "usr" / "lib" / "aarch64-linux-gnu"),
                                  "--version", "a b"])


def test_the_second_run_runs_nothing_and_says_nothing(scene):
    assert run(*scene.args())[0] == 0
    (scene.stub / "calls").unlink()
    code, out, err = run(*scene.args())
    assert (code, lines(out), err) == (0, [scene.export()], "")
    assert scene.calls() == []
    assert len(scene.downloads()) == 1


def test_a_wrapper_without_its_program_is_made_again(scene):
    assert run(*scene.args())[0] == 0
    os.rename(str(scene.root), str(scene.into / "moved-aside"))
    code, out, _ = run(*scene.args())
    assert (code, lines(out)) == (0, [scene.export()])
    assert len(scene.downloads()) == 2


# The dry run.

def test_a_dry_run_says_what_it_would_do_and_makes_nothing(scene):
    code, out, err = run(*scene.args("--dry-run"))
    assert (code, err) == (0, "")
    assert lines(out) == [
        "Would download librsvg2-bin librsvg2-2 into a new download- folder in %s" % scene.into,
        "Would unpack them into %s and write %s" % (scene.root, scene.wrapper),
        scene.export()]
    assert scene.calls() == [] and not scene.into.exists()


def test_a_dry_run_with_everything_in_place_prints_only_the_line(scene):
    assert run(*scene.args())[0] == 0
    (scene.stub / "calls").unlink()
    code, out, _ = run(*scene.args("--dry-run"))
    assert (code, lines(out), scene.calls()) == (0, [scene.export()], [])


# Failures: non-zero, apt's or dpkg's last lines, nothing in DIR/bin.

def test_a_failed_download_is_reported_and_nothing_is_written_in_bin(scene):
    scene.mark("apt-fails", "Reading package lists...\nE: Unable to locate package librsvg2-bin\n")
    code, out, err = run(*scene.args())
    assert (code, out) == (3, "")
    [download] = scene.downloads()
    assert err == ("fetch-deb: %s download librsvg2-bin librsvg2-2 failed (exit 100); its last "
                   "lines:\n  Reading package lists...\n  E: Unable to locate package "
                   "librsvg2-bin\nCheck the package names and the network, and run again; the "
                   "download folder %s is left as it is, and nothing was written in %s\n"
                   % (scene.bin / "apt-get", download, scene.into / "bin"))
    assert not (scene.into / "bin").exists()
    assert len(scene.calls()) == 1


def test_a_download_that_misses_a_package_is_reported(scene):
    scene.mark("apt-skips-librsvg2-2")
    code, out, err = run(*scene.args())
    assert (code, out) == (3, "")
    assert lines(err)[-1] == ("fetch-deb: apt-get download gave 1 file for 2 packages "
                              "(librsvg2-bin_1.0-1_arm64.deb); nothing was written in %s"
                              % (scene.into / "bin"))
    assert not scene.wrapper.exists()


def test_a_failed_unpacking_is_reported_and_nothing_is_written_in_bin(scene):
    scene.mark("dpkg-fails")
    code, out, err = run(*scene.args())
    assert (code, out) == (3, "")
    assert "dpkg-deb: error: stand-in failure" in err
    assert lines(err)[-1].endswith("nothing was written in %s" % (scene.into / "bin"))
    assert not scene.wrapper.exists()


def test_packages_without_the_program_are_reported(scene):
    code, out, err = run("--into", scene.into, "--program", "rsvg-view", "--var", "V", *PACKAGES)
    assert (code, out) == (3, "")
    assert lines(err)[-1] == ("fetch-deb: the packages unpacked into %s hold no rsvg-view in "
                              "usr/bin, bin, usr/sbin, sbin or usr/local/bin; nothing was written "
                              "in %s" % (scene.root, scene.into / "bin"))


def test_a_download_that_hangs_is_given_up(scene, monkeypatch):
    monkeypatch.setattr(fetchdeb, "TIMEOUT", 0.5)
    scene.mark("apt-hangs")
    code, out, err = run(*scene.args())
    assert (code, out) == (3, "")
    assert lines(err)[0].startswith("fetch-deb: %s download librsvg2-bin librsvg2-2 gave no answer "
                                    "in 0.5 seconds" % (scene.bin / "apt-get"))
    assert not (scene.into / "bin").exists()


@pytest.mark.parametrize("missing", ["apt-get", "dpkg-deb"])
def test_no_apt_on_path_is_reported(scene, missing):
    (scene.bin / missing).unlink()
    code, out, err = run(*scene.args())
    assert (code, out) == (3, "")
    assert err == ("fetch-deb: no %s on PATH; fetch-deb runs where apt is (Debian, Ubuntu), such "
                   "as the Linux virtual machine\n" % missing)
    assert scene.calls() == [] and not scene.into.exists()


def test_a_wrapper_that_cannot_be_written_is_reported(scene):
    (scene.into / "bin").mkdir(parents=True)
    (scene.into / "bin").chmod(0o555)
    try:
        code, out, err = run(*scene.args())
        assert (code, out) == (3, "")
        assert lines(err)[-1].startswith("fetch-deb: cannot write %s: " % scene.wrapper)
        assert list((scene.into / "bin").iterdir()) == []
    finally:
        (scene.into / "bin").chmod(0o755)


# Names, refused before anything runs.

@pytest.mark.parametrize("argv, message", [
    (["--program", "bin/x", "--var", "V", "p1"], "--program must be a plain program name, not 'bin/x'"),
    (["--program", "x", "--var", "1V", "p1"], "--var must be letters, figures and _, starting with a letter or _: '1V'"),
    (["--program", "x", "--var", "V", "p1", "x;rm"], "not a Debian package name (small letters, figures, + - and ., starting with a letter or figure): 'x;rm'"),
])
def test_names_that_are_not_names_are_refused_before_anything_runs(scene, argv, message):
    code, out, err = run("--into", scene.into, *argv)
    assert (code, out, err) == (2, "", "fetch-deb: %s\n" % message)
    assert scene.calls() == [] and not scene.into.exists()


def test_a_package_that_looks_like_an_option_is_refused_by_the_parser_before_anything_runs(scene):
    code, out, err = run("--into", scene.into, "--program", "x", "--var", "V", "p1", "-o")
    assert (code, out) == (2, "")
    assert "unrecognized arguments: -o" in err
    assert scene.calls() == [] and not scene.into.exists()


# Paths a shell would split.

def test_a_hostile_folder_is_handed_over_as_it_is_and_the_wrapper_still_runs(tmp_path,
                                                                            monkeypatch):
    s = Scene(tmp_path, into_name="it's \"q\" $HOME `x` \\ café")
    monkeypatch.setenv("PATH", str(s.bin) + os.pathsep + "/usr/bin:/bin")
    monkeypatch.setenv("DEBSTUB_DIR", str(s.stub))
    code, out, _ = run(*s.args())
    assert (code, lines(out)) == (0, [s.export()])
    assert run_wrapper(s.wrapper, "x")[1] == [
        "LD=%s" % (s.root / "usr" / "lib" / "aarch64-linux-gnu"), "x"]


# The command-line surface.

def test_help_names_every_flag(scene):
    code, out, _ = run("--help")
    assert code == 0
    for flag in ("--into", "--program", "--var", "--dry-run", "PACKAGE"):
        assert flag in out


def test_as_a_program_the_first_run_prints_only_the_line(scene):
    done = subprocess.run([sys.executable, str(COMMAND)] + scene.args(), capture_output=True,
                          text=True, check=False, cwd=str(scene.tmp))
    assert (done.returncode, lines(done.stdout)) == (0, [scene.export()])
    assert "Traceback" not in done.stderr


def test_an_apt_get_that_cannot_be_started_is_reported_not_a_traceback(scene):
    (scene.bin / "apt-get").unlink()
    (scene.bin / "apt-get").write_text("#!/nonexistent/sh\n", encoding="utf-8")
    (scene.bin / "apt-get").chmod(0o755)
    code, out, err = run(*scene.args())
    assert (code, out) == (3, "")
    assert "failed (exit 127)" in lines(err)[0]
    assert "No such file or directory" in lines(err)[1]


def test_a_folder_that_cannot_hold_the_download_is_reported(scene):
    scene.into.parent.mkdir(parents=True)
    scene.into.write_text("a file, not a folder\n", encoding="utf-8")
    code, out, err = run(*scene.args())
    assert (code, out) == (3, "")
    assert err.startswith("fetch-deb: cannot make a download folder in %s: " % scene.into)
    assert scene.calls() == []
