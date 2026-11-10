"""The checks on a reported status and its --until time (PLAN.md "A status a session reports about
itself")."""
import pytest

from lobstertools import mail


def refused(check, value):
    with pytest.raises(mail.Failure) as caught:
        check(value)
    assert caught.value.code == mail.EXIT_USAGE
    return str(caught.value)


def test_a_status_is_kept_as_given_with_only_its_ends_trimmed():
    assert mail.check_status_text("  dreaming  ") == "dreaming"
    hostile = "waiting for \"Squirrel\" $(x) `y` \\ café 日本 ✓ </script>"
    assert mail.check_status_text(hostile) == hostile


def test_a_status_of_exactly_60_characters_is_accepted_and_61_refused():
    assert mail.check_status_text("x" * 60) == "x" * 60
    message = refused(mail.check_status_text, "x" * 61)
    assert message == "the status must be one line of 1 to 60 characters; this one has 61"


def test_an_empty_or_blank_status_is_refused():
    for blank in ("", "   "):
        assert refused(mail.check_status_text, blank) == (
            "the status must be one line of 1 to 60 characters; this one is empty "
            "(use --clear to clear it)")


def test_a_status_with_a_newline_or_other_control_character_is_refused():
    for text in ("dreaming\nnext line", "dreaming\r", "a\tb", "bell\x07"):
        assert refused(mail.check_status_text, text) == (
            "the status must be one line of plain text, without newlines, tabs or other "
            "control characters")


def test_until_in_z_form_is_kept_and_an_offset_is_stored_as_utc():
    assert mail.check_until("2026-11-10T16:30:00Z") == "2026-11-10T16:30:00Z"
    assert mail.check_until("2026-11-10T17:30:00+01:00") == "2026-11-10T16:30:00Z"


def test_until_already_past_is_accepted():
    assert mail.check_until("2000-01-01T00:00:00Z") == "2000-01-01T00:00:00Z"


def test_until_that_is_not_a_time_or_has_no_zone_is_refused():
    for text in ("tomorrow", "2026-11-10", "2026-11-10T16:30:00", "16:30Z", ""):
        assert refused(mail.check_until, text) == (
            "--until %r is not a time with a zone; give it as 2026-11-10T16:30:00Z" % text)
