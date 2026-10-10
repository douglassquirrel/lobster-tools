"""The message format: header lines, a blank line, the body, byte for byte.

    From: training-video
    To: video-tools
    Date: 2026-10-10T08:29:17+01:00
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
    return now.isoformat(timespec="seconds")


def make_id(now, sender, subject):
    return "%s-%s-%s" % (now.strftime("%Y-%m-%d-%H%M"), sender, slug(subject))


def unique_id(base, taken):
    candidate, counter = base, 1
    while candidate in taken:
        counter += 1
        candidate = "%s-%d" % (base, counter)
    return candidate
