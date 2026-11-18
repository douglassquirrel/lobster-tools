"""request new and request send (PLAN.md "`request`", "Settled" 59-61)."""
from conftest import HOSTILE

EMPTY = ("# Request %s\n\nTo: %s\n\n## Need\n\n## Ask\n\n## Test ideas\n\n## Private\n\n"
         "## Missing\n")


def test_new_in_a_mailbox_that_has_sent_no_request_makes_request_01_and_sends_nothing(world):
    before = world.files()
    code, out, err = world.rq("new", "--to", "b", "--title", "Speaker letters")
    path = world.project / "requests" / "request-01-speaker-letters.md"
    assert (code, err) == (0, "")
    assert out == "Made request 01 for b:\n  %s\n" % path
    assert path.read_text("utf-8") == EMPTY % ("01: Speaker letters", "b")
    assert world.files() == before


def test_new_takes_one_more_than_the_highest_number_sent_or_kept(world):
    for n in range(1, 7):
        world.send("a", "b", "Request %02d: tool %d" % (n, n))
    world.send("a", "c", "Request 7: one figure")
    (world.project / "requests").mkdir()
    (world.project / "requests" / "request-08-a-draft.md").write_text("draft\n", "utf-8")
    code, out, _ = world.rq("new", "--to", "b", "--title", "Next")
    assert (code, out) == (0, "Made request 09 for b:\n  %s\n"
                           % (world.project / "requests" / "request-09-next.md"))
    assert world.requests() == ["request-08-a-draft.md", "request-09-next.md"]


def test_a_follow_up_or_addendum_this_mailbox_sent_holds_its_number(world):
    world.send("a", "b", "Request 12 follow-up: more")
    world.send("a", "b", "Request 14, addendum: more")
    world.send("b", "a", "Request 30: theirs, not ours")
    world.send("a", "b", "Requests 40 to 41: a note")
    code, _, _ = world.rq("new", "--to", "b", "--title", "Next")
    assert code == 0
    assert world.requests() == ["request-15-next.md"]


def test_new_twice_without_sending_makes_two_files_with_two_numbers(world):
    world.rq("new", "--to", "b", "--title", "One")
    world.rq("new", "--to", "c", "--title", "Two")
    assert world.requests() == ["request-01-one.md", "request-02-two.md"]


def test_new_with_follows_names_the_earlier_request(world):
    world.send("a", "b", "Request 03: first")
    code, _, err = world.rq("new", "--to", "b", "--title", "Second", "--follows", "3")
    assert (code, err) == (0, "")
    text = (world.project / "requests" / "request-04-second.md").read_text("utf-8")
    assert text.startswith("# Request 04: Second\n\nTo: b\nFollows request 03.\n\n## Need\n")


def test_new_with_follows_of_a_request_this_mailbox_never_made_is_refused(world):
    code, out, err = world.rq("new", "--to", "b", "--title", "Second", "--follows", "5")
    assert (code, out) == (3, "")
    assert err == "request new: a has no request 05 to follow (none sent, no file)\n"
    assert world.requests() == []


def test_new_dry_run_says_what_it_would_write_and_writes_nothing(world):
    code, out, err = world.rq("new", "--to", "b", "--title", "Speaker letters", "--dry-run")
    path = world.project / "requests" / "request-01-speaker-letters.md"
    assert (code, err) == (0, "")
    assert out == "Would make request 01 for b:\n  %s\n" % path
    assert not (world.project / "requests").exists()


def test_new_to_a_mailbox_that_does_not_exist_is_refused(world):
    code, out, err = world.rq("new", "--to", "nobody", "--title", "T")
    assert (code, out) == (3, "")
    assert err.startswith("request new: no mailbox nobody in ")
    assert world.requests() == []


def test_new_refuses_a_title_that_is_empty_or_more_than_one_line(world):
    for title in ("", "  ", "two\nlines"):
        code, _, err = world.rq("new", "--to", "b", "--title", title)
        assert code == 2
        assert err == "request new: the title must be one line and not empty\n"
    assert world.requests() == []


def test_a_non_code_project_keeps_its_requests_in_tools(world):
    (world.project / "lobster.conf").write_text("KIND=non-code\nSELF=a\n", "utf-8")
    code, out, _ = world.rq("new", "--to", "b", "--title", "T")
    assert (code, out) == (0, "Made request 01 for b:\n  %s\n"
                           % (world.project / "tools" / "request-01-t.md"))


def test_folder_names_where_the_request_files_are(world, tmp_path):
    code, _, _ = world.rq("new", "--to", "b", "--title", "T", "--folder", str(tmp_path / "kept"))
    assert code == 0
    assert (tmp_path / "kept" / "request-01-t.md").is_file()


def test_with_no_kind_and_no_folder_the_command_asks_for_folder(world):
    (world.project / "lobster.conf").write_text("SELF=a\n", "utf-8")
    code, out, err = world.rq("new", "--to", "b", "--title", "T")
    assert (code, out) == (2, "")
    assert err == ("request new: lobster.conf in %s says no KIND=code or KIND=non-code, so "
                   "where the request files are is not known; give --folder DIR\n"
                   % world.project)


def test_the_mailbox_is_the_folder_name_less_code_when_lobster_conf_does_not_name_it(world):
    (world.project / "lobster.conf").write_text("KIND=code\n", "utf-8")
    world.send("a", "b", "Request 04: x")
    world.rq("new", "--to", "b", "--title", "T")
    assert world.requests() == ["request-05-t.md"]


