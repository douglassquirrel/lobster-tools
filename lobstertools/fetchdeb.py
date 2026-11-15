"""fetch-deb: a program from Debian packages, unpacked into a folder without root, behind a wrapper
(Request 24 (a) from training-video; PLAN.md "Settled" 54).

It runs programs only through run_program, and only two: `apt-get download PACKAGE...` (the
network), in a new download folder, and `dpkg-deb -x FILE DIR` (L1's third exception, "Settled"
54). It writes the downloaded files, what they unpack to, and one wrapper, made from checked names
and paths, by a new copy renamed into place. It never deletes anything: a failed download's folder
is named and left.
"""
import argparse
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

PROGRAM = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.+-]*\Z")
NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
PACKAGE = re.compile(r"[a-z0-9][a-z0-9+.-]+\Z")
BIN_FOLDERS = ("usr/bin", "bin", "usr/sbin", "sbin", "usr/local/bin")
PROG = "fetch-deb"
EXIT_OK, EXIT_USAGE, EXIT_FAILED = 0, 2, 3
TIMEOUT = 900


class Refused(Exception):
    pass


def check_names(program, var, packages):
    """Refused in words for anything that is not a plain program name, a variable name, or a
    Debian package name: none of them can then be read as an option or a path."""
    if not PROGRAM.match(program) or program in (".", ".."):
        raise Refused("--program must be a plain program name, not %r" % program)
    if not NAME.match(var) or not var.isascii():
        raise Refused("--var must be letters, figures and _, starting with a letter or _: %r" % var)
    if not packages:
        raise Refused("name at least one package")
    for package in packages:
        if not PACKAGE.match(package):
            raise Refused("not a Debian package name (small letters, figures, + - and ., starting "
                          "with a letter or figure): %r" % package)


def find_program(root, name):
    """The program in the unpacked packages' bin folders, usr/bin first; None when absent."""
    for folder in BIN_FOLDERS:
        path = os.path.join(root, folder, name)
        if os.path.isfile(path):
            return path
    return None


def library_dirs(root):
    """Every folder under root holding a shared object (`*.so`, `*.so.N`), sorted."""
    found = []
    for folder, _, files in os.walk(root):
        if any(name.endswith(".so") or ".so." in name for name in files):
            found.append(folder)
    return sorted(found)


def wrapper_text(program_path, libraries, packages):
    """A /bin/sh wrapper that puts the libraries first on LD_LIBRARY_PATH and runs the program
    with its arguments; every path quoted."""
    lines = ["#!/bin/sh", "# Made by lobster-tools' fetch-deb from: %s" % " ".join(packages)]
    if libraries:
        lines += ["LD_LIBRARY_PATH=%s${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
                  % shlex.quote(":".join(libraries)), "export LD_LIBRARY_PATH"]
    lines.append('exec %s "$@"' % shlex.quote(program_path))
    return "\n".join(lines) + "\n"


def export_line(var, path):
    return "export %s=%s" % (var, shlex.quote(path))


class Failure(Exception):
    pass


def allowed(argv):
    """Whether argv is one of the two programs fetch-deb may run."""
    argv = list(argv)
    name = os.path.basename(argv[0]) if argv else ""
    return ((name == "apt-get" and len(argv) > 2 and argv[1] == "download"
             and all(PACKAGE.match(p) for p in argv[2:]))
            or (name == "dpkg-deb" and len(argv) == 4 and argv[1] == "-x"))


