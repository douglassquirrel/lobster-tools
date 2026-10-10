"""The message format: header lines, a blank line, the body, byte for byte.

    From: training-video
    To: video-tools
    Date: 2026-10-10T07:29:17Z
    Subject: Request 11: phonemes
    Id: 2026-10-10-0829-training-video-request-11-phonemes
    In-Reply-To: <id>            (only on a reply)
    Body-SHA-256: <hex>

    <the body, exactly as the sender wrote it>

A file whose first lines are not a complete header block is a message dropped in by hand: its
whole content is the body and it has no headers.
"""
import hashlib
import re
import unicodedata
from collections import namedtuple
from datetime import datetime, timezone

REQUIRED = ["From", "To", "Date", "Subject", "Id", "Body-SHA-256"]
ORDER = ["From", "To", "Date", "Subject", "Id", "In-Reply-To", "Body-SHA-256"]
SLUG_LENGTH = 40

Parsed = namedtuple("Parsed", "headers body")


def body_hash(body):
    return hashlib.sha256(body).hexdigest()


def render(headers, body):
    lines = ["%s: %s" % (key, headers[key]) for key in ORDER if key in headers]
    return ("\n".join(lines) + "\n\n").encode("utf-8") + body


def parse(data):
    head, sep, body = data.partition(b"\n\n")
    if not sep:
        return Parsed(None, data)
    headers = {}
    for line in head.split(b"\n"):
        match = re.match(rb"^([A-Za-z][A-Za-z0-9-]*): (.*)$", line)
        if not match:
            return Parsed(None, data)
        try:
            headers[match.group(1).decode("ascii")] = match.group(2).decode("utf-8")
        except UnicodeDecodeError:
            return Parsed(None, data)
    if any(key not in headers for key in REQUIRED):
        return Parsed(None, data)
    return Parsed(headers, body)


def slug(text):
    plain = unicodedata.normalize("NFKD", text)
    plain = "".join(ch for ch in plain if not unicodedata.combining(ch)).lower()
    plain = re.sub(r"[^a-z0-9]+", "-", plain).strip("-")
    plain = plain[:SLUG_LENGTH].rstrip("-")
    return plain or "message"


def format_date(now):
    """Every stamp the tool writes is UTC and says so with Z, whatever clock the sender has."""
    return now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_date(text):
    """Reads a stamp back: the Z form, or an offset form (Python 3.9 cannot read Z itself)."""
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def make_id(now, sender, subject):
    """The minute is UTC, so ids from senders in different time zones sort by true time."""
    utc = now.astimezone(timezone.utc)
    return "%s-%s-%s" % (utc.strftime("%Y-%m-%d-%H%M"), sender, slug(subject))


def unique_id(base, taken):
    candidate, counter = base, 1
    while candidate in taken:
        counter += 1
        candidate = "%s-%d" % (base, counter)
    return candidate
