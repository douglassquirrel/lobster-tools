"""session-check: the facts a session checks at its start and its end (Request 16). Reads only.

It reads the project's folder, its lobster.conf and the mailbox's sent/ copies, and runs git only
through run_git, with reading verbs only (PLAN.md "Settled" 43; `stash` only as `stash list`,
"Settled" 46). It writes nothing, anywhere.
"""
import argparse
import os
import re
import subprocess
import sys
from collections import namedtuple

from lobstertools import config, mail, message

Finding = namedtuple("Finding", "kind text")     # kind: first, problem, cannot, fact

EXIT_OK, EXIT_TELL, EXIT_USAGE, EXIT_CANNOT = 0, 1, 2, 3

DIARY_IN_BODY = re.compile(r"DIARY\.md\W*(?:\w+\W+){0,6}?(\d[\d,]*)\s+lines\b")


def handover_diary_lines(headers, body):
    """The diary's length the last handover gave: its Diary-Lines header, failing that the first
    "N lines" within a few words after "DIARY.md" in its body, failing that None."""
    value = (headers or {}).get("Diary-Lines", "")
    if value.isdigit():
        return int(value)
    match = DIARY_IN_BODY.search(body.decode("utf-8", "replace"))
    return int(match.group(1).replace(",", "")) if match else None


def folder_list(value):
    """FOLDERS as bernstein-tools writes it (Request 21, "Settled" 55): folders separated by colons,
    each part trimmed and an empty one passed over; a line with no colon is one path, spaces and
    all."""
    value = (value or "").strip()
    if ":" not in value:
        return [value] if value else []
    return [part.strip() for part in value.split(":") if part.strip()]


def expected_folders(conf, session, home, mail_root):
    """(what, path) for each folder this session should be able to reach."""
    folders = folder_list(conf.get("FOLDERS"))
    if session == "mac":
        found = [("FOLDERS %s" % path, path) for path in folders]
        return found + ([("the mail root", mail_root)] if mail_root else [])
    mnt = os.path.join(home, "mnt")
    found = [("SISTER %s" % name, os.path.join(mnt, name))
             for name in (conf.get("SISTER") or "").split()]
    found += [("CLAWS %s" % name, os.path.join(mnt, name))
              for name in (conf.get("CLAWS") or "").split()]
    for path in folders:
        name = os.path.basename(os.path.normpath(path))
        found.append(("FOLDERS %s" % name, os.path.join(mnt, name)))
    return found + [("the mail folder", os.path.join(mnt, "mail")),
                    ("lobster-tools", os.path.join(mnt, "lobster-tools"))]


# Fields before the path in each kind of porcelain v2 entry ("Things checked" 10).
FIELDS_BEFORE_PATH = {"1": 8, "2": 9, "u": 10, "?": 1}


def parse_status(data):
    """`git status --porcelain=v2 --branch -z`: the branch, its upstream, how far ahead, whether
    the upstream's ref is gone, and every changed or untracked path (ignored ones left out)."""
    status = {"head": None, "upstream": None, "ahead": None, "gone": False, "paths": []}
    items = data.split(b"\0")
    skip = False
    for raw in items:
        if skip or not raw:
            skip = False
            continue
        item = raw.decode("utf-8", "replace")
        if item.startswith("# branch.head "):
            status["head"] = item[len("# branch.head "):]
        elif item.startswith("# branch.upstream "):
            status["upstream"] = item[len("# branch.upstream "):]
        elif item.startswith("# branch.ab "):
            status["ahead"] = int(item.split()[2].lstrip("+"))
        elif item[0] in FIELDS_BEFORE_PATH:
            status["paths"].append(item.split(" ", FIELDS_BEFORE_PATH[item[0]])[-1])
            skip = item[0] == "2"        # a rename's old path follows as its own item
    status["gone"] = status["upstream"] is not None and status["ahead"] is None
    return status


