"""job: a queue that runs commands one at a time, in the order added, and a wait on it (Request 29
from bernstein; PLAN.md "Settled" 64-69).

A queue is a folder, `jobs/NAME/` under the working folder unless --dir says otherwise, holding one
folder per job in `waiting/`, `running/`, `done/` or `cancelled/`, moved between them by rename. A
job's folder holds `job.json` (its arguments, its working folder, when it was added, --go-on), and,
as it goes, `started.json`, `output` (its stdout and stderr together) and `ended.json` (its exit
code, or the signal that ended it, and when), or `cancelled.json`. Nothing is ever deleted or
rewritten. `job run`, which a session starts in the background, runs the queue and ends when it is
empty: there is no daemon. Commands are started from run_job alone, from the arguments as given,
never through a shell; a running job is stopped from stop_job alone, with SIGTERM to its process
group. L1 is about mail messages and does not bear on this ("Settled" 63).
"""
import argparse
import contextlib
import fcntl
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

from lobstertools import waitfile

PROG = "job"
EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_BUSY, EXIT_MISSING, EXIT_TIMEOUT = 0, 1, 2, 3, 4, 5
QUEUE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")
JOB_ID = re.compile(r"[0-9]{1,9}\Z")
FOLDERS = ("waiting", "running", "done", "cancelled")
COMMAND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), PROG)
DEFAULT_QUEUE = "default"
USAGE_ADD = "job add [--queue NAME] -- COMMAND [ARG ...]"
LOCK_TRIES, LOCK_PAUSE = 5, 0.05
GRACE = 5   # seconds job wait gives a runner started just before it to take its lock
now = time.monotonic
sleep = time.sleep


class Failure(Exception):
    def __init__(self, code, text):
        super().__init__(text)
        self.code, self.text = code, text


def stamp():
    """Now, in UTC, to the second; LOBSTER_JOB_NOW fixes it for the tests."""
    fixed = os.environ.get("LOBSTER_JOB_NOW")
    if fixed:
        return fixed
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def shown(argv):
    return " ".join(shlex.quote(a) for a in argv)


def command_of(saved):
    """The job's command as one line, quoted for a shell; ? when its job.json cannot be read."""
    argv = (saved or {}).get("argv")
    return shown(argv) if argv else "?"


def job_id(text):
    if not JOB_ID.match(text or ""):
        raise Failure(EXIT_USAGE, "a job id is a number, such as 3 or 0003, not %r" % text)
    return "%04d" % int(text)


