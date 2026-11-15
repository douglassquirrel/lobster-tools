"""prepare-venv: a project's venv in the Linux device shell, its packages, its model check, one
setting in its config and the export lines (Request 01 from training-video-tools; PLAN.md "Settled" 49).

It runs programs only through run_program, and only three: `python3 -m venv --system-site-packages
DIR`, the venv's `python -m pip install -r FILE` and its `python -c "import ..."`, the line built
here from checked module names (L1's exception, "Settled" 49). It writes one file, the config it is
named, by writing a new copy beside it and renaming it into place. It never deletes anything.
"""
import argparse
import keyword
import os
import posixpath
import re
import shlex
import shutil
import stat
import subprocess
import sys
from collections import namedtuple

from lobstertools import config

PROG = "prepare-venv"
EXIT_OK, EXIT_USAGE, EXIT_FAILED = 0, 2, 3
PROJECT_FILE = "prepare-venv.conf"
KEYS = ("ENV_PREFIX", "REQUIREMENTS", "IMPORTS", "MODEL_FILES", "MODEL_SETTING", "MODEL_HELP")
REQUIRED = ("ENV_PREFIX", "REQUIREMENTS", "IMPORTS")
DEFAULT_HELP = "the project's README"

Project = namedtuple("Project", "prefix requirements imports model_files model_setting model_help")

NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
PREFIX = re.compile(r"[A-Z][A-Z0-9_]*\Z")


class ProjectError(Exception):
    pass


def is_module_name(text):
    parts = text.split(".")
    return all(part.isascii() and NAME.match(part) and not keyword.iskeyword(part)
               for part in parts)


def parse_project(text, home):
    """The project's own details from its prepare-venv.conf; ProjectError in words for anything
    wrong. Nothing in it is ever run: IMPORTS must be module names, from which the line is built."""
    try:
        settings = config.parse_conf(text, home)
    except config.ConfigError as error:
        raise ProjectError(str(error).replace(" of the config file", "")) from None
    unknown = [key for key in settings if key not in KEYS]
    if unknown:
        raise ProjectError("it has a key prepare-venv does not know: %s (the keys are %s)"
                           % (", ".join(unknown), ", ".join(KEYS)))
    for key in REQUIRED:
        if not settings.get(key):
            raise ProjectError("it has no %s line" % key)
    prefix = settings["ENV_PREFIX"]
    if not PREFIX.match(prefix):
        raise ProjectError("ENV_PREFIX must be capital letters, figures and _, starting with a "
                           "letter: %r" % prefix)
    requirements = settings["REQUIREMENTS"]
    normal = posixpath.normpath(requirements)
    if requirements.startswith("/") or normal == ".." or normal.startswith("../"):
        raise ProjectError("REQUIREMENTS must name a file inside the checkout, relative to it: %r"
                           % requirements)
    imports = settings["IMPORTS"].split()
    for name in imports:
        if not is_module_name(name):
            raise ProjectError("IMPORTS holds something that is not a module name: %r" % name)
    model_files = (settings.get("MODEL_FILES") or "").split()
    for name in model_files:
        if "/" in name or name in (".", ".."):
            raise ProjectError("MODEL_FILES must be plain file names in the model folder, not %r"
                               % name)
    setting = settings.get("MODEL_SETTING") or None
    if setting is not None and not NAME.match(setting):
        raise ProjectError("MODEL_SETTING must be letters, figures and _, starting with a letter "
                           "or _: %r" % setting)
    return Project(prefix, requirements, imports, model_files, setting,
                   settings.get("MODEL_HELP") or DEFAULT_HELP)


def import_line(names):
    """The import check's line, built here from names parse_project has checked."""
    return "import " + ", ".join(names)


def export_lines(prefix, python, conf):
    """The lines for `eval`, each value quoted as a shell needs it."""
    lines = ["export %s_PYTHON=%s" % (prefix, shlex.quote(python))]
    if conf is not None:
        lines.append("export %s_CONF=%s" % (prefix, shlex.quote(conf)))
    return lines + ["export PYTHONDONTWRITEBYTECODE=1"]


def is_setting_line(line, key):
    body = line.strip()
    return (not body.startswith("#") and "=" in body
            and body.partition("=")[0].strip() == key)


def with_setting(text, key, value):
    """The config's text with KEY=value in it, every other line as it was; None when it already
    says so. `text` None is a file that does not exist. ValueError for a file that is not
    KEY=value lines."""
    if text is None:
        return "%s=%s\n" % (key, value)
    try:
        settings = config.parse_conf(text, os.path.expanduser("~"))
    except config.ConfigError as error:
        raise ValueError(str(error).replace(" of the config file", "")) from None
    if settings.get(key) == value:
        return None
    new = "%s=%s\n" % (key, value)
    lines = text.splitlines(True)
    if any(is_setting_line(line, key) for line in lines):
        return "".join(new if is_setting_line(line, key) else line for line in lines)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    return "".join(lines) + new


