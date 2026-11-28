"""each: run one command over a list of items, one at a time (Request 35 from bernstein; PLAN.md
"Settled" 85-87)."""
import argparse
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys

from lobstertools.secrets import PASSED_ON, Relay, in_foreground

PROG = "each"
EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_NOT_FOUND = 0, 1, 2, 3


def items_from(text):
    """The items in a list's text: one per line; a line empty or only white space is skipped; a
    final line with no newline is taken; one carriage return before a newline is dropped; all else
    is kept as given."""
    items = []
    for line in text.split("\n"):
        line = line.removesuffix("\r")
        if line.strip():
            items.append(line)
    return items


PLACE = "{}"


def filled(command, item):
    """COMMAND with ITEM put in: in place of every {} in its arguments (never in the command word
    itself), or as one more argument at the end when none holds {}."""
    word, arguments = command[0], list(command[1:])
    if any(PLACE in argument for argument in arguments):
        return [word] + [argument.replace(PLACE, item) for argument in arguments]
    return [word] + arguments + [item]


SHELLS = ("sh", "bash", "zsh", "dash", "ksh", "fish", "csh", "tcsh")
INTERPRETERS = ("python", "perl", "ruby", "node", "osascript", "php", "lua", "Rscript")
WAYS_ROUND = ("env", "xargs")
PYTHON = re.compile(r"python(\d+(\.\d+)?)?\Z")


def refusal(word):
    """Why each will not run the command WORD (a shell, an interpreter, or env or xargs, the two
    plain ways round that), or None."""
    name = os.path.basename(word)
    if name in SHELLS + INTERPRETERS + WAYS_ROUND or PYTHON.match(name):
        return ("%s refused: each runs one tool over a list, never a shell or an "
                "interpreter (a ganglion's rule 11). Name the tool itself after --; a job no tool "
                "does yet is a request to a claw." % name)
    return None


def shown(argv):
    return " ".join(shlex.quote(argument) for argument in argv)


def run_item(argv, relay):
    """The one place each starts a program: ARGV as given, never through a shell, with nothing on
    its standard input and this terminal's output. RELAY is told the child once it exists. Returns
    its exit code (a signal as minus its number), or the OSError that kept it from starting."""
    sys.stdout.flush()
    sys.stderr.flush()
    try:
        child = subprocess.Popen(argv, stdin=subprocess.DEVNULL)
    except OSError as error:
        return error
    relay.attach(child)
    return child.wait()


def parse(argv):
    parser = argparse.ArgumentParser(
        prog=PROG,
        usage="%(prog)s [--from FILE|-] [--go-on] [--dry-run] [ITEM ...] -- COMMAND [ARG ...]",
        description="Run COMMAND once for each item, one at a time, in order. Each {} in its "
                    "arguments is the item; with no {}, the item is the last argument. Never "
                    "through a shell; the command's standard input is empty.")
    parser.add_argument("items", nargs="*", metavar="ITEM", help="the items, before --")
    parser.add_argument("--from", dest="source", metavar="FILE",
                        help="read the items from FILE, one per line (- for standard input)")
    parser.add_argument("--go-on", action="store_true",
                        help="run every item even when one fails (exit 1 if any failed)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print each command line it would run, and run none")
    before, command = (argv[:argv.index("--")], argv[argv.index("--") + 1:]) \
        if "--" in argv else (argv, [])
    args = parser.parse_args(before)
    args.command = command
    if not command:
        parser.error("nothing after --: give the command to run, as in "
                     "each ITEM ... -- COMMAND [ARG ...]")
    if args.items and args.source is not None:
        parser.error("give the items after each or in --from, not both")
    if not args.items and args.source is None:
        parser.error("no items: list them before --, or give --from FILE (- for standard input)")
    return args


class Refusal(Exception):
    def __init__(self, code, text):
        super().__init__(text)
        self.code, self.text = code, text


def check_command(word):
    """Refuse, before anything runs, a command each will not run or cannot find."""
    reason = refusal(word)
    if reason:
        raise Refusal(EXIT_USAGE, reason)
    if "/" in word:
        if not (os.path.isfile(word) and os.access(word, os.X_OK)):
            raise Refusal(EXIT_NOT_FOUND, "%s: no such command; nothing run" % word)
    elif shutil.which(word) is None:
        raise Refusal(EXIT_NOT_FOUND, "%s: no such command on PATH; nothing run" % word)


def read_items(args, stdin):
    if args.source is None:
        return args.items
    if args.source == "-":
        return items_from((stdin or sys.stdin).read())
    try:
        with open(args.source, encoding="utf-8", errors="surrogateescape") as listing:
            return items_from(listing.read())
    except OSError as error:
        raise Refusal(EXIT_USAGE, "--from %s cannot be read (%s); nothing run"
                      % (args.source, error.strerror))


def main(argv=None, stdin=None):
    args = parse(sys.argv[1:] if argv is None else argv)
    try:
        check_command(args.command[0])
        items = read_items(args, stdin)
    except Refusal as refused:
        sys.stderr.write("%s: %s\n" % (PROG, refused.text))
        return refused.code
    total = len(items)
    if not total:
        print("no items: nothing run")
        return EXIT_OK
    if args.dry_run:
        for number, item in enumerate(items, 1):
            print("would run [%d/%d] %s" % (number, total, shown(filled(args.command, item))))
        print("dry run: %d would run, none run" % total)
        return EXIT_OK
    stop = Stop()
    before = {signum: signal.signal(signum, stop.handle) for signum in PASSED_ON}
    try:
        return run_all(args, items, stop)
    finally:
        for signum, handler in before.items():
            signal.signal(signum, handler)


class Stop:
    """A stop sent to each: the first signal is kept, so no more items start, and every one is
    passed on to the running command as secrets passes it on ("Settled" 77, 78)."""

    def __init__(self):
        self.signum, self.relay = None, Relay(in_foreground)

    def handle(self, signum, frame):
        if self.signum is None:
            self.signum = signum
        self.relay.handle(signum, frame)


def run_all(args, items, stop):
    total = len(items)
    succeeded = failed = 0
    for number, item in enumerate(items, 1):
        if stop.signum is not None:
            number -= 1
            break
        argv_ = filled(args.command, item)
        print("[%d/%d] %s" % (number, total, shown(argv_)))
        code = run_item(argv_, stop.relay)
        if isinstance(code, OSError):
            print("could not start: %s" % code.strerror)
        else:
            print("ended by signal %d" % -code if code < 0 else "exit %d" % code)
        if code == 0:
            succeeded += 1
            continue
        failed += 1
        if stop.signum is None and not args.go_on:
            print("stopped at the first failure: %d of %d ran (%d succeeded, %d failed), %d not "
                  "run" % (number, total, succeeded, failed, total - number))
            return EXIT_FAILED
    if stop.signum is not None:
        print("stopped by signal %d: %d of %d ran (%d succeeded, %d failed), %d not run"
              % (stop.signum, number, total, succeeded, failed, total - number))
        return 128 + stop.signum
    print("%d ran: %d succeeded, %d failed" % (total, succeeded, failed))
    return EXIT_FAILED if failed else EXIT_OK