def write_new(path, data):
    """A new file, never one already there (O_EXCL)."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(data)


def write_json(path, value):
    write_new(path, json.dumps(value, ensure_ascii=False, indent=1) + "\n")


class Queue:
    def __init__(self, top, name):
        if not QUEUE_NAME.match(name):
            raise Failure(EXIT_USAGE, "a queue name is letters, figures, - and _, starting with a "
                                      "letter or figure, not %r" % name)
        self.top, self.name, self.path = top, name, os.path.join(top, name)

    def folder(self, which, *more):
        return os.path.join(self.path, which, *more)

    def ids(self, which):
        try:
            names = os.listdir(self.folder(which))
        except OSError:
            return []
        return sorted(n for n in names if JOB_ID.match(n))

    def where(self, ident):
        for which in FOLDERS:
            if os.path.isdir(self.folder(which, ident)):
                return which
        return None

    def read(self, which, ident, name="job.json"):
        try:
            with open(self.folder(which, ident, name), encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, ValueError):
            return None

    def next_id(self):
        numbers = [int(i) for which in FOLDERS for i in self.ids(which)]
        return "%04d" % (max(numbers, default=0) + 1)

    def empty(self):
        return not any(self.ids(which) for which in FOLDERS)

    def make(self):
        for which in FOLDERS:
            os.makedirs(self.folder(which), exist_ok=True)

    @contextlib.contextmanager
    def books(self):
        """Held while a job is added, picked or moved, so two of those never cross."""
        self.make()
        fd = os.open(os.path.join(self.path, "books.lock"), os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def runner_active(self):
        path = os.path.join(self.path, "runner.lock")
        try:
            fd = os.open(path, os.O_RDONLY)
        except OSError:
            return False
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except OSError:
            return True
        finally:
            os.close(fd)
        return False

    def runner_line(self):
        line = "%s run" % shlex.quote(COMMAND)
        if self.name != DEFAULT_QUEUE:
            line += " --queue %s" % self.name
        if self.top != os.path.abspath("jobs"):
            line += " --dir %s" % shlex.quote(self.top)
        return line


def add(queue, args, command):
    if command is None or args.rest:
        raise Failure(EXIT_USAGE, "put the command after --: %s" % USAGE_ADD)
    if not command:
        raise Failure(EXIT_USAGE, "no command after --")
    if args.dry_run:
        print("Would add job %s to queue %s: %s" % (queue.next_id(), queue.name, shown(command)))
        return EXIT_OK
    with queue.books():
        ident = queue.next_id()
        os.mkdir(queue.folder("waiting", ident))
        write_json(queue.folder("waiting", ident, "job.json"),
                   {"id": ident, "argv": command, "cwd": os.getcwd(), "added": stamp(),
                    "go_on": args.go_on})
    print("Added job %s to queue %s: %s" % (ident, queue.name, shown(command)))
    if queue.runner_active():
        print("The runner for queue %s will start it in turn." % queue.name)
    else:
        print("No runner for queue %s: start one in the background with:" % queue.name)
        print("  %s" % queue.runner_line())
    return EXIT_OK


def listing(queue, args):
    state = "runner running" if queue.runner_active() else "no runner"
    print("Queue %s (%s): %s%s" % (queue.name, queue.path, "empty; " if queue.empty() else "",
                                   state))
    for which, title in (("done", "Done"), ("running", "Running"), ("waiting", "Waiting"),
                         ("cancelled", "Cancelled")):
        idents = queue.ids(which)
        if idents:
            print("%s:" % title)
        for ident in idents:
            print("  %s" % describe(queue, which, ident))
    return EXIT_OK


def describe(queue, which, ident):
    saved = queue.read(which, ident) or {}
    command = command_of(saved)
    if which == "cancelled":
        when = (queue.read(which, ident, "cancelled.json") or {}).get("cancelled", "?")
        return "%s  cancelled %s  %s" % (ident, when, command)
    if which == "done":
        began = queue.read(which, ident, "started.json") or {}
        ended = queue.read(which, ident, "ended.json") or {}
        return "%s  %s after %s, ended %s  %s" % (
            ident, how_it_ended(ended), duration(began.get("started"), ended.get("ended")),
            ended.get("ended", "?"), command)
    if which == "running":
        began = queue.read(which, ident, "started.json") or {}
        pid = began.get("pid")
        if queue.runner_active():
            state = "running"
        else:
            state = "no runner: %s" % ("still running" if alive(pid) else "interrupted")
        return "%s  since %s, process %s, %s  %s" % (ident, began.get("started", "?"), pid, state,
                                                    command)
    line = "%s  added %s  %s" % (ident, saved.get("added", "?"), command)
    return line + ("  (--go-on)" if saved.get("go_on") else "")


def cancel(queue, args):
    ident = job_id(args.id)
    which = queue.where(ident)
    if which is None:
        raise Failure(EXIT_MISSING, "no job %s in queue %s" % (ident, queue.name))
    if which == "cancelled":
        raise Failure(EXIT_BUSY, "job %s is already cancelled" % ident)
    if which == "done":
        raise Failure(EXIT_BUSY, "job %s has already ended" % ident)
    command = command_of(queue.read(which, ident))
    if which == "running":
        if not args.running:
            raise Failure(EXIT_BUSY, "job %s is running; add --running to stop it (SIGTERM)"
                          % ident)
        return cancel_running(queue, ident, command, args.dry_run)
    if args.dry_run:
        print("Would cancel job %s: %s" % (ident, command))
        return EXIT_OK
    with queue.books():
        os.rename(queue.folder("waiting", ident), queue.folder("cancelled", ident))
        write_json(queue.folder("cancelled", ident, "cancelled.json"), {"cancelled": stamp()})
    print("Cancelled job %s: %s" % (ident, command))
    return EXIT_OK


def how_it_ended(ended):
    if ended.get("interrupted"):
        return "interrupted"
    if ended.get("signal") is not None:
        return "ended by signal %d" % ended["signal"]
    return "exit %s" % ended.get("exit")


def duration(start, end):
    """How long from one stamp to the other: 42s, 3m05s, 2h07m; ? when either is missing."""
    try:
        seconds = int((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds())
    except (TypeError, ValueError):
        return "?"
    if seconds < 60:
        return "%ds" % seconds
    if seconds < 3600:
        return "%dm%02ds" % divmod(seconds, 60)
    return "%dh%02dm" % (seconds // 3600, seconds % 3600 // 60)


def alive(pid):
    """Whether a process with this id is there (signal 0 sends nothing)."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def run_job(argv, cwd, output, on_start):
    """Start the job's arguments as given, never through a shell, in its own process group, with
    its stdout and stderr to output; call on_start(pid), wait, and return its return code (a
    signal as minus its number), or the OSError that kept it from starting."""
    try:
        process = subprocess.Popen(list(argv), cwd=cwd, stdin=subprocess.DEVNULL, stdout=output,
                                   stderr=subprocess.STDOUT, start_new_session=True)
    except OSError as error:
        return error
    on_start(process.pid)
    return process.wait()