def model_problems(model, files, help_):
    """What the model folder lacks, a message each: the folder itself, or each file."""
    if not os.path.isdir(model):
        return ["the model folder %s does not exist; get the model as %s says" % (model, help_)]
    return ["the model folder %s has no %s; get it as %s says" % (model, name, help_)
            for name in files if not os.path.isfile(os.path.join(model, name))]


def is_inside(path, checkout):
    """Whether `path` is the checkout or anything under it, symbolic links followed."""
    real, top = os.path.realpath(path), os.path.realpath(checkout)
    return real == top or real.startswith(top.rstrip(os.sep) + os.sep)


class Failure(Exception):
    """A refusal or a failure, in words, with the exit code it ends the run with."""

    def __init__(self, text, code=EXIT_FAILED):
        super().__init__(text)
        self.code = code


def allowed(argv):
    """Whether argv is one of the three programs prepare-venv may run."""
    argv = list(argv)
    return ((len(argv) == 5 and argv[1:4] == ["-m", "venv", "--system-site-packages"])
            or (len(argv) == 6 and argv[1:5] == ["-m", "pip", "install", "-r"])
            or (len(argv) == 3 and argv[1] == "-c" and argv[2].startswith("import ")
                and all(is_module_name(name.strip())
                        for name in argv[2][len("import "):].split(","))))


def run_program(argv):
    """(exit code, its output and errors together) of one of the three programs, given as an
    argument list, never a shell line."""
    if not allowed(argv):
        raise ValueError("prepare-venv runs only python3 -m venv, pip install -r and the import "
                         "check, not %r" % (argv,))
    try:
        done = subprocess.run(list(argv), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, check=False)
    except OSError as error:
        return 127, str(error)
    return done.returncode, done.stdout.decode("utf-8", "replace")


def progress(text):
    sys.stderr.write("%s: %s\n" % (PROG, text))


def last_lines(output):
    return "".join("  %s\n" % line for line in output.strip().splitlines()[-5:])


def run_or_fail(argv, advice):
    code, output = run_program(argv)
    if code != 0:
        raise Failure("%s failed (exit %d); its last lines:\n%s%s"
                      % (" ".join(shlex.quote(a) for a in argv), code, last_lines(output), advice))


def read_project(checkout):
    path = os.path.join(checkout, PROJECT_FILE)
    if not os.path.isfile(path):
        raise Failure("%s has no %s; a project that uses prepare-venv keeps its own details there "
                      "(README, \"prepare-venv\")" % (checkout, PROJECT_FILE), EXIT_USAGE)
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except (OSError, UnicodeDecodeError) as error:
        raise Failure("%s cannot be read: %s" % (path, error), EXIT_USAGE) from None
    try:
        return parse_project(text, os.path.expanduser("~")), path
    except ProjectError as error:
        raise Failure("%s cannot be used: %s" % (path, error), EXIT_USAGE) from None


def check_flags(project, path, model, conf):
    """The flags the project's file calls for, and none it does not."""
    if project.model_setting and (model is None or conf is None):
        raise Failure("%s names a model setting (MODEL_SETTING); give the model folder with "
                      "--model and the config file with --conf" % path, EXIT_USAGE)
    if project.model_files and model is None:
        raise Failure("%s names model files (MODEL_FILES); give the model folder with --model"
                      % path, EXIT_USAGE)
    if model is not None and not (project.model_files or project.model_setting):
        raise Failure("--model is given, but %s names no model (MODEL_FILES or MODEL_SETTING)"
                      % path, EXIT_USAGE)
    if conf is not None and not project.model_setting:
        raise Failure("--conf is given, but %s names no setting to write in it (MODEL_SETTING)"
                      % path, EXIT_USAGE)


def ensure_venv(venv, dry):
    """The venv's python, made now with the python3 on PATH when DIR/bin/python is missing;
    (its python, whether it is new)."""
    python = os.path.join(venv, "bin", "python")
    if os.path.isfile(python):
        return python, False
    python3 = shutil.which("python3")
    if python3 is None:
        raise Failure("no python3 on PATH to make the venv with; install Python 3 or put it on "
                      "PATH")
    if dry:
        print("Would make the venv at %s" % venv)
        return python, True
    run_or_fail([python3, "-m", "venv", "--system-site-packages", venv],
                "Fix that (the venv module and pip must work on this machine) and run again")
    progress("made the venv at %s" % venv)
    return python, True


