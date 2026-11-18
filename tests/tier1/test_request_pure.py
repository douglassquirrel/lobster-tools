"""request's pure parts: which subjects are requests, which hold a number, the next number, the
file a draft is written as, and reading a draft back (PLAN.md "`request`", "Settled" 59-62)."""
import pytest

from lobstertools import request


@pytest.mark.parametrize("subject, expected", [
    ("Request 7: speaker letters", (7, "speaker letters")),
    ("Request 07: speaker letters", (7, "speaker letters")),
    ("Request 126: a: b", (126, "a: b")),
    ("Request: an unnumbered one", None),
    ("Request 18 follow-up: more", None),
    ("Request 9, addendum: more", None),
    ("Re: Request 3: an answer", None),
    ("Update on Request 4: news", None),
    ("Request 5:", None),
    ("request 5: lower case", None),
])
def test_only_a_subject_of_exactly_request_n_colon_title_is_a_request(subject, expected):
    assert request.request_subject(subject) == expected


@pytest.mark.parametrize("subject, expected", [
    ("Request 12: a title", 12),
    ("Request 7: one figure", 7),
    ("Request 18 follow-up: more", 18),
    ("Request 9, addendum: more", 9),
    ("Request 5 (re Request 3): more", 5),
    ("Request 4", 4),
    ("Request: unnumbered", None),
    ("Requests 1 to 3: a note", None),
    ("Re: Request 3: an answer", None),
    ("Request 12a: odd", None),
    ("Note on Request 20: x", None),
])
def test_a_subject_that_begins_request_n_holds_the_number(subject, expected):
    assert request.held_number(subject) == expected


@pytest.mark.parametrize("subject, expected", [
    ("Request: unnumbered", True),
    ("Note on Requests 1 to 3: x", True),
    ("Update on Request 4: news", True),
    ("Re: Request 18 follow-up: more", True),
    ("Notice: the rules changed", False),
    ("Handover 2026-11-15 22:04Z", False),
    ("Requested by nobody", False),
])
def test_a_subject_names_a_request_when_it_has_the_word(subject, expected):
    assert request.names_a_request(subject) is expected


@pytest.mark.parametrize("held, expected", [([], 1), ([1, 2, 7], 8), ([9, 3], 10), ([0], 1)])
def test_the_next_number_is_one_more_than_the_highest_held(held, expected):
    assert request.next_number(held) == expected


@pytest.mark.parametrize("name, expected", [
    ("request-07-use-prepare-venv.md", 7),
    ("request-7-old.md", 7),
    ("request-126-x.md", 126),
    ("README.md", None),
    ("request-x.md", None),
    ("request-07-x.txt", None),
    (".request-07-x.md", None),
])
def test_a_request_file_is_named_request_number_slug(name, expected):
    assert request.file_number(name) == expected


def test_the_draft_has_the_heading_the_recipient_and_five_empty_sections():
    assert request.draft_text(9, "video-tools", "Speaker letters", None) == (
        "# Request 09: Speaker letters\n\nTo: video-tools\n\n"
        "## Need\n\n## Ask\n\n## Test ideas\n\n## Private\n\n## Missing\n")


def test_a_draft_that_follows_another_says_so():
    text = request.draft_text(12, "b", "More", 7)
    assert text.startswith("# Request 12: More\n\nTo: b\nFollows request 07.\n\n## Need\n")


def test_the_file_name_is_the_number_and_the_slug_of_the_title():
    assert request.file_name(3, "A café: the Plan!") == "request-03-a-cafe-the-plan.md"
    assert request.file_name(104, "x") == "request-104-x.md"


def test_a_fresh_draft_reads_back_with_its_number_title_recipient_and_nothing_filled():
    draft = request.read_draft(request.draft_text(9, "video-tools", "Speaker letters", 4))
    assert draft == request.Draft(9, "Speaker letters", "video-tools", False)


def test_a_draft_with_one_section_written_counts_as_filled():
    text = request.draft_text(2, "b", "T", None).replace("## Ask\n", "## Ask\n\nA tool.\n")
    assert request.read_draft(text).filled is True


def test_text_under_a_heading_that_is_not_one_of_the_five_does_not_fill_it():
    text = request.draft_text(2, "b", "T", None) + "\n## Notes\n\nSomething.\n"
    assert request.read_draft(text).filled is False


def test_a_draft_without_its_heading_or_recipient_reads_as_none_for_them():
    draft = request.read_draft("Some text\n\n## Need\n\nx\n")
    assert draft == request.Draft(None, None, None, True)


def test_the_plan_line_names_the_request_the_asker_the_message_and_the_day():
    assert request.plan_line("bernstein", 26, "2026-11-18-0840-bernstein-request-26-x",
                             "2026-11-18T08:40:57Z") == (
        "(Request 26 from bernstein, message `2026-11-18-0840-bernstein-request-26-x`, "
        "18 November 2026)")
