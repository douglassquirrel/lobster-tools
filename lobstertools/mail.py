"""lobster-mail: a file-based mail system between projects. See PLAN.md (outside the checkout).

One folder per mailbox, one Markdown file per message, state kept as the folder a message is in.
The tool adds files and renames them; it never edits, deletes or runs anything.
"""
import argparse
import os
import sys

VERBS = ["init", "send", "reply", "check", "list", "read", "ack", "done", "thread", "watch", "duty"]
BOXES = ["new", "open", "done", "sent"]
AS_HELP = "the mailbox this run acts for, named as the project is (or LOBSTER_MAIL_AS)"
ROOT_HELP = "the mail root (or LOBSTER_MAIL_ROOT, or MAIL_ROOT in ~/.lobster-tools.conf)"


def build_parser():
    parser = argparse.ArgumentParser(
        prog="lobster-mail",
        description="File-based mail between projects: one folder per mailbox, one file per "
        "message, never edited, never deleted.",
    )
    verbs = parser.add_subparsers(dest="verb", metavar="VERB")

    def verb(name, help_, me=True, json_=True, dry_run=False):
        sub = verbs.add_parser(name, help=help_, description=help_)
        sub.add_argument("--root", metavar="DIR", help=ROOT_HELP)
        if me:
            sub.add_argument("--as", dest="me", metavar="ME", help=AS_HELP)
        if json_:
            sub.add_argument("--json", action="store_true", help="print the result as JSON")
        if dry_run:
            sub.add_argument(
                "--dry-run", action="store_true", help="do everything but the write or the move"
            )
        return sub

    sub = verb("init", "make a mailbox (and the mail root, if missing)", me=False, dry_run=True)
    sub.add_argument("name", metavar="NAME", help="the mailbox, named as the project folder is")

    sub = verb("send", "send a message to another mailbox", dry_run=True)
    sub.add_argument("--to", required=True, metavar="THEM", help="the recipient mailbox")
    sub.add_argument("--subject", required=True, metavar="TEXT", help="one line, not empty")
    sub.add_argument("body", metavar="BODY.md", help="the body file, or - for standard input")

    sub = verb("reply", "reply to a message in my mailbox", dry_run=True)
    sub.add_argument("id", metavar="ID")
    sub.add_argument("body", metavar="BODY.md", help="the body file, or - for standard input")
    sub.add_argument("--subject", metavar="TEXT", help="default: Re: and the original's subject")

    verb("check", "list new mail, oldest first")

    sub = verb("list", "list a folder of my mailbox, or all four")
    group = sub.add_mutually_exclusive_group()
    for box in BOXES:
        group.add_argument("--" + box, dest="box", action="store_const", const=box)

    sub = verb("read", "print a message in full, moving nothing", json_=False)
    sub.add_argument("id", metavar="ID")

    sub = verb("ack", "claim a new message (new -> open) and print it", dry_run=True)
    sub.add_argument("id", metavar="ID")

    sub = verb("done", "mark a message dealt with (new or open -> done)", dry_run=True)
    sub.add_argument("id", metavar="ID")

    sub = verb("thread", "print the chain of replies around a message")
    sub.add_argument("id", metavar="ID")

    sub = verb("watch", "wait until there is new mail, then list it")
    sub.add_argument("--timeout", type=float, default=0, metavar="SECONDS", help="0: forever")
    sub.add_argument("--every", type=float, default=2, metavar="SECONDS", help="how often to look")

    sub = verb("duty", "take, keep, release or show the duty of watching a mailbox")
    sub.add_argument("action", choices=["take", "beat", "release", "status"])
    sub.add_argument("--session", metavar="NAME", help="the session taking or holding the duty")
    sub.add_argument(
        "--stale", type=float, default=45, metavar="MINUTES", help="a heartbeat older than this is stale"
    )
    return parser


def main(argv=None, stdin=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.verb is None:
        parser.print_usage(sys.stderr)
        print("lobster-mail: a verb is needed: " + ", ".join(VERBS), file=sys.stderr)
        return 2
    if hasattr(args, "me") and not args.me:
        args.me = os.environ.get("LOBSTER_MAIL_AS") or None
        if not args.me:
            parser.error("--as NAME is required (or set LOBSTER_MAIL_AS)")
    return 0