def test_send_sends_the_file_as_it_is_with_its_subject_and_keeps_it(world):
    world.rq("new", "--to", "b", "--title", "Speaker letters")
    path = world.fill("01")
    kept = path.read_bytes()
    code, out, err = world.rq("send", "1")
    assert (code, err) == (0, "")
    [delivered] = [k for k in world.files() if k.startswith("b/new/")]
    data = world.files()[delivered]
    assert b"\nSubject: Request 01: Speaker letters\n" in data
    assert data.startswith(b"From: a\nTo: b\n")
    assert data.partition(b"\n\n")[2] == kept
    assert path.read_bytes() == kept
    assert out.startswith("Sent %s to b\n" % delivered[6:-3])


def test_a_hostile_body_is_sent_byte_for_byte(world):
    world.rq("new", "--to", "b", "--title", "Hostile")
    path = world.fill("01", need=HOSTILE.decode("utf-8") + "\n")
    code, _, err = world.rq("send", "01")
    assert (code, err) == (0, "")
    [data] = [v for k, v in world.files().items() if k.startswith("b/new/")]
    assert data.partition(b"\n\n")[2] == path.read_bytes()


def test_send_of_a_number_already_sent_is_refused_and_sends_nothing(world):
    world.rq("new", "--to", "b", "--title", "One")
    world.fill("01")
    world.rq("send", "01")
    before = world.files()
    code, out, err = world.rq("send", "01")
    assert (code, out) == (3, "")
    assert err == ("request send: request 01 was sent already, as "
                   "2026-10-10-0900-a-request-01-one; a request is never sent twice\n")
    assert world.files() == before


def test_send_of_a_number_a_follow_up_already_used_is_refused(world):
    world.send("a", "b", "Request 01 follow-up: more")
    (world.project / "requests").mkdir()
    (world.project / "requests" / "request-01-x.md").write_text(
        EMPTY.replace("## Need\n", "## Need\n\nx\n") % ("01: X", "b"), "utf-8")
    code, _, err = world.rq("send", "1")
    assert code == 3
    assert "request 01 was sent already" in err


def test_send_dry_run_prints_the_subject_the_recipient_and_the_paths_and_writes_nothing(world):
    world.rq("new", "--to", "b", "--title", "One")
    path = world.fill("01")
    before = world.files()
    code, out, err = world.rq("send", "01", "--dry-run")
    assert (code, err) == (0, "")
    assert out.startswith("Would send %s\n" % path)
    assert "Subject: Request 01: One\n" in out
    assert "To: b\n" in out
    assert "  to:   %s/b/new/2026-10-10-0900-a-request-01-one.md\n" % world.root in out
    assert "  copy: %s/a/sent/2026-10-10-0900-a-request-01-one.md\n" % world.root in out
    assert world.files() == before


def test_send_refuses_a_file_whose_five_sections_are_all_empty(world):
    world.rq("new", "--to", "b", "--title", "One")
    code, out, err = world.rq("send", "01")
    assert (code, out) == (3, "")
    assert err == ("request send: %s has nothing under any of its five sections (Need, Ask, "
                   "Test ideas, Private, Missing); write the request first\n"
                   % (world.project / "requests" / "request-01-one.md"))
    assert world.files() == {}


def test_send_of_a_number_with_no_file_is_refused(world):
    code, _, err = world.rq("send", "07")
    assert code == 3
    assert err == ("request send: no request file 07 in %s (request new makes one)\n"
                   % (world.project / "requests"))


def test_send_of_a_number_with_two_files_is_refused_naming_both(world):
    folder = world.project / "requests"
    folder.mkdir()
    for name in ("request-03-x.md", "request-3-y.md"):
        (folder / name).write_text("# Request 03: X\n\nTo: b\n\n## Need\n\nx\n", "utf-8")
    code, _, err = world.rq("send", "3")
    assert code == 3
    assert err == ("request send: two files for request 03 in %s: request-03-x.md, "
                   "request-3-y.md; keep one\n" % folder)
    assert world.files() == {}


def test_send_refuses_a_file_without_its_heading_or_its_to_line(world):
    folder = world.project / "requests"
    folder.mkdir()
    (folder / "request-01-x.md").write_text("Request one\n\nTo: b\n\n## Need\n\nx\n", "utf-8")
    (folder / "request-02-y.md").write_text("# Request 02: Y\n\n## Need\n\nx\n", "utf-8")
    (folder / "request-03-z.md").write_text("# Request 04: Z\n\nTo: b\n\n## Need\n\nx\n", "utf-8")
    code, _, err = world.rq("send", "1")
    assert (code, err) == (3, "request send: %s has no heading \"# Request 01: TITLE\"\n"
                           % (folder / "request-01-x.md"))
    code, _, err = world.rq("send", "2")
    assert (code, err) == (3, "request send: %s has no line \"To: PROJECT\" under its heading\n"
                           % (folder / "request-02-y.md"))
    code, _, err = world.rq("send", "3")
    assert (code, err) == (3, "request send: %s has no heading \"# Request 03: TITLE\"\n"
                           % (folder / "request-03-z.md"))
    assert world.files() == {}


def test_a_number_that_is_not_a_number_is_a_usage_error(world):
    code, _, err = world.rq("send", "seven")
    assert code == 2
    assert "request send: the number must be a whole number, like 07; not 'seven'" in err