def take_runner_lock(queue):
    """The runner's lock, held until it ends; a moment's retry, since list and wait look at it."""
    fd = os.open(os.path.join(queue.path, "runner.lock"), os.O_RDWR | os.O_CREAT, 0o644)
    for attempt in range(LOCK_TRIES):
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except OSError:
            if attempt + 1 < LOCK_TRIES:
                time.sleep(LOCK_PAUSE)
    os.close(fd)
    raise Failure(EXIT_BUSY, "another job run is running queue %s; only one may run a queue"
                  % queue.name)


def stopped(queue, why):
    waiting = len(queue.ids("waiting"))
    return Failure(EXIT_FAILED, "%s, so the queue stopped with %d waiting; to go on, run it again:"
                                "\n  %s\nor cancel what should not run"
                   % (why, waiting, queue.runner_line()))


def settle_left_running(queue):
    """A job a runner that stopped left in running/: refused while its process is there; else
    marked interrupted, moved to done/, and the queue stops."""
    for ident in queue.ids("running"):
        pid = (queue.read("running", ident, "started.json") or {}).get("pid")
        if alive(pid):
            raise Failure(EXIT_BUSY, "job %s is still running as process %d, with no runner to "
                                     "record its end; wait for it to end, or stop it with: job "
                                     "cancel --running %s" % (ident, pid, ident))
        write_json(queue.folder("running", ident, "ended.json"),
                   {"ended": stamp(), "exit": None, "signal": None, "interrupted": True})
        os.rename(queue.folder("running", ident), queue.folder("done", ident))
        raise stopped(queue, "job %s was interrupted: its runner stopped before it ended, and it "
                             "is no longer running" % ident)