def run_program(argv, cwd=None):
    """(exit code, its output and errors together) of one of the two programs, given as an
    argument list, never a shell line; None for the code when it gave no answer in TIMEOUT."""
    if not allowed(argv):
        raise ValueError("fetch-deb runs only apt-get download and dpkg-deb -x, not %r" % (argv,))
    try:
        done = subprocess.run(list(argv), cwd=cwd, stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
                              timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return None, ""
    except OSError as error:
        return 127, str(error)
    return done.returncode, done.stdout.decode("utf-8", "replace")


def progress(text):
    sys.stderr.write("%s: %s\n" % (PROG, text))


def run_or_fail(argv, advice, cwd=None):
    code, output = run_program(argv, cwd)
    shown = " ".join(shlex.quote(a) for a in argv)
    if code is None:
        raise Failure("%s gave no answer in %s seconds\n%s" % (shown, TIMEOUT, advice))
    if code != 0:
        last = "".join("  %s\n" % line for line in output.strip().splitlines()[-5:])
        raise Failure("%s failed (exit %d); its last lines:\n%s%s" % (shown, code, last, advice))


def write_wrapper(path, text):
    """The wrapper, mode 755: a new copy beside it, renamed into place."""
    folder = os.path.dirname(path)
    temp = os.path.join(folder, ".%s.fetch-deb-%d.tmp" % (os.path.basename(path), os.getpid()))
    try:
        os.makedirs(folder, exist_ok=True)
        with open(temp, "x", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(temp, 0o755)
        os.replace(temp, path)
    except OSError as error:
        left = ("; the new copy is left at %s" % temp) if os.path.exists(temp) else ""
        raise Failure("cannot write %s: %s%s" % (path, error.strerror or error, left)) from None


def parse(argv):
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Fetch a program from Debian packages without root: apt-get download the "
                    "packages into a new folder under --into, unpack them into --into/root with "
                    "dpkg-deb -x, write a wrapper --into/bin/PROGRAM that puts their libraries on "
                    "LD_LIBRARY_PATH, and print 'export VAR=<the wrapper>' for eval. A second run "
                    "that finds the wrapper and its program runs nothing.")
    parser.add_argument("--into", required=True, metavar="DIR",
                        help="the folder to fetch into, such as one in the work area")
    parser.add_argument("--program", required=True, metavar="NAME",
                        help="the program the packages hold, such as rsvg-convert")
    parser.add_argument("--var", required=True, metavar="VAR",
                        help="the variable the export line sets, such as RSVG_CONVERT")
    parser.add_argument("--dry-run", action="store_true",
                        help="say what would be done; download, unpack and write nothing")
    parser.add_argument("packages", nargs="*", metavar="PACKAGE",
                        help="the Debian packages, such as librsvg2-bin librsvg2-2")
    return parser.parse_args(argv)


def fetch(args):
    try:
        check_names(args.program, args.var, args.packages)
    except Refused as refused:
        raise Failure(str(refused), EXIT_USAGE) from None
    into = os.path.abspath(args.into)
    root, bin_ = os.path.join(into, "root"), os.path.join(into, "bin")
    wrapper = os.path.join(bin_, args.program)
    line = export_line(args.var, wrapper)
    if os.path.isfile(wrapper) and find_program(root, args.program):
        print(line)
        return EXIT_OK
    tools = {}
    for name in ("apt-get", "dpkg-deb"):
        tools[name] = shutil.which(name)
        if tools[name] is None:
            raise Failure("no %s on PATH; fetch-deb runs where apt is (Debian, Ubuntu), such as "
                          "the Linux virtual machine" % name)
    if args.dry_run:
        print("Would download %s into a new download- folder in %s" % (" ".join(args.packages), into))
        print("Would unpack them into %s and write %s" % (root, wrapper))
        print(line)
        return EXIT_OK
    untouched = "nothing was written in %s" % bin_
    try:
        os.makedirs(into, exist_ok=True)
        download = tempfile.mkdtemp(prefix="download-", dir=into)
    except OSError as error:
        raise Failure("cannot make a download folder in %s: %s" % (into, error.strerror or error))
    run_or_fail([tools["apt-get"], "download"] + args.packages,
                "Check the package names and the network, and run again; the download folder %s "
                "is left as it is, and %s" % (download, untouched), cwd=download)
    debs = sorted(name for name in os.listdir(download) if name.endswith(".deb"))
    if len(debs) != len(args.packages):
        raise Failure("apt-get download gave %d file%s for %d packages (%s); %s"
                      % (len(debs), "" if len(debs) == 1 else "s", len(args.packages),
                         ", ".join(debs), untouched))
    progress("downloaded %s into %s" % (" ".join(args.packages), download))
    for name in debs:
        run_or_fail([tools["dpkg-deb"], "-x", os.path.join(download, name), root],
                    "The downloaded packages are left in %s; %s" % (download, untouched))
    progress("unpacked them into %s" % root)
    program = find_program(root, args.program)
    if program is None:
        raise Failure("the packages unpacked into %s hold no %s in %s; %s"
                      % (root, args.program, ", ".join(BIN_FOLDERS[:-1]) + " or " + BIN_FOLDERS[-1],
                         untouched))
    write_wrapper(wrapper, wrapper_text(program, library_dirs(root), args.packages))
    progress("wrote %s" % wrapper)
    print(line)
    return EXIT_OK


def main(argv=None):
    args = parse(argv)
    try:
        return fetch(args)
    except Failure as failure:
        code = failure.args[1] if len(failure.args) > 1 else EXIT_FAILED
        sys.stderr.write("%s: %s\n" % (PROG, failure.args[0]))
        return code
