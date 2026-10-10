import hashlib
from datetime import datetime, timedelta, timezone

from lobstertools import message

LONDON = timezone(timedelta(hours=1))
NOW = datetime(2026, 10, 10, 8, 29, 17, tzinfo=LONDON)
HOSTILE = (
    b"From: evil\nSubject: not a header\n\n# Title\n\n$(rm -rf /) `x` \\ \"q\" 'q'\n"
    b"</script>\n---\nid: fake\n\xe2\x9c\x93 caf\xc3\xa9 \xe6\x97\xa5\xe6\x9c\xac\n"
    b"trailing spaces   \nno final newline"
)
HEADERS = {
    "From": "training-video",
    "To": "video-tools",
    "Date": "2026-10-10T08:29:17+01:00",
    "Subject": "Request 11: phonemes",
    "Id": "2026-10-10-0829-training-video-request-11-phonemes",
    "Body-SHA-256": hashlib.sha256(HOSTILE).hexdigest(),
}


def test_body_hash_is_the_sha256_of_the_body_bytes():
    assert message.body_hash(HOSTILE) == hashlib.sha256(HOSTILE).hexdigest()


def test_render_then_parse_round_trips_headers_and_a_hostile_body():
    data = message.render(HEADERS, HOSTILE)
    assert data.startswith(b"From: training-video\nTo: video-tools\n")
    parsed = message.parse(data)
    assert parsed.headers == HEADERS
    assert parsed.body == HOSTILE


def test_render_puts_in_reply_to_only_when_given():
    assert b"In-Reply-To" not in message.render(HEADERS, b"x")
    with_reply = dict(HEADERS, **{"In-Reply-To": "2026-10-10-0742-training-video-ticks"})
    data = message.render(with_reply, b"x")
    assert b"\nIn-Reply-To: 2026-10-10-0742-training-video-ticks\n" in data
    assert message.parse(data).headers["In-Reply-To"] == "2026-10-10-0742-training-video-ticks"


def test_a_file_without_a_complete_header_block_is_hand_dropped():
    parsed = message.parse(b"From: someone\nSubject: a note\n\nJust dropped in by hand.\n")
    assert parsed.headers is None
    assert parsed.body == b"From: someone\nSubject: a note\n\nJust dropped in by hand.\n"
    assert message.parse(b"no headers at all").headers is None
    assert message.parse(b"").headers is None


def test_slug_lowercases_hyphenates_strips_accents_and_cuts_at_40():
    assert message.slug("Request 11: Phonemes for the voice, where spelling can't fix it") == (
        "request-11-phonemes-for-the-voice-where"
    )
    assert message.slug("Café ✓ naïve — dash") == "cafe-naive-dash"
    assert message.slug("???") == "message"
    assert message.slug("") == "message"


def test_date_header_is_utc_to_the_second_marked_z_whatever_the_senders_clock():
    assert message.format_date(NOW) == "2026-10-10T07:29:17Z"
    assert message.format_date(NOW.astimezone(timezone.utc)) == "2026-10-10T07:29:17Z"


def test_parse_date_reads_the_z_form_back_and_the_old_offset_form():
    assert message.parse_date("2026-10-10T07:29:17Z") == NOW
    assert message.parse_date("2026-10-10T08:29:17+01:00") == NOW


def test_id_takes_its_minute_in_utc_whatever_the_senders_clock():
    utc = "2026-10-10-0729-training-video-request-11-phonemes-for-the-voice"
    assert message.make_id(NOW, "training-video", "Request 11: Phonemes for the voice") == utc
    assert message.make_id(NOW.astimezone(timezone.utc), "training-video",
                           "Request 11: Phonemes for the voice") == utc


def test_unique_id_appends_a_counter_when_the_name_is_taken():
    assert message.unique_id("a-b", set()) == "a-b"
    assert message.unique_id("a-b", {"a-b"}) == "a-b-2"
    assert message.unique_id("a-b", {"a-b", "a-b-2"}) == "a-b-3"
