"""request: the bookkeeping of requests between projects. See PLAN.md (outside the checkout).

A request is a message, not a reply, whose subject is exactly "Request N: TITLE"; its replies are
the messages whose In-Reply-To leads back to it. Everything is worked out from this mailbox's own
folders and the project's request files each time it runs, and kept nowhere. The command adds a
request file, sends, replies and closes through lobster-mail's own code; it never edits, deletes
or runs anything, and never reads another project's mailbox.
"""
import argparse
import json
import os
import re
import sys
from collections import namedtuple

from lobstertools import config, mail, message
from lobstertools.mail import EXIT_OK, EXIT_PRECONDITION, EXIT_USAGE, EXIT_WRITE, Failure

SECTIONS = ["Need", "Ask", "Test ideas", "Private", "Missing"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December"]

SUBJECT_RE = re.compile(r"^Request (\d+): (.*\S.*)$")
HELD_RE = re.compile(r"^Request (\d+)(?![\w])")
NAMES_RE = re.compile(r"\bRequests?\b", re.IGNORECASE)
FILE_RE = re.compile(r"^request-(\d+)-.*\.md$")
HEADING_RE = re.compile(r"^# Request (\d+): (.*\S.*)$")
TO_RE = re.compile(r"^To: (\S+)\s*$")

Draft = namedtuple("Draft", "number title to filled")


def request_subject(subject):
    """(number, title) for a subject that is exactly "Request N: TITLE", else None."""
    match = SUBJECT_RE.match(subject)
    return (int(match.group(1)), match.group(2)) if match else None


def held_number(subject):
    """The number a subject this mailbox sent holds: any subject that begins "Request N"."""
    match = HELD_RE.match(subject)
    return int(match.group(1)) if match else None


def names_a_request(subject):
    return bool(NAMES_RE.search(subject))


def next_number(held):
    return max([0] + list(held)) + 1


def file_number(name):
    match = FILE_RE.match(name)
    return int(match.group(1)) if match else None


def file_name(number, title):
    return "request-%02d-%s.md" % (number, message.slug(title))


def draft_text(number, to, title, follows):
    head = "# Request %02d: %s\n\nTo: %s\n" % (number, title, to)
    if follows is not None:
        head += "Follows request %02d.\n" % follows
    return head + "".join("\n## %s\n" % name for name in SECTIONS)


def read_draft(text):
    """The heading's number and title, the To: line, and whether any of the five sections has
    something written under it."""
    number = title = to = None
    filled, current = False, None
    for line in text.splitlines():
        heading = HEADING_RE.match(line)
        if heading and number is None:
            number, title = int(heading.group(1)), heading.group(2)
            current = None
            continue
        recipient = TO_RE.match(line)
        if recipient and to is None and current is None:
            to = recipient.group(1)
            continue
        if line.startswith("#"):
            name = line.lstrip("#").strip()
            current = name if line.startswith("## ") and name in SECTIONS else None
            continue
        if current and line.strip():
            filled = True
    return Draft(number, title, to, filled)


def plan_line(sender, number, id_, date):
    when = message.parse_date(date)
    return "(Request %02d from %s, message `%s`, %d %s %d)" % (
        number, sender, id_, when.day, MONTHS[when.month - 1], when.year)


# The project, its mailbox and its request files

class Project:
    """Where a run works: the project folder, its mailbox, the folder of its request files."""

    def __init__(self, args):
        self.folder = os.path.abspath(args.project or os.getcwd())
        conf = self.settings()
        self.me = args.me or conf.get("SELF") or mail.project_name(self.folder)
        if args.folder:
            self.requests = os.path.abspath(os.path.expanduser(args.folder))
        elif conf.get("KIND") in KIND_FOLDERS:
            self.requests = os.path.join(self.folder, KIND_FOLDERS[conf["KIND"]])
        else:
            raise Failure(EXIT_USAGE, "lobster.conf in %s says no KIND=code or KIND=non-code, so "
                          "where the request files are is not known; give --folder DIR"
                          % self.folder)
        self.box = mail.mailbox(mail.resolve_root(args), self.me, "--as")

    def settings(self):
        path = os.path.join(self.folder, "lobster.conf")
        if not os.path.isfile(path):
            return {}
        try:
            with open(path, encoding="utf-8") as handle:
                return config.parse_conf(handle.read(), os.path.expanduser("~"))
        except (OSError, UnicodeDecodeError, config.ConfigError) as problem:
            raise Failure(EXIT_USAGE, "lobster.conf in %s could not be read: %s"
                          % (self.folder, problem))

    def files(self):
        """{number: [file names]} of the request files kept."""
        found = {}
        if os.path.isdir(self.requests):
            for name in sorted(os.listdir(self.requests)):
                number = file_number(name)
                if number is not None:
                    found.setdefault(number, []).append(name)
        return found

    def messages(self, boxes):
        """Every message with headers in these folders of this mailbox."""
        return list(mail.thread_entries(self.box, boxes).values())

    def sent_holding(self):
        """{number: [ids]} of what this mailbox sent with a subject that begins "Request N"."""
        held = {}
        for entry in self.messages(["sent"]):
            if entry["from"] == self.me and not entry["in_reply_to"]:
                number = held_number(entry["subject"])
                if number is not None:
                    held.setdefault(number, []).append(entry["id"])
        return held


KIND_FOLDERS = {"code": "requests", "non-code": "tools"}


def number_arg(text):
    if not re.match(r"^\d+$", text or ""):
        raise Failure(EXIT_USAGE, "the number must be a whole number, like 07; not %r" % text)
    return int(text)


def check_title(title):
    if not title or not title.strip() or "\n" in title or "\r" in title:
        raise Failure(EXIT_USAGE, "the title must be one line and not empty")
    return title.strip()


def write_new(path, data):
    try:
        mail.write_new_file(path, data)
    except FileExistsError:
        raise Failure(EXIT_PRECONDITION, "%s is there already; nothing written" % path)


# The verbs

def cmd_new(args, stdin=None):
    run = Project(args)
    title = check_title(args.title)
    mail.mailbox(run.box.root, args.to, "--to")
    held = set(run.sent_holding()) | set(run.files())
    if args.follows is not None:
        follows = number_arg(args.follows)
        if follows not in held:
            raise Failure(EXIT_PRECONDITION, "%s has no request %02d to follow (none sent, no file)"
                          % (run.me, follows))
    else:
        follows = None
    number = next_number(held)
    path = os.path.join(run.requests, file_name(number, title))
    if args.dry_run:
        print("Would make request %02d for %s:\n  %s" % (number, args.to, path))
        return EXIT_OK
    os.makedirs(run.requests, exist_ok=True)
    write_new(path, draft_text(number, args.to, title, follows).encode("utf-8"))
    print("Made request %02d for %s:\n  %s" % (number, args.to, path))
    return EXIT_OK


def own_file(run, number):
    names = run.files().get(number, [])
    if not names:
        raise Failure(EXIT_PRECONDITION, "no request file %02d in %s (request new makes one)"
                      % (number, run.requests))
    if len(names) > 1:
        raise Failure(EXIT_PRECONDITION, "two files for request %02d in %s: %s; keep one"
                      % (number, run.requests, ", ".join(names)))
    return os.path.join(run.requests, names[0])


def cmd_send(args, stdin=None):
    run = Project(args)
    number = number_arg(args.number)
    sent = run.sent_holding().get(number)
    if sent:
        raise Failure(EXIT_PRECONDITION, "request %02d was sent already, as %s; a request is never "
                      "sent twice" % (number, ", ".join(sorted(sent))))
    path = own_file(run, number)
    with open(path, "rb") as handle:
        body = handle.read()
    draft = read_draft(body.decode("utf-8", errors="replace"))
    if draft.number != number:
        raise Failure(EXIT_PRECONDITION, "%s has no heading \"# Request %02d: TITLE\""
                      % (path, number))
    if not draft.to:
        raise Failure(EXIT_PRECONDITION, "%s has no line \"To: PROJECT\" under its heading" % path)
    if not draft.filled:
        raise Failure(EXIT_PRECONDITION, "%s has nothing under any of its five sections (%s); "
                      "write the request first" % (path, ", ".join(SECTIONS)))
    them = mail.mailbox(run.box.root, draft.to, "the file's To: line")
    subject = "Request %02d: %s" % (number, draft.title)
    if args.dry_run:
        print("Would send %s" % path)
    return mail.deliver(run.box.root, run.box, them, subject, body, None, args.dry_run, args.json,
                        "Sent", "send")


# The register: worked out from this mailbox and the request files, kept nowhere

ASKED_STATES = ["drafted", "sent", "answered", "closed"]
ASKED_OF_STATES = ["waiting here", "claimed", "answered", "done here"]


def root_of(known, id_):
    """The message a chain of In-Reply-To leads back to, within this mailbox."""
    seen = set()
    while known[id_]["in_reply_to"] in known and id_ not in seen:
        seen.add(id_)
        id_ = known[id_]["in_reply_to"]
    return id_


def days_since(date, now):
    return (now - message.parse_date(date)).days


def days_text(days):
    if days is None:
        return "-"
    return "1 day" if days == 1 else "%d days" % days


def reply_entry(entry):
    return {"id": entry["id"], "from": entry["from"], "date": entry["date"], "box": entry["box"]}


def register(run):
    """What this mailbox asked, what it was asked, and what names a request but is not one."""
    now = mail.clock()
    known = mail.thread_entries(run.box)
    ordered = sorted(known.values(), key=lambda e: (e["date"], e["id"]))
    asked, asked_of = {}, []
    for entry in ordered:
        found = request_subject(entry["subject"])
        if not found or entry["in_reply_to"]:
            continue
        number, title = found
        if entry["box"] == "sent" and entry["from"] == run.me:
            asked.setdefault(number, []).append({
                "number": number, "to": None, "title": title, "state": "sent", "id": entry["id"],
                "date": entry["date"], "days": None, "file": None, "replies": [], "_to": entry})
        elif entry["box"] != "sent" and entry["from"] != run.me:
            asked_of.append(dict(number=number, title=title, state=None, id=entry["id"],
                                 date=entry["date"], box=entry["box"], days=None, replies=[],
                                 **{"from": entry["from"]}))
    own, files = [], run.files()
    for number in sorted(set(asked) | set(files)):
        names = files.get(number, [])
        path = os.path.join(run.requests, names[0]) if names else None
        for item in asked.get(number) or [None]:
            if item is None:
                with open(path, "rb") as handle:
                    draft = read_draft(handle.read().decode("utf-8", errors="replace"))
                item = {"number": number, "to": draft.to, "title": draft.title or names[0],
                        "state": "drafted", "id": None, "date": None, "days": None,
                        "file": path, "replies": []}
            else:
                item["to"] = mail.parsed_message(item.pop("_to")["path"]).headers["To"]
                item["file"] = path
            own.append(item)
    by_id = {item["id"]: item for item in own + asked_of if item["id"]}
    counted = set(by_id)
    not_counted = []
    for entry in ordered:
        root = root_of(known, entry["id"])
        if entry["id"] in counted:
            continue
        if root in counted:
            item = by_id[root]
            mine = entry["from"] == run.me
            if ("to" in item and not mine and entry["box"] != "sent") or \
                    ("to" not in item and mine and entry["box"] == "sent"):
                item["replies"].append(reply_entry(entry))
            continue
        if names_a_request(entry["subject"]):
            not_counted.append({"id": entry["id"], "box": entry["box"], "from": entry["from"],
                                "subject": entry["subject"]})
    for item in own:
        if item["state"] == "drafted":
            continue
        waiting = [r for r in item["replies"] if r["box"] in ("new", "open")]
        item["state"] = "answered" if waiting else "closed" if item["replies"] else "sent"
        item["days"] = None if item["state"] == "closed" else days_since(item["date"], now)
    for item in asked_of:
        item["state"] = ("done here" if item["box"] == "done" else "answered" if item["replies"]
                         else "claimed" if item["box"] == "open" else "waiting here")
        item["days"] = None if item["state"] == "done here" else days_since(item["date"], now)
    not_counted.sort(key=lambda e: e["id"])
    return own, asked_of, not_counted


ROW = "  %02d  %-16s  %-10s  %-12s  %-7s  %s"


def cmd_list(args, stdin=None):
    run = Project(args)
    own, asked_of, not_counted = register(run)
    if args.open:
        own = [item for item in own if item["state"] != "closed"]
        asked_of = [item for item in asked_of if item["state"] != "done here"]
        not_counted = []
    if args.json:
        print(json.dumps({"mailbox": run.me, "asked": own, "asked_of": asked_of,
                          "not_counted": not_counted}, indent=1))
        return EXIT_OK
    if not (own or asked_of or not_counted):
        print("No %srequests for or from %s" % ("open " if args.open else "", run.me))
        return EXIT_OK
    if own:
        print("Asked by %s (%d):" % (run.me, len(own)))
        for item in own:
            print(ROW % (item["number"], "to %s" % (item["to"] or "?"), (item["date"] or "-")[:10],
                         item["state"], days_text(item["days"]), item["title"]))
    if asked_of:
        print("Asked of %s (%d):" % (run.me, len(asked_of)))
        for item in asked_of:
            print(ROW % (item["number"], "from %s" % item["from"], item["date"][:10],
                         item["state"], days_text(item["days"]), item["title"]))
    if not_counted:
        print("Not counted, named as requests but not \"Request N: TITLE\" (%d):"
              % len(not_counted))
        for entry in not_counted:
            print("  %s  %s/  %s" % (entry["id"], entry["box"], entry["subject"]))
    return EXIT_OK


def print_body(data):
    out = getattr(sys.stdout, "buffer", None)
    if out is not None:
        sys.stdout.flush()
        out.write(data)
        out.flush()
    else:
        sys.stdout.write(data.decode("utf-8", errors="replace"))


def reply_lines(item):
    for reply in item["replies"]:
        print("  reply from %s, %s, %s (%s/)" % (reply["from"], reply["date"], reply["id"],
                                                  reply["box"]))


def show_own(run, number, args):
    own, _, _ = register(run)
    found = [item for item in own if item["number"] == number]
    if not found:
        raise Failure(EXIT_PRECONDITION, "%s has no request %02d: none sent, no file"
                      % (run.me, number))
    if len(found) > 1:
        raise Failure(EXIT_PRECONDITION, "request %02d was sent more than once: %s; read each with "
                      "lobster-mail read ID" % (number, ", ".join(i["id"] for i in found)))
    item = dict(found[0])
    kept = None
    if item["file"]:
        with open(item["file"], "rb") as handle:
            kept = handle.read()
    body, differs = kept, False
    if item["id"]:
        body = mail.parsed_message(run.box.file("sent", item["id"])).body
        differs = kept is not None and message.body_hash(kept) != message.body_hash(body)
    if args.json:
        item.update(differs=differs, body=body.decode("utf-8", errors="replace"))
        print(json.dumps(item, indent=1))
        return EXIT_OK
    print("Request %02d: %s" % (number, item["title"]))
    if item["id"]:
        print("  to %s; sent %s as %s" % (item["to"], item["date"], item["id"]))
    else:
        print("  to %s; drafted, not sent" % (item["to"] or "?"))
    print("  state: %s" % item["state"])
    reply_lines(item)
    if item["file"]:
        print("  file: %s" % item["file"])
    if differs:
        print("  the file differs from what was sent (its SHA-256 is not the sent copy's "
              "Body-SHA-256)")
    print()
    print_body(body)
    return EXIT_OK


def asked_of_one(run, sender, number, verb_text):
    _, asked_of, _ = register(run)
    found = [item for item in asked_of if item["from"] == sender and item["number"] == number]
    if not found:
        raise Failure(EXIT_PRECONDITION, "no request %02d from %s in %s's mailbox"
                      % (number, sender, run.me))
    if len(found) > 1:
        raise Failure(EXIT_PRECONDITION, "two requests %02d from %s: %s; %s"
                      % (number, sender, ", ".join(i["id"] for i in found), verb_text))
    return found[0]


def show_asked_of(run, sender, number, args):
    item = dict(asked_of_one(run, sender, number, "read each with lobster-mail read ID"))
    body = mail.parsed_message(run.box.file(item["box"], item["id"])).body
    line = plan_line(sender, number, item["id"], item["date"])
    if args.json:
        item.update(plan_line=line, body=body.decode("utf-8", errors="replace"))
        print(json.dumps(item, indent=1))
        return EXIT_OK
    print("Request %02d from %s: %s" % (number, sender, item["title"]))
    print("  received %s as %s (%s/)" % (item["date"], item["id"], item["box"]))
    print("  state: %s" % item["state"])
    reply_lines(item)
    print("  for PLAN.md: %s" % line)
    print()
    print_body(body)
    return EXIT_OK


def cmd_show(args, stdin=None):
    if len(args.what) not in (1, 2):
        raise Failure(EXIT_USAGE, "give NN for this project's own request, or PROJECT NN for one "
                      "it was asked")
    number = number_arg(args.what[-1])
    run = Project(args)
    if len(args.what) == 1:
        return show_own(run, number, args)
    return show_asked_of(run, mail.check_name(args.what[0], "PROJECT"), number, args)


def cmd_answer(args, stdin=None):
    run = Project(args)
    number = number_arg(args.number)
    sender = mail.check_name(args.project_name, "PROJECT")
    item = asked_of_one(run, sender, number, "answer the one meant with lobster-mail reply ID")
    them = mail.mailbox(run.box.root, sender, "PROJECT")
    body = mail.read_body(args.body, stdin)
    subject = "Re: Request %02d: %s" % (number, item["title"])
    return mail.deliver(run.box.root, run.box, them, subject, body, item["id"], args.dry_run,
                        args.json, "Replied", "reply")


def cmd_close(args, stdin=None):
    run = Project(args)
    number = number_arg(args.number)
    own, _, _ = register(run)
    found = [item for item in own if item["number"] == number]
    if not found:
        raise Failure(EXIT_PRECONDITION, "%s has no request %02d: none sent, no file"
                      % (run.me, number))
    replies = [r for item in found for r in item["replies"]]
    waiting = [r for r in replies if r["box"] in ("new", "open")]
    if not replies:
        raise Failure(EXIT_PRECONDITION, "request %02d has no reply yet; nothing to close" % number)
    if not waiting:
        raise Failure(EXIT_PRECONDITION, "every reply to request %02d is in done/ already" % number)
    for reply in waiting:
        if args.dry_run:
            print("Would move %s: %s/ -> done/" % (reply["id"], reply["box"]))
            continue
        where, _ = mail.move(run.box, reply["id"], ["new", "open"], "done",
                             lambda now_in, id_=reply["id"]: "%s moved to %s/ meanwhile"
                             % (id_, now_in))
        print("Done %s: %s/ -> done/" % (reply["id"], where))
    return EXIT_OK


COMMANDS = {"new": cmd_new, "send": cmd_send, "list": cmd_list, "show": cmd_show,
            "answer": cmd_answer, "close": cmd_close}


def build_parser():
    parser = argparse.ArgumentParser(
        prog="request",
        description="The bookkeeping of requests between projects, worked out from the mail: "
                    "the next number's file, sending it, the register of requests asked and "
                    "asked of this project, answering and closing. It decides nothing, and never "
                    "edits, deletes or runs anything.")
    verbs = parser.add_subparsers(dest="verb", metavar="VERB")

    def verb(name, help_, json_=True, dry_run=False):
        sub = verbs.add_parser(name, help=help_, description=help_)
        sub.add_argument("--as", dest="me", metavar="ME",
                         help="the project's mailbox (default: SELF in lobster.conf, else the "
                              "folder's name less -code)")
        sub.add_argument("--root", metavar="DIR", help=mail.ROOT_HELP)
        sub.add_argument("--project", metavar="DIR",
                         help="the project's folder (default: the working folder)")
        sub.add_argument("--folder", metavar="DIR",
                         help="where the request files are (default: requests/ for KIND=code, "
                              "tools/ for KIND=non-code, in lobster.conf)")
        if json_:
            sub.add_argument("--json", action="store_true", help="print the result as JSON")
        if dry_run:
            sub.add_argument("--dry-run", action="store_true",
                             help="say what would be done, and write nothing")
        return sub

    sub = verb("new", "make the file for the next request: the next number, a heading, the "
               "recipient and the five empty sections; it sends nothing", json_=False,
               dry_run=True)
    sub.add_argument("--to", required=True, metavar="PROJECT", help="the project to be asked")
    sub.add_argument("--title", required=True, metavar="TEXT", help="one line, not empty")
    sub.add_argument("--follows", metavar="NN",
                     help="the earlier request of this project's this one corrects or adds to")

    sub = verb("send", "send request NN's file, as it is, to the project on its To: line, with "
               "the subject \"Request NN: TITLE\"", dry_run=True)
    sub.add_argument("number", metavar="NN")

    sub = verb("list", "the register, worked out from the mail each time: each request this "
               "project asked and each it was asked, with how it stands; reads only")
    sub.add_argument("--open", action="store_true", help="only what is not closed")

    sub = verb("show", "one request: its text, the ids and dates of it and its replies, and how "
               "it stands; reads only")
    sub.add_argument("what", nargs="+", metavar="[PROJECT] NN",
                     help="NN: this project's own request; PROJECT NN: one it was asked")

    sub = verb("answer", "reply to PROJECT's request NN with FILE, as lobster-mail reply does",
               dry_run=True)
    sub.add_argument("project_name", metavar="PROJECT", help="the project that asked")
    sub.add_argument("number", metavar="NN", help="its number for the request")
    sub.add_argument("body", metavar="FILE", help="the answer: a file, or - for standard input")

    sub = verb("close", "mark the replies to this project's request NN dealt with (new or open "
               "-> done), as lobster-mail done does", json_=False, dry_run=True)
    sub.add_argument("number", metavar="NN")
    return parser


def main(argv=None, stdin=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.verb is None:
        parser.print_usage(sys.stderr)
        print("request: a verb is needed: " + ", ".join(COMMANDS), file=sys.stderr)
        return EXIT_USAGE
    try:
        return COMMANDS[args.verb](args, stdin)
    except Failure as failure:
        print("request %s: %s" % (args.verb, failure), file=sys.stderr)
        return failure.code
    except OSError as problem:
        print("request %s: could not write: %s" % (args.verb, problem), file=sys.stderr)
        return EXIT_WRITE