def parse_stashes(data):
    """`git stash list --format=%gd%x00%ci%x00%gs`: (name, when made, git's words) for each
    stash, newest first, as git lists them."""
    found = []
    for line in data.decode("utf-8", "replace").splitlines():
        if line.strip():
            name, when, words = (line.split("\0", 2) + ["", ""])[:3]
            found.append((name, when, words))
    return found


def size_text(count):
    if count < 1000:
        return "%d bytes" % count
    for unit, scale in (("kB", 1e3), ("MB", 1e6), ("GB", 1e9)):
        if count < scale * 1000 or unit == "GB":
            return "%.1f %s" % (count / scale, unit)


def fact(text):
    return Finding("fact", text)


def problem(text, first=False):
    return Finding("first" if first else "problem", text)


def cannot(text):
    return Finding("cannot", text)


def report(findings):
    """The lines to print, everything to tell first (a shorter diary first of all), and the exit
    code: 3 when something cannot be told, else 1 when something is to be told, else 0."""
    first = [f.text for f in findings if f.kind == "first"]
    tell = first + [f.text for f in findings if f.kind in ("problem", "cannot")]
    facts = [f.text for f in findings if f.kind == "fact"]
    if tell:
        lines = ["-- To tell the person you work for (%d):" % len(tell)] + tell
    else:
        lines = ["-- Nothing to tell."]
    lines += ["-- Facts:"] + facts
    if any(f.kind == "cannot" for f in findings):
        return lines, EXIT_CANNOT
    return lines, EXIT_TELL if tell else EXIT_OK



# Running git: reading verbs only, never a lock, never a prompt ("Settled" 43).

GIT_READING = ("status", "remote", "log", "check-ignore", "stash list")
GIT_TIMEOUT = 60
STASH_FORMAT = "--format=%gd%x00%ci%x00%gs"     # its name, when it was made, git's words
STASH_AT_THE_END = ": put it back before the handover, or tell the person it is being left and why"


def reading(args):
    """Whether ARGS begin with one of the reading verbs (`stash` only as `stash list`)."""
    return any(list(args[:len(verb.split())]) == verb.split() for verb in GIT_READING)


class NoGit(Exception):
    pass


class GitSilent(Exception):
    pass


def run_git(repo, args):
    """(exit code, stdout bytes, first line of stderr) of `git -C REPO ARGS`."""
    if not reading(args):
        raise ValueError("session-check runs only reading git verbs, not %r" % (args[:2],))
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0", LC_ALL="C")
    try:
        done = subprocess.run(["git", "-C", repo] + list(args), check=False,
                              stdin=subprocess.DEVNULL, capture_output=True, env=env,
                              timeout=GIT_TIMEOUT)
    except FileNotFoundError:
        raise NoGit()
    except subprocess.TimeoutExpired:
        raise GitSilent()
    error = done.stderr.decode("utf-8", "replace").strip().splitlines()
    return done.returncode, done.stdout, error[0] if error else ""


def plural(count, word):
    return "%d %s%s" % (count, word, "" if count == 1 else "s")