def ensure_packages(python, venv, requirements, imports, dry, fresh):
    """Install the requirements when the venv cannot import the modules, and check again after.
    A venv a dry run has not made cannot be asked, and would need them."""
    line = import_line(imports)
    if not (dry and fresh):
        code, _ = run_program([python, "-c", line])
        if code == 0:
            return
    if dry:
        print("Would install the packages in %s into %s" % (requirements, venv))
        return
    run_or_fail([python, "-m", "pip", "install", "-r", requirements],
                "Fix that (the network, or a package's build needs) and run again; the venv is "
                "kept")
    progress("installed the packages in %s into %s" % (requirements, venv))
    code, output = run_program([python, "-c", line])
    if code != 0:
        raise Failure("the packages in %s are installed in %s, but `%s` still fails; its last "
                      "lines:\n%sCheck that REQUIREMENTS and IMPORTS in %s agree"
                      % (requirements, venv, line, last_lines(output), PROJECT_FILE))


def write_replacing(path, text):
    """Write `text` as `path`: a new file beside it, renamed into place, the old file's mode kept."""
    folder = os.path.dirname(path)
    temp = os.path.join(folder, ".%s.prepare-venv-%d.tmp" % (os.path.basename(path), os.getpid()))
    try:
        os.makedirs(folder, exist_ok=True)
        mode = stat.S_IMODE(os.stat(path).st_mode) if os.path.exists(path) else None
        with open(temp, "x", encoding="utf-8") as handle:
            handle.write(text)
        if mode is not None:
            os.chmod(temp, mode)
        os.replace(temp, path)
    except OSError as error:
        left = ("; the new copy is left at %s" % temp) if os.path.exists(temp) else ""
        raise Failure("cannot write %s: %s%s" % (path, error.strerror or error, left)) from None


def ensure_conf(conf, key, model, dry):
    """KEY=model in the config, every other line kept; a file that says it already is left alone."""
    try:
        text = None
        if os.path.lexists(conf):
            with open(conf, encoding="utf-8") as handle:
                text = handle.read()
        new = with_setting(text, key, model)
    except (OSError, ValueError) as error:
        raise Failure("%s cannot be used as it is; fix it or name another file with --conf:\n  %s"
                      % (conf, error)) from None
    if new is None:
        return
    if dry:
        print("Would write %s with %s=%s" % (conf, key, model))
        return
    write_replacing(conf, new)
    progress("wrote %s" % conf)


def parse(argv):
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Prepare a project's venv for the Linux device shell, outside its checkout: make "
                    "or reuse the venv, install the project's packages when they do not import, "
                    "write the model folder into the project's config, check the model's files, "
                    "and print the export lines for eval. The project's own details are in "
                    "prepare-venv.conf in its checkout (README, \"prepare-venv\").")
    parser.add_argument("--project", required=True, metavar="DIR",
                        help="the project's checkout: where its prepare-venv.conf is, and what "
                             "the venv must not be inside")
    parser.add_argument("--venv", required=True, metavar="DIR",
                        help="the venv to make or reuse, outside the checkout")
    parser.add_argument("--model", metavar="DIR",
                        help="the model folder, when prepare-venv.conf names model files or a "
                             "model setting")
    parser.add_argument("--conf", metavar="FILE",
                        help="the config to write the model setting into, when prepare-venv.conf "
                             "names one")
    parser.add_argument("--dry-run", action="store_true",
                        help="say what would be done; make, install and write nothing (only the "
                             "import check runs)")
    return parser.parse_args(argv)


def prepare(args):
    checkout, venv = os.path.abspath(args.project), os.path.abspath(args.venv)
    model = os.path.abspath(args.model) if args.model is not None else None
    conf = os.path.abspath(args.conf) if args.conf is not None else None
    if model is not None and ("\n" in model or "\r" in model):
        raise Failure("--model holds a line break, which one line of a config file cannot hold",
                      EXIT_USAGE)
    if is_inside(venv, checkout):
        raise Failure("--venv %s is inside the checkout %s; make the venv outside it (in a "
                      "connected checkout it would shadow the project's own .venv)"
                      % (args.venv, checkout), EXIT_USAGE)
    project, path = read_project(checkout)
    check_flags(project, path, model, conf)
    requirements = os.path.join(checkout, project.requirements)
    if not os.path.isfile(requirements):
        raise Failure("the requirements file %s, named by REQUIREMENTS in %s, does not exist"
                      % (requirements, PROJECT_FILE), EXIT_USAGE)
    python, fresh = ensure_venv(venv, args.dry_run)
    ensure_packages(python, venv, requirements, project.imports, args.dry_run, fresh)
    if project.model_setting:
        ensure_conf(conf, project.model_setting, model, args.dry_run)
    problems = (model_problems(model, project.model_files, project.model_help)
                if model is not None else [])
    for problem in problems:
        progress(problem)
    if problems:
        return EXIT_FAILED
    for line in export_lines(project.prefix, python, conf):
        print(line)
    return EXIT_OK


def main(argv=None):
    args = parse(argv)
    try:
        return prepare(args)
    except Failure as failure:
        sys.stderr.write("%s: %s\n" % (PROG, failure))
        return failure.code