def run_one(queue, ident):
    """Run the job now in running/ and move it to done/; return (its exit code or None, go_on)."""
    saved = queue.read("running", ident) or {}
    argv, cwd = saved.get("argv") or [], saved.get("cwd")
    folder = queue.folder("running", ident)
    print("Job %s started: %s" % (ident, shown(argv)), flush=True)
    with open(os.path.join(folder, "output"), "xb") as output:
        result = run_job(argv, cwd, output,
                         lambda pid: write_json(os.path.join(folder, "started.json"),
                                                {"started": stamp(), "pid": pid}))
        if isinstance(result, OSError):
            write_json(os.path.join(folder, "started.json"), {"started": stamp(), "pid": None})
            output.write(("job: cannot start %s in %s: %s\n"
                          % (shown(argv[:1]), cwd, result.strerror or result)).encode("utf-8"))
            result = 127
    ended = {"ended": stamp(), "exit": result if result >= 0 else None,
             "signal": -result if result < 0 else None, "interrupted": False}
    write_json(os.path.join(folder, "ended.json"), ended)
    with queue.books():
        os.rename(folder, queue.folder("done", ident))
    began = queue.read("done", ident, "started.json") or {}
    print("Job %s ended: %s after %s" % (ident, how_it_ended(ended),
                                         duration(began.get("started"), ended["ended"])),
          flush=True)
    return result, bool(saved.get("go_on"))


def run(queue, args):
    queue.make()
    fd = take_runner_lock(queue)
    try:
        with queue.books():
            settle_left_running(queue)
        ran = failed = 0
        while True:
            with queue.books():
                waiting = queue.ids("waiting")
                if waiting:
                    os.rename(queue.folder("waiting", waiting[0]),
                              queue.folder("running", waiting[0]))
            if not waiting:
                break
            result, go_on = run_one(queue, waiting[0])
            ran += 1
            if result != 0:
                if not go_on:
                    raise stopped(queue, "job %s failed (%s)" % (
                        waiting[0], "exit %d" % result if result > 0 else "signal %d" % -result))
                failed += 1
        if not ran:
            print("Queue %s is empty: nothing to run" % queue.name)
        else:
            print("Queue %s is empty: ran %d job%s%s" % (
                queue.name, ran, "" if ran == 1 else "s",
                ", %d failed (--go-on)" % failed if failed else ""))
        return EXIT_OK
    finally:
        os.close(fd)


def stop_job(pid):
    """SIGTERM to the job's process group (its own, started so by run_job); never SIGKILL."""
    os.killpg(pid, signal.SIGTERM)


def cancel_running(queue, ident, command, dry_run):
    pid = (queue.read("running", ident, "started.json") or {}).get("pid")
    if not alive(pid):
        raise Failure(EXIT_BUSY, "job %s is no longer running, but its runner stopped before "
                                 "recording its end; the next job run marks it interrupted" % ident)
    if dry_run:
        print("Would send SIGTERM to job %s (process group %d): %s" % (ident, pid, command))
        return EXIT_OK
    try:
        stop_job(pid)
    except OSError as error:
        raise Failure(EXIT_FAILED, "could not stop job %s (process group %d): %s"
                      % (ident, pid, error.strerror or error)) from None
    after = ("its runner records how it ended" if queue.runner_active()
             else "with no runner, the next job run marks it interrupted")
    print("Sent SIGTERM to job %s (process group %d): %s; %s" % (ident, pid, command, after))
    return EXIT_OK


def wait(queue, args):
    if args.timeout < 0:
        raise Failure(EXIT_USAGE, "--timeout must be 0 or more, not %g" % args.timeout)
    before = set(queue.ids("done"))
    start = now()

    def look():
        ended = sorted(set(queue.ids("done")) - before)
        if ended:
            return ["Job %s ended: %s" % (ident, describe_end(queue, ident)) for ident in ended]
        running, waiting = queue.ids("running"), queue.ids("waiting")
        if not running and not waiting:
            return ["Queue %s is empty: nothing waiting or running" % queue.name]
        if queue.runner_active():
            return None
        for ident in running:
            pid = (queue.read("running", ident, "started.json") or {}).get("pid")
            if not alive(pid):
                return ["Job %s was interrupted: its runner stopped before it ended, and it is no "
                        "longer running" % ident]
        if not running:
            if now() - start < GRACE:
                return None
            return ["Queue %s has %d waiting and no runner; start one in the background with:"
                    % (queue.name, len(waiting)), "  %s" % queue.runner_line()]
        return None

    found = waitfile.wait_until(look, now, sleep, args.timeout, 0, 1)
    if found is None:
        still = "".join("; job %s is running, since %s" % (
            ident, (queue.read("running", ident, "started.json") or {}).get("started", "?"))
            for ident in queue.ids("running"))
        raise Failure(EXIT_TIMEOUT, "nothing ended in %g seconds%s" % (args.timeout, still))
    for line in found:
        print(line)
    return EXIT_OK