class Check:
    """One run: the project, its settings and what has been found so far."""

    def __init__(self, args):
        self.args, self.project = args, os.path.abspath(args.project or os.getcwd())
        self.home = os.path.expanduser("~")
        self.findings, self.git_missing, self.root_problem = [], False, None
        self.name = os.path.basename(self.project)

    def add(self, finding):
        self.findings.append(finding)

    def git(self, repo, args):
        """run_git, or None when git is missing (said once)."""
        if self.git_missing:
            return None
        try:
            return run_git(repo, args)
        except NoGit:
            self.git_missing = True
            self.add(cannot("git was not found on PATH, so nothing about commits can be told"))
            return None

    # lobster.conf

    def settings(self):
        path = os.path.join(self.project, "lobster.conf")
        if not os.path.isfile(path):
            self.add(cannot("no lobster.conf in %s, so the folders this session should reach "
                            "cannot be told" % self.project))
            return {}
        try:
            with open(path, encoding="utf-8") as handle:
                return config.parse_conf(handle.read(), self.home)
        except (OSError, UnicodeDecodeError, config.ConfigError) as problem_:
            self.add(cannot("lobster.conf could not be read (%s), so the folders this session "
                            "should reach cannot be told" % problem_))
            return {}

    # git

    def repositories(self):
        """The project folder, then each folder directly in it that is a git repository."""
        found = [(self.project, self.name)]
        for entry in sorted(os.listdir(self.project)):
            path = os.path.join(self.project, entry)
            if (not entry.startswith(".") and entry != "_to_delete" and os.path.isdir(path)
                    and os.path.exists(os.path.join(path, ".git"))):
                found.append((path, "%s/%s" % (self.name, entry)))
        return found

    def git_facts(self, repo, label, diary=False):
        if not os.path.exists(os.path.join(repo, ".git")):
            self.add(cannot("git, %s: not a git repository, so nothing about its commits can be "
                            "told" % label))
            return
        try:
            answer = self.git(repo, ["status", "--porcelain=v2", "--branch", "-z"])
        except GitSilent:
            self.add(cannot("git, %s: git status gave no answer in %s seconds, so nothing about "
                            "its commits can be told" % (label, GIT_TIMEOUT)))
            return
        if answer is None:
            return
        code, out, error = answer
        if code != 0:
            self.add(cannot("git, %s: git status failed: %s" % (label, error)))
            return
        status = parse_status(out)
        paths = status["paths"]
        if paths:
            self.add(problem("git, %s: %s uncommitted" % (label, plural(len(paths), "file"))))
        else:
            self.add(fact("git, %s: nothing uncommitted" % label))
        self.push_facts(repo, label, status)
        self.stash_facts(repo, label)
        if diary and self.args.when == "end" and "DIARY.md" in paths:
            self.add(problem("DIARY.md has changes not committed: commit it before the handover"))

    def push_facts(self, repo, label, status):
        if status["gone"]:
            self.add(problem("git, %s: its upstream %s is gone (deleted on the remote, or never "
                             "fetched), so what is not pushed cannot be counted"
                             % (label, status["upstream"])))
        elif status["upstream"] is None:
            answer = self.git(repo, ["remote"])
            if answer is not None and answer[0] == 0 and not answer[1].strip():
                self.add(fact("git, %s: no remote (local only)" % label))
            else:
                self.add(problem("git, %s: branch %s has a remote but no upstream, so what is not "
                                 "pushed cannot be counted" % (label, status["head"])))
        elif status["ahead"] == 0:
            self.add(fact("git, %s: level with %s (as last fetched)" % (label, status["upstream"])))
        else:
            self.add(problem("git, %s: %s not pushed to %s" % (
                label, plural(status["ahead"], "commit"), status["upstream"])))
            if self.args.when == "end":
                answer = self.git(repo, ["log", "--oneline", "@{u}..HEAD"])
                if answer is not None and answer[0] == 0:
                    for text in answer[1].decode("utf-8", "replace").splitlines():
                        self.add(problem("  not pushed: " + text))

    def stash_facts(self, repo, label):
        try:
            answer = self.git(repo, ["stash", "list", STASH_FORMAT])
        except GitSilent:
            self.add(cannot("git, %s: git stash list gave no answer in %s seconds, so whether it "
                            "has a stash cannot be told" % (label, GIT_TIMEOUT)))
            return
        if answer is None:
            return
        if answer[0] != 0:
            self.add(cannot("git, %s: git stash list failed: %s" % (label, answer[2])))
            return
        stashes = parse_stashes(answer[1])
        advice = STASH_AT_THE_END if self.args.when == "end" else ""
        for name, when, words in stashes:
            self.add(problem("git, %s: %s: %s (made %s)%s" % (label, name, words, when, advice)))
        if not stashes:
            self.add(fact("git, %s: no stash" % label))

    # folders

    def folders(self, conf, mail_root):
        conf = dict(conf)
        conf["FOLDERS"] = ":".join(self.expand(p) for p in folder_list(conf.get("FOLDERS")))
        for what, path in expected_folders(conf, self.args.session, self.home, mail_root):
            if os.path.isdir(path):
                self.add(fact("folder reachable: %s (%s)" % (what, path)))
            else:
                self.add(problem("folder missing: %s, expected at %s" % (what, path)))

    def expand(self, path):
        return self.home + path[1:] if path == "~" or path.startswith("~/") else path

    # leftovers

    def pycache(self, repos):
        found = []
        for here, dirs, _ in os.walk(self.project):
            if "__pycache__" in dirs:
                found.append(os.path.join(here, "__pycache__"))
            dirs[:] = [d for d in dirs if d not in (".git", ".venv", "__pycache__")
                       and not (here == self.project and d == "_to_delete")]
        if not found:
            self.add(fact("__pycache__: none"))
            return
        loose, ignored = [], 0
        for path in sorted(found):
            repo = max((r for r, _ in repos if path.startswith(r + os.sep)), key=len)
            try:
                answer = self.git(repo, ["check-ignore", "-q", os.path.relpath(path, repo)])
            except GitSilent:
                answer = None
            if answer is None:
                self.add(fact("__pycache__: %s (whether git ignores them cannot be told)"
                              % plural(len(found), "folder")))
                return
            if answer[0] == 0:
                ignored += 1
            else:
                loose.append(os.path.relpath(path, self.project))
        if loose:
            self.add(problem("__pycache__: %s not ignored by git: %s (removing %s needs the "
                             "person's OK)" % (plural(len(loose), "folder"), ", ".join(loose),
                                               "it" if len(loose) == 1 else "them")))
        if ignored:
            self.add(fact("__pycache__: %s ignored by git" % plural(ignored, "folder")))

    def locks(self):
        if not os.path.isfile(os.path.join(self.project, "backlog", "config.yml")):
            return
        folder = os.path.join(self.project, "backlog", ".locks")
        inside = sorted(os.listdir(folder)) if os.path.isdir(folder) else []
        if inside:
            self.add(problem("backlog/.locks/ is not empty: %s (removing %s needs the person's "
                             "OK)" % (", ".join(inside), "it" if len(inside) == 1 else "them")))
        else:
            self.add(fact("backlog/.locks/: empty"))

    def to_delete(self):
        folder = os.path.join(self.project, "_to_delete")
        names = sorted(n for n in os.listdir(folder)) if os.path.isdir(folder) else []
        if not names:
            self.add(fact("_to_delete/: none"))
            return
        size = 0
        for name in names:
            path = os.path.join(folder, name)
            size += os.lstat(path).st_size if not os.path.isdir(path) else 0
            for here, _, files in os.walk(path):
                size += sum(os.lstat(os.path.join(here, f)).st_size for f in files)
        last = max(names, key=lambda n: os.lstat(os.path.join(folder, n)).st_ctime)
        self.add(fact("_to_delete/: %s, %s; put there last: %s"
                      % (plural(len(names), "thing"), size_text(size), last)))

    # the diary

    def diary(self, me, mail_root):
        path = os.path.join(self.project, "DIARY.md")
        if not os.path.isfile(path):
            self.add(fact("DIARY.md: none in the project folder"))
            return None
        with open(path, "rb") as handle:
            lines = handle.read().count(b"\n")
        try:
            if mail_root is None:
                raise mail.Failure(mail.EXIT_USAGE, self.root_problem)
            given = last_handover_lines(mail_root, me)
        except mail.Failure as failure:
            self.add(cannot("the mailbox %s could not be read, so the diary cannot be compared "
                            "with the last handover: %s" % (me, failure)))
            return lines
        if given is False:
            self.add(fact("DIARY.md: %d lines; no handover found to compare with" % lines))
        elif given is None:
            self.add(fact("DIARY.md: %d lines; the last handover gave no length" % lines))
        elif lines < given:
            self.add(problem("DIARY.md is shorter than the last handover said: %d lines now, %d "
                             "then. Tell the person before writing anything in it."
                             % (lines, given), first=True))
        else:
            self.add(fact("DIARY.md: %d lines; the last handover gave %d" % (lines, given)))
        return lines

    # what waits

    def waiting(self):
        inbox = os.path.join(self.project, "inbox")
        new = sorted(n for n in os.listdir(inbox) if not n.startswith(".")
                     and n not in ("README.md", "done")) if os.path.isdir(inbox) else []
        self.add(fact("inbox/: %d new: %s" % (len(new), ", ".join(new)) if new
                      else "inbox/: nothing new"))
        dreams = os.path.join(self.project, "dreams")
        undecided = [n for n in os.listdir(dreams) if not n.startswith(".")
                     and os.path.isfile(os.path.join(dreams, n))] if os.path.isdir(dreams) else []
        self.add(fact("dreams/: %d undecided" % len(undecided) if undecided
                      else "dreams/: nothing undecided"))


