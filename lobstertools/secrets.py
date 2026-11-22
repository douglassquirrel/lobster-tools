"""secrets: keep named sets of secrets, each a folder at mode 700 holding env.sh at mode 600, and
run a command with a set's variables (Request 30 from bernstein; PLAN.md "Settled" 70-73).

env.sh stays a shell file (`export NAME='value'` lines), so `set -a; . env.sh; set +a` still works,
but this command never runs it: it reads it line by line and refuses any line it cannot read,
naming the line's number and never its text. No value is ever printed, logged, put in an argument
list or written anywhere but the set's env.sh.
"""
import argparse
import collections
import os
import re
import stat
import subprocess
import sys
import termios
import threading

from lobstertools import config

PROG = "secrets"
MASK = b"[secret]"
MASK_MIN = 8
EXIT_OK, EXIT_EMPTY, EXIT_USAGE, EXIT_NO_SET, EXIT_EXISTS, EXIT_UNSAFE = 0, 1, 2, 3, 4, 6
EXIT_STOPPED = 130
TTY = "/dev/tty"
NO_TERMINAL = "no terminal to ask on; give --stdin to read the value from standard input"
RUN_OWN, RUN_CANNOT, RUN_NOT_FOUND = 125, 126, 127

NAME = re.compile(r"[A-Z_][A-Z0-9_]*\Z")
SET_NAME = re.compile(r"[a-z0-9][a-z0-9_-]*\Z")
LINE = re.compile(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)\Z", re.DOTALL)
BARE = re.compile(r"[A-Za-z0-9_\-./:@%+,=]")

Entry = collections.namedtuple("Entry", "number raw name value")


class BadLine(Exception):
    """A line of env.sh this command cannot read; carries its number only, never its text."""

    def __init__(self, number, why):
        super().__init__("line %d: %s" % (number, why))
        self.number, self.why = number, why


def good_name(name):
    return bool(NAME.match(name))


def good_set_name(name):
    return bool(SET_NAME.match(name))


def parse_value(rest):
    """The value a shell would give `NAME=rest`, for the forms this command reads; None for any
    other form."""
    out, i = [], 0
    while i < len(rest):
        c = rest[i]
        if c == "'":
            end = rest.find("'", i + 1)
            if end < 0:
                return None
            out.append(rest[i + 1:end])
            i = end + 1
        elif c == '"':
            end = rest.find('"', i + 1)
            if end < 0 or any(ch in rest[i + 1:end] for ch in "$`\\"):
                return None
            out.append(rest[i + 1:end])
            i = end + 1
        elif rest.startswith("\\'", i):
            out.append("'")
            i += 2
        elif c in " \t":
            tail = rest[i:].strip()
            if tail and not tail.startswith("#"):
                return None
            return "".join(out)
        elif BARE.match(c):
            out.append(c)
            i += 1
        else:
            return None
    return "".join(out)


def parse_env(text):
    """Every line of env.sh as an Entry (its number, its text as written, and the name and value
    of a variable line, None for a blank line or a comment). Raises BadLine for any other line, or
    a name given twice."""
    entries, seen = [], set()
    for number, raw in enumerate(text.splitlines(keepends=True), 1):
        line = raw.rstrip("\r\n")
        if not line.strip() or line.lstrip().startswith("#"):
            entries.append(Entry(number, raw, None, None))
            continue
        found = LINE.match(line)
        value = parse_value(found.group(2)) if found else None
        if value is None:
            raise BadLine(number, "not a line of the form export NAME='value'")
        name = found.group(1)
        if name in seen:
            raise BadLine(number, "a second line for %s" % name)
        seen.add(name)
        entries.append(Entry(number, raw, name, value))
    return entries


def env_line(name, value):
    """The line env.sh holds for NAME: single-quoted, so the shell takes it as it is."""
    return "export %s='%s'\n" % (name, value.replace("'", "'\\''"))