def describe_end(queue, ident):
    began = queue.read("done", ident, "started.json") or {}
    ended = queue.read("done", ident, "ended.json") or {}
    command = command_of(queue.read("done", ident))
    return "%s after %s: %s" % (how_it_ended(ended),
                                duration(began.get("started"), ended.get("ended")), command)


def parse(argv):
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="A queue of commands run one at a time, in the order added, for a session on "
                    "the Mac. 'job add -- COMMAND' queues a command; 'job run', started in the "
                    "background, runs the queue until it is empty; 'job wait', in the background, "
                    "returns when a job ends; 'job list' shows the queue; 'job cancel ID' takes a "
                    "waiting job off it. The queue is a folder, jobs/NAME/ in the working folder.")
    verbs = parser.add_subparsers(dest="verb", metavar="{add,run,list,wait,cancel}")
    verbs.required = True

    def verb(name, text):
        sub = verbs.add_parser(name, help=text, description=text)
        sub.add_argument("--queue", default=DEFAULT_QUEUE, metavar="NAME",
                         help="the queue (default: default)")
        sub.add_argument("--dir", default="jobs", metavar="DIR",
                         help="the folder the queues are in (default: jobs, in the working folder)")
        return sub

    sub = verb("add", "Put a command at the end of the queue: job add [--queue NAME] -- COMMAND "
                      "[ARG ...]. The arguments are kept as given and never pass through a shell.")
    sub.add_argument("--go-on", action="store_true",
                     help="if this command fails, the queue goes on (by default a failure stops it)")
    sub.add_argument("--dry-run", action="store_true", help="say what would be added; add nothing")
    sub.add_argument("rest", nargs="*", help=argparse.SUPPRESS)
    verb("run", "Run the queue's jobs one at a time until it is empty; start it in the background.")
    verb("list", "Show what is waiting, running, done and cancelled. Reads only.")
    sub = verb("wait", "Return when a job ends, or at once when nothing is running or waiting.")
    sub.add_argument("--timeout", type=float, default=2700, metavar="SECONDS",
                     help="give up after this long, exit 5 (default 2700; 0: as long as it takes)")
    sub = verb("cancel", "Take a waiting job off the queue (moved to cancelled/).")
    sub.add_argument("id", metavar="ID", help="the job's number, such as 3 or 0003")
    sub.add_argument("--running", action="store_true",
                     help="stop the job if it is running: SIGTERM to its process group, never "
                          "SIGKILL; the runner records how it ended, and the queue stops")
    sub.add_argument("--dry-run", action="store_true", help="say what would be done; do nothing")
    return parser.parse_args(argv)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    command = None
    if argv[:1] == ["add"] and "--" in argv:
        cut = argv.index("--")
        argv, command = argv[:cut], argv[cut + 1:]
    args = parse(argv)
    try:
        queue = Queue(os.path.abspath(args.dir), args.queue)
        if args.verb == "add":
            return add(queue, args, command)
        return {"run": run, "list": listing, "wait": wait, "cancel": cancel}[args.verb](queue, args)
    except Failure as failure:
        sys.stderr.write("%s: %s\n" % (PROG, failure.text))
        return failure.code