def last_handover_lines(mail_root, me):
    """The diary length the newest handover gave (None if it gave none), or False when there is
    no handover: the newest message in ME's sent/ addressed to ME."""
    box = mail.mailbox(mail_root, me, "the mailbox")
    newest = None
    folder = box.folder("sent")
    for name in os.listdir(folder):
        if not name.endswith(".md"):
            continue
        with open(os.path.join(folder, name), "rb") as handle:
            parsed = message.parse(handle.read())
        headers = parsed.headers
        if headers and headers["To"] == me and headers["From"] == me:
            key = (headers["Date"], headers["Id"])
            if newest is None or key > newest[0]:
                newest = (key, parsed)
    if newest is None:
        return False
    return handover_diary_lines(newest[1].headers, newest[1].body)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="session-check",
        description="The facts a lobster project's session checks at its start and its end: git, "
                    "connected folders, leftovers, _to_delete/, the diary's length, what waits. "
                    "Reads only; asks nothing; changes nothing. Exit 0: nothing to tell; 1: "
                    "something to tell the person you work for; 2: a wrong argument; 3: "
                    "something cannot be told.")
    parser.add_argument("when", choices=["start", "end"],
                        help="start: the checks at a session's start; end: the same, with each "
                             "commit not pushed, an uncommitted diary, and its length for the "
                             "handover")
    parser.add_argument("--session", choices=["mac", "device"],
                        default=os.environ.get("LOBSTER_MAIL_SESSION") or None,
                        help="where this session runs: mac (Claude Code on the Mac) or device "
                             "(the Linux virtual machine; folders under ~/mnt) (or "
                             "LOBSTER_MAIL_SESSION)")
    parser.add_argument("--project", metavar="DIR",
                        help="the project's folder (default: the working folder)")
    parser.add_argument("--root", metavar="DIR", help=mail.ROOT_HELP)
    parser.add_argument("--as", dest="me", metavar="NAME",
                        help="the project's mailbox (default: SELF in lobster.conf, else the "
                             "folder's name less -code)")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.session not in ("mac", "device"):
        parser.error("--session mac or --session device is required (or set "
                     "LOBSTER_MAIL_SESSION)")
    run = Check(args)
    if not os.path.isdir(run.project):
        print("session-check: the project folder %s does not exist" % run.project,
              file=sys.stderr)
        return EXIT_USAGE
    conf = run.settings()
    me = args.me or conf.get("SELF") or mail.project_name(run.project)
    try:
        mail_root = mail.resolve_root(args)
    except mail.Failure as failure:
        mail_root, run.root_problem = None, str(failure)
    repos = run.repositories()
    for repo, label in repos:
        run.git_facts(repo, label, diary=repo == run.project)
    run.folders(conf, mail_root)
    run.pycache(repos)
    run.locks()
    run.to_delete()
    lines = run.diary(me, mail_root)
    run.waiting()
    if args.when == "end" and lines is not None:
        run.add(fact("for the handover: DIARY.md is %d lines (lobster-mail handover --diary "
                     "DIARY.md records it)" % lines))
    print("== session-check %s for %s (%s), %s ==" % (args.when, me, args.session,
                                                       message.format_date(mail.clock())))
    text, code = report(run.findings)
    print("\n".join(text))
    return code
