"""wait-for-file: wait until a file appears and, if asked, has stopped changing (Request 29 from
bernstein; PLAN.md "Settled" 64).

It only reads: it looks at the path every second, and never writes, moves or runs anything. The
path is one path, taken whole (spaces, `$`, `*` and all), unless --glob says it is a pattern.
"""
import argparse
import glob as globbing
import os
import sys
import time

PROG = "wait-for-file"
EXIT_OK, EXIT_USAGE, EXIT_TIMEOUT = 0, 2, 5
EVERY = 1


def wait_until(look, now, sleep, timeout, stable, every):
    """What look() returns once it has returned the same thing, not None, for `stable` seconds;
    None when `timeout` seconds pass first (0: wait as long as it takes). Never sleeps past the
    timeout."""
    start = now()
    seen = since = None
    while True:
        found = look()
        moment = now()
        if found is None:
            seen = since = None
        else:
            if found != seen:
                seen, since = found, moment
            if moment - since >= stable:
                return found
        if timeout:
            left = timeout - (moment - start)
            if left <= 0:
                return None
            sleep(min(every, left))
        else:
            sleep(every)


def looker(path, glob):
    """A look: the (path, size, modification time) of each file there, sorted, as a tuple; None
    when there is none."""
    def look():
        entries = []
        for name in (sorted(globbing.glob(path)) if glob else [path]):
            try:
                found = os.stat(name)
            except OSError:
                continue
            entries.append((name, found.st_size, found.st_mtime_ns))
        return tuple(entries) or None
    return look



now = time.monotonic
sleep = time.sleep


def parse(argv):
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Wait until PATH exists and print it; exit 0 when it does, 5 at the timeout. "
                    "PATH is taken whole, never split or matched, unless --glob is given. It "
                    "only looks, every second: it writes, moves and runs nothing. For a session "
                    "on the Mac, as a background command, as lobster-mail wait is run.")
    parser.add_argument("path", metavar="PATH", help="the file to wait for")
    parser.add_argument("--timeout", type=float, default=2700, metavar="SECONDS",
                        help="give up after this long, exit 5 (default 2700, 45 minutes; "
                             "0 waits as long as it takes)")
    parser.add_argument("--stable", type=float, default=0, metavar="SECONDS",
                        help="wait also until the file has not changed in size or time for this "
                             "long, so a delivery still being written is not taken for a whole one")
    parser.add_argument("--glob", action="store_true",
                        help="PATH is a pattern (*, ?, [...]); print every file it matches")
    args = parser.parse_args(argv)
    for flag, value in (("--timeout", args.timeout), ("--stable", args.stable)):
        if value < 0:
            parser.error("%s must be 0 or more, not %g" % (flag, value))
    return args


def main(argv=None):
    args = parse(argv)
    look = looker(args.path, args.glob)
    found = wait_until(look, now, sleep, args.timeout, args.stable, EVERY)
    if found is None:
        if look() is None:
            why = "did not appear in %g seconds" % args.timeout
        else:
            why = "was still changing after %g seconds (--stable %g)" % (args.timeout, args.stable)
        sys.stderr.write("%s: %s %s\n" % (PROG, args.path, why))
        return EXIT_TIMEOUT
    for name, _, _ in found:
        print(name)
    return EXIT_OK