class Masker:
    """Replaces each value (bytes, of MASK_MIN or more) in a stream with MASK, holding back only
    the end of what it has been given that could be the start of a value."""

    def __init__(self, values):
        self.values = sorted({v for v in values if len(v) >= MASK_MIN}, key=len, reverse=True)
        self.held = b""

    def replace(self, data):
        for value in self.values:
            data = data.replace(value, MASK)
        return data

    def feed(self, data):
        data = self.replace(self.held + data)
        keep = 0
        for size in range(min(len(data), max((len(v) for v in self.values), default=1) - 1), 0, -1):
            if any(v.startswith(data[-size:]) for v in self.values):
                keep = size
                break
        self.held = data[len(data) - keep:] if keep else b""
        return data[:len(data) - keep]

    def flush(self):
        data, self.held = self.held, b""
        return data


class Refusal(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class SecretSet:
    """A set: its label (its name, or the path it was given as) and its folder."""

    def __init__(self, label, folder):
        self.label, self.folder = label, folder
        self.env = os.path.join(folder, "env.sh")

    def read(self):
        """The set's entries; Refusal (exit 3) when it is not there, cannot be read, or holds a
        line this command cannot read."""
        try:
            with open(self.env, "rb") as handle:
                data = handle.read()
        except FileNotFoundError:
            raise Refusal(EXIT_NO_SET, "no set %s: no file %s" % (self.label, self.env))
        except OSError as error:
            raise Refusal(EXIT_NO_SET, "cannot read %s: %s" % (self.env, error.strerror))
        try:
            return parse_env(data.decode("utf-8"))
        except UnicodeDecodeError:
            raise Refusal(EXIT_NO_SET, "%s is not UTF-8 text; fix it in an editor" % self.env)
        except BadLine as bad:
            raise Refusal(EXIT_NO_SET, "line %d of %s is %s; fix it in an editor"
                          % (bad.number, self.env, bad.why))

    def unsafe(self):
        """What is wrong with where the set is kept, one line each."""
        found = []
        for path, private in ((self.folder, 0o700), (self.env, 0o600)):
            try:
                bits = stat.S_IMODE(os.stat(path).st_mode)
            except OSError:
                continue
            if bits & 0o077:
                found.append("%s is mode %o; make it private with: chmod %o %s"
                             % (path, bits, private, path))
        tree = git_tree(self.folder)
        if tree:
            found.append("%s is inside the git working tree %s" % (self.folder, tree))
        return found


def git_tree(folder):
    """The nearest folder at or above FOLDER that holds .git, or None. Runs nothing."""
    here = os.path.abspath(folder)
    while True:
        if os.path.exists(os.path.join(here, ".git")):
            return here
        up = os.path.dirname(here)
        if up == here:
            return None
        here = up


def find_root(args):
    home = os.path.expanduser("~")
    try:
        conf = config.read_conf(home)
    except config.ConfigError as error:
        raise Refusal(EXIT_USAGE, "%s/.lobster-tools.conf: %s" % (home, error))
    root = args.root or os.environ.get("LOBSTER_SECRETS_ROOT") or conf.get("SECRETS_ROOT")
    if not root:
        raise Refusal(EXIT_USAGE, "no root for the sets: give --root DIR, or put SECRETS_ROOT=DIR "
                                  "in ~/.lobster-tools.conf (or LOBSTER_SECRETS_ROOT in the "
                                  "environment)")
    return os.path.abspath(os.path.expanduser(root))


def sets_named(args, names):
    """The sets the arguments name: each name under the root, then each --set-dir."""
    found = []
    if names:
        root = find_root(args)
        for name in names:
            if not good_set_name(name):
                raise Refusal(EXIT_USAGE, "%r is not a set name: lower-case letters, figures, "
                                          "- and _ only" % name)
            found.append(SecretSet(name, os.path.join(root, name)))
    for folder in args.set_dir or []:
        folder = os.path.abspath(os.path.expanduser(folder))
        found.append(SecretSet(folder, folder))
    if not found:
        raise Refusal(EXIT_USAGE, "name a set, or give --set-dir DIR")
    return found


def one_set(args):
    found = sets_named(args, [args.set] if args.set else [])
    if len(found) != 1:
        raise Refusal(EXIT_USAGE, "name one set, or give one --set-dir DIR, not both")
    return found[0]


def do_init(args, stdin):
    names = args.names or []
    if not names:
        raise Refusal(EXIT_USAGE, "give the names the set holds: --names NAME [NAME ...]")
    for name in names:
        if not good_name(name):
            raise Refusal(EXIT_USAGE, "%r is not a name: capitals, figures and _ only, not "
                                      "starting with a figure" % name)
    if len(set(names)) != len(names):
        raise Refusal(EXIT_USAGE, "a name is given twice")
    target = one_set(args)
    parent = os.path.dirname(target.folder)
    if not os.path.isdir(parent):
        raise Refusal(EXIT_NO_SET, "no folder %s; make it with: mkdir -m 700 %s" % (parent, parent))
    if os.path.lexists(target.folder):
        raise Refusal(EXIT_EXISTS, "%s already exists; nothing written" % target.folder)
    text = "".join(env_line(name, "") for name in names)
    if args.dry_run:
        print("Would make %s (700) and %s (600): %s" % (target.folder, target.env, " ".join(names)))
        return EXIT_OK
    os.mkdir(target.folder, 0o700)
    os.chmod(target.folder, 0o700)
    descriptor = os.open(target.env, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        os.fchmod(handle.fileno(), 0o600)
        handle.write(text)
    print("Made %s (700) and %s (600): %s" % (target.folder, target.env, " ".join(names)))
    return EXIT_OK


def do_check(args, stdin):
    need = args.need or []
    for name in need:
        if not good_name(name):
            raise Refusal(EXIT_USAGE, "%r is not a name" % name)
    worst = EXIT_OK
    values = {}
    for found in sets_named(args, args.sets):
        try:
            entries = [e for e in found.read() if e.name]
        except Refusal as refusal:
            sys.stderr.write("%s: %s\n" % (PROG, refusal))
            worst = EXIT_NO_SET
            continue
        print("%s (%s):" % (found.label, found.folder))
        width = max([len(e.name) for e in entries] + [len(n) for n in need] + [0]) + 2
        for entry in entries:
            print("  %s%s" % (entry.name.ljust(width), "set" if entry.value else "empty"))
            values[entry.name] = values.get(entry.name) or entry.value
            if not entry.value and (not need or entry.name in need) and worst != EXIT_NO_SET:
                worst = EXIT_EMPTY
        for line in found.unsafe():
            print("  unsafe: %s" % line)
            if worst == EXIT_OK:
                worst = EXIT_UNSAFE
    for name in need:
        if name not in values:
            print("%s  missing (in none of the sets)" % name)
            if worst != EXIT_NO_SET:
                worst = EXIT_EMPTY
    return worst


def do_list(args, stdin):
    root = find_root(args)
    try:
        names = sorted(n for n in os.listdir(root) if os.path.isdir(os.path.join(root, n)))
    except OSError:
        raise Refusal(EXIT_NO_SET, "no folder %s" % root)
    if not names:
        print("No sets in %s" % root)
    for name in names:
        found = SecretSet(name, os.path.join(root, name))
        if not os.path.exists(found.env):
            print("%s: (no env.sh)" % name)
            continue
        try:
            entries = found.read()
        except Refusal as refusal:
            match = re.match(r"line (\d+) of ", str(refusal))
            print("%s: (cannot read%s)" % (name, " line " + match.group(1) if match else ""))
            continue
        held = " ".join(e.name for e in entries if e.name)
        print("%s: %s%s" % (name, held, " (unsafe)" if found.unsafe() else ""))
    return EXIT_OK


def ask(prompt):
    """A value typed at the terminal, not echoed, of any length."""
    try:
        fd = os.open(TTY, os.O_RDWR | os.O_NOCTTY)
    except OSError:
        raise Refusal(EXIT_USAGE, NO_TERMINAL)
    try:
        return read_hidden(fd, prompt)
    finally:
        os.close(fd)


def read_hidden(fd, prompt):
    """Write PROMPT to the terminal FD and read a line from it, not echoed, with the terminal out
    of its line mode, so the value has no length limit (macOS takes 1,024 characters on a line).
    Return or newline or Ctrl-D ends it; Backspace takes back one character, Ctrl-U clears, Ctrl-C
    stops. The terminal's settings are put back however it ends."""
    saved = termios.tcgetattr(fd)
    quiet = list(saved)
    quiet[3] &= ~(termios.ICANON | termios.ECHO | termios.ISIG | termios.IEXTEN)
    quiet[6] = list(saved[6])
    quiet[6][termios.VMIN], quiet[6][termios.VTIME] = 1, 0
    typed = bytearray()
    try:
        termios.tcsetattr(fd, termios.TCSAFLUSH, quiet)
        os.write(fd, prompt.encode("utf-8"))
        while True:
            chunk = os.read(fd, 4096)
            for byte in chunk:
                if byte in (0x0A, 0x0D, 0x04):
                    chunk = b""
                    break
                if byte == 0x03:
                    raise Refusal(EXIT_STOPPED, "stopped at the prompt; nothing changed")
                if byte in (0x7F, 0x08):
                    while typed and typed[-1] & 0xC0 == 0x80:
                        typed.pop()
                    if typed:
                        typed.pop()
                elif byte == 0x15:
                    typed.clear()
                else:
                    typed.append(byte)
            if not chunk:
                break
    finally:
        termios.tcsetattr(fd, termios.TCSANOW, saved)
        os.write(fd, b"\n")
    try:
        return typed.decode("utf-8")
    except UnicodeDecodeError:
        raise Refusal(EXIT_USAGE, "the value is not UTF-8 text; nothing changed")


def read_value(args, stdin, label):
    if args.stdin:
        data = stdin.read()
        if data.endswith(b"\n"):
            data = data[:-1]
        try:
            value = data.decode("utf-8")
        except UnicodeDecodeError:
            raise Refusal(EXIT_USAGE, "the value is not UTF-8 text; nothing changed")
    elif stdin.isatty():
        value = ask("Value for %s in %s (not shown): " % (args.name, label))
    else:
        raise Refusal(EXIT_USAGE, NO_TERMINAL)
    if not value:
        raise Refusal(EXIT_USAGE, "the value is empty; nothing changed")
    if any(ch in value for ch in "\n\r\0"):
        raise Refusal(EXIT_USAGE, "the value holds a line break or a NUL; nothing changed")
    return value


def write_env(target, text):
    """Write TEXT as TARGET's env.sh: a new file in the set's own folder, with the old file's
    mode, renamed over it. If that fails, env.sh is as it was."""
    fresh = os.path.join(target.folder, ".env.sh.new-%d" % os.getpid())
    try:
        bits = stat.S_IMODE(os.stat(target.env).st_mode)
        descriptor = os.open(fresh, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(text.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
            os.fchmod(handle.fileno(), bits)
        os.replace(fresh, target.env)
    except OSError as error:
        left = (" A part-written copy may be left at %s (mode 600): remove it yourself."
                % fresh if os.path.exists(fresh) else "")
        raise Refusal(EXIT_NO_SET, "could not write %s: %s; it is as it was.%s"
                      % (target.env, error.strerror, left))


def do_set(args, stdin):
    if not good_name(args.name):
        raise Refusal(EXIT_USAGE, "%r is not a name: capitals, figures and _ only" % args.name)
    target = one_set(args)
    entries = target.read()
    held = {e.name: e for e in entries if e.name}
    if args.name not in held and not args.add:
        raise Refusal(EXIT_EXISTS, "%s has no %s; give --add to add it" % (target.label, args.name))
    was = ("added" if args.name not in held
           else "it was empty" if not held[args.name].value else "replaced")
    if args.dry_run:
        print("Would set %s in %s (%s)" % (args.name, target.label,
                                          "it is empty" if was == "it was empty" else
                                          "to add" if was == "added" else "to replace"))
        return EXIT_OK
    value = read_value(args, stdin, target.label)
    if args.min_length and len(value) < args.min_length:
        raise Refusal(EXIT_USAGE, "the value is %d characters, fewer than --min-length %d; "
                                  "nothing changed" % (len(value), args.min_length))
    line = env_line(args.name, value)
    if args.name in held:
        text = "".join(line if e.name == args.name else e.raw for e in entries)
    else:
        text = "".join(e.raw for e in entries)
        if text and not text.endswith("\n"):
            text += "\n"
        text += line
    write_env(target, text)
    said = "%s, %d characters" % (was, len(value))
    if was == "replaced":
        said += "; was %d" % len(held[args.name].value)
    print("%s set in %s (%s)" % (args.name, target.label, said))
    for problem in target.unsafe():
        print("unsafe: %s" % problem)
    return EXIT_OK


def write_all(fd, data):
    while data:
        data = data[os.write(fd, data):]


def pump(stream, fd, masker):
    """Pass what STREAM gives to FD, masked, until it ends. If FD's reader has gone, go on reading
    (so the command is never left blocked) and pass nothing more."""
    gone = False
    while True:
        data = os.read(stream.fileno(), 65536)
        out = masker.feed(data) if data else masker.flush()
        if out and not gone:
            try:
                write_all(fd, out)
            except OSError:
                gone = True
        if not data:
            return


def run_command(argv, env, values):
    """The one place secrets starts a program: ARGV as given, never through a shell, with ENV.
    With VALUES (bytes), its two output streams come through pumps that mask them; with None, it
    has the terminal as it is. Returns its exit code, or 128+N if signal N ended it."""
    sys.stdout.flush()
    sys.stderr.flush()
    piped = values is not None
    try:
        child = subprocess.Popen(argv, env=env,
                                 stdout=subprocess.PIPE if piped else None,
                                 stderr=subprocess.PIPE if piped else None)
    except FileNotFoundError:
        raise Refusal(RUN_NOT_FOUND, "%s: command not found" % argv[0])
    except OSError as error:
        raise Refusal(RUN_CANNOT, "%s cannot be run: %s" % (argv[0], error.strerror))
    pumps = []
    if piped:
        pumps = [threading.Thread(target=pump, args=(child.stdout, 1, Masker(values))),
                 threading.Thread(target=pump, args=(child.stderr, 2, Masker(values)))]
        for each in pumps:
            each.start()
    while True:
        try:
            code = child.wait()
            break
        except KeyboardInterrupt:
            continue
    for each in pumps:
        each.join()
    if piped:
        child.stdout.close()
        child.stderr.close()
    return 128 - code if code < 0 else code


def do_run(args, stdin, command):
    chosen = sets_named(args, args.sets)
    merged, origin = {}, {}
    for found in chosen:
        problems = found.unsafe()
        if problems:
            raise Refusal(RUN_OWN, "%s is not safe to use: %s" % (found.label, problems[0]))
        for entry in found.read():
            if not entry.name:
                continue
            if entry.name in origin:
                raise Refusal(RUN_OWN, "%s is in both %s and %s; name only one of them"
                              % (entry.name, origin[entry.name], found.label))
            merged[entry.name], origin[entry.name] = entry.value, found.label
    for name in args.need or []:
        if name not in merged:
            raise Refusal(RUN_OWN, "%s is in none of the sets: %s"
                          % (name, " ".join(f.label for f in chosen)))
        if not merged[name]:
            raise Refusal(RUN_OWN, "%s is empty in %s; put a value in with: secrets set %s %s"
                          % (name, origin[name], origin[name], name))
    env = dict(os.environ)
    env.update(merged)
    values = None if args.no_mask else [v.encode("utf-8") for v in merged.values()]
    return run_command(command, env, values)


def at_least_one(text):
    """--min-length's N: a whole number of at least 1."""
    try:
        number = int(text)
    except ValueError:
        number = 0
    if number < 1:
        raise argparse.ArgumentTypeError("%r is not a whole number of at least 1" % text)
    return number


def parse(argv):
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Keep named sets of secrets, each a folder (mode 700) holding env.sh (mode "
                    "600), and run a command with a set's variables. No value is ever printed. "
                    "A Claude session may run check, list and run; never set with a value.")
    verbs = parser.add_subparsers(dest="verb", metavar="{init,set,check,run,list}")
    where = argparse.ArgumentParser(add_help=False)
    where.add_argument("--root", metavar="DIR",
                       help="the folder holding the sets (else LOBSTER_SECRETS_ROOT, else "
                            "SECRETS_ROOT in ~/.lobster-tools.conf)")
    where.add_argument("--set-dir", action="append", metavar="DIR",
                       help="a set given by its folder, in place of a name")

    init = verbs.add_parser("init", parents=[where], help="make a new set with empty names",
                            description="Make SET's folder (700) and env.sh (600), with each "
                                        "name on a line and an empty value. Refuses a set that "
                                        "exists; never writes over a file.")
    init.add_argument("set", nargs="?", metavar="SET")
    init.add_argument("--names", nargs="+", metavar="NAME")
    init.add_argument("--dry-run", action="store_true", help="say what it would make; make nothing")

    put = verbs.add_parser("set", parents=[where], help="put one value in, for a person",
                           description="Replace NAME's line in SET's env.sh with a value asked "
                                       "for on the terminal without echoing it (or read from "
                                       "standard input with --stdin). Every other line and the "
                                       "file's mode stay as they were. Never prints the value.")
    put.add_argument("set", nargs="?", metavar="SET")
    put.add_argument("name", metavar="NAME")
    put.add_argument("--add", action="store_true", help="add NAME if the set does not have it")
    put.add_argument("--stdin", action="store_true",
                     help="read the value from standard input to its end (one final newline "
                          "dropped), for a tool such as a sign-in command")
    put.add_argument("--min-length", type=at_least_one, metavar="N",
                     help="refuse a value of fewer than N characters, writing nothing")
    put.add_argument("--dry-run", action="store_true", help="check the set and name; ask nothing")

    check = verbs.add_parser("check", parents=[where], help="say which names are set (reads only)",
                             description="Print each name as set or empty, and each --need name "
                                         "in no set as missing; never a value. Says so if the "
                                         "folder or file is open to others or inside a git "
                                         "working tree. Exit 0 all set, 1 a name empty or "
                                         "missing, 3 a set not there or unreadable, 6 all set "
                                         "but unsafe.")
    check.add_argument("sets", nargs="*", metavar="SET")
    check.add_argument("--need", nargs="+", metavar="NAME",
                       help="only these names must be set (exit 1 if any is empty or missing)")

    run = verbs.add_parser("run", parents=[where], help="run a command with sets' variables",
                           usage="%(prog)s [SET ...] [--need NAME ...] [--no-mask] -- COMMAND "
                                 "[ARG ...]",
                           description="Run COMMAND with the named sets' variables added to its "
                                       "environment, and nothing from any other set. Arguments "
                                       "go to it as given, never through a shell. Values of 8 "
                                       "characters or more in its output are shown as [secret] "
                                       "unless --no-mask. Exit: the command's own; 125 a set "
                                       "or needed name missing, empty or unsafe; 126 the "
                                       "command cannot be run; 127 it is not found.")
    run.add_argument("sets", nargs="*", metavar="SET")
    run.add_argument("--need", nargs="+", metavar="NAME",
                     help="refuse (125) unless each of these names is set")
    run.add_argument("--no-mask", action="store_true",
                     help="give the command the terminal as it is, values unmasked (for a "
                          "person at the keyboard)")

    verbs.add_parser("list", parents=[where], help="print each set and its names (reads only)",
                     description="Print each set under the root and the names it holds, never "
                                 "a value; (unsafe) after one open to others or inside git.")
    args = parser.parse_args(argv)
    if not args.verb:
        parser.error("name a verb: init, set, check, run or list")
    return args


def main(argv=None, stdin=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    stdin = stdin if stdin is not None else sys.stdin.buffer
    command = None
    if argv[:1] == ["run"] and not ("--" not in argv and {"-h", "--help"} & set(argv)):
        if "--" not in argv:
            sys.stderr.write("%s: give the command after --: secrets run SET -- COMMAND [ARG ...]\n"
                             % PROG)
            return RUN_OWN
        cut = argv.index("--")
        argv, command = argv[:cut], argv[cut + 1:]
        if not command:
            sys.stderr.write("%s: nothing after --: give the command to run\n" % PROG)
            return RUN_OWN
    try:
        args = parse(argv)
    except SystemExit as exit_:
        if command is not None and exit_.code:
            return RUN_OWN
        raise
    try:
        if args.verb == "run":
            return do_run(args, stdin, command)
        return {"init": do_init, "set": do_set, "check": do_check, "list": do_list}[args.verb](
            args, stdin)
    except Refusal as refusal:
        sys.stderr.write("%s: %s\n" % (PROG, refusal))
        if args.verb == "run" and refusal.code not in (RUN_CANNOT, RUN_NOT_FOUND):
            return RUN_OWN
        return refusal.code
