"""session-check's pure parts: the handover's diary length, the folders a session should reach,
git's porcelain status, sizes, and how findings become the report and its exit code."""
import pytest

from lobstertools import check

# The diary length the last handover gave

def test_the_diary_lines_header_is_read_first():
    headers = {"Diary-Lines": "2421"}
    assert check.handover_diary_lines(headers, b"DIARY.md is 100 lines.\n") == 2421


def test_without_the_header_the_lines_after_diary_md_in_the_body_are_read():
    body = b"Stopped at noon.\nDIARY.md's length: 2,383 lines.\n"
    assert check.handover_diary_lines({}, body) == 2383


def test_the_first_number_of_lines_close_after_diary_md_counts():
    body = b"READ DIARY.md \"Where things stand\" FIRST. DIARY.md is 5843 lines; 12 lines added.\n"
    assert check.handover_diary_lines({}, body) == 5843


def test_lines_far_from_diary_md_or_before_it_do_not_count():
    body = (b"Wrote 300 lines of tests. Read DIARY.md, then PLAN.md, then the code, then the "
            b"README, which has 40 lines of usage.\n")
    assert check.handover_diary_lines({}, body) is None


def test_a_handover_that_gives_no_length_gives_none():
    assert check.handover_diary_lines({}, b"Nothing in progress.\n") is None


def test_a_header_that_is_not_a_number_falls_back_to_the_body():
    assert check.handover_diary_lines({"Diary-Lines": "many"}, b"DIARY.md: 12 lines\n") == 12


# The folders a session should be able to reach

CONF = {"SISTER": "online-publishing", "CLAWS": "word-tools  google-docs-tools",
        "FOLDERS": "/Users/sq/models/kokoro /Users/sq/Big Files"}


def test_the_device_shell_expects_each_named_project_and_folder_under_mnt():
    found = check.expected_folders(dict(CONF, FOLDERS="/Users/sq/models/kokoro"), "device",
                                   "/home/u", "/home/u/mnt/mail")
    assert found == [
        ("SISTER online-publishing", "/home/u/mnt/online-publishing"),
        ("CLAWS word-tools", "/home/u/mnt/word-tools"),
        ("CLAWS google-docs-tools", "/home/u/mnt/google-docs-tools"),
        ("FOLDERS kokoro", "/home/u/mnt/kokoro"),
        ("the mail folder", "/home/u/mnt/mail"),
        ("lobster-tools", "/home/u/mnt/lobster-tools"),
    ]


def test_on_the_mac_only_the_named_folders_and_the_mail_root_are_expected():
    found = check.expected_folders(dict(CONF, FOLDERS="/Users/sq/models/kokoro"), "mac",
                                   "/Users/sq", "/Users/sq/projects/mail")
    assert found == [
        ("FOLDERS /Users/sq/models/kokoro", "/Users/sq/models/kokoro"),
        ("the mail root", "/Users/sq/projects/mail"),
    ]


@pytest.mark.parametrize("value, parts", [
    ("/a/one:/a/two", ["/a/one", "/a/two"]),
    ("~/models/one:~/models/two", ["~/models/one", "~/models/two"]),
    (" /a/one : /a/two ", ["/a/one", "/a/two"]),
    ("/a/one::/a/two:", ["/a/one", "/a/two"]),
    ("/a/my folder", ["/a/my folder"]),
    ("  /a/my folder  ", ["/a/my folder"]),
    ("/a/one", ["/a/one"]),
    ("", []),
    ("   ", []),
    (":", []),
])
def test_folders_are_separated_by_colons_and_a_line_without_one_is_one_path(value, parts):
    assert check.folder_list(value) == parts


def test_two_folders_by_colon_on_the_device_are_two_names_under_mnt():
    found = check.expected_folders({"FOLDERS": "/Users/sq/one:/Users/sq/Big Files"}, "device",
                                   "/home/u", None)
    assert found[:2] == [("FOLDERS one", "/home/u/mnt/one"),
                         ("FOLDERS Big Files", "/home/u/mnt/Big Files")]


def test_empty_settings_expect_only_the_mail_and_lobster_tools():
    conf = {"SISTER": "", "CLAWS": "", "FOLDERS": ""}
    assert check.expected_folders(conf, "device", "/h", "/h/mnt/mail") == [
        ("the mail folder", "/h/mnt/mail"), ("lobster-tools", "/h/mnt/lobster-tools")]
    assert check.expected_folders({}, "mac", "/h", None) == []


# git's porcelain v2 status, as "Things checked" 10 records it

def z(*items):
    return b"".join(i + b"\0" for i in items)


def test_a_clean_branch_level_with_its_upstream():
    status = check.parse_status(z(b"# branch.oid 250c95", b"# branch.head main",
                                  b"# branch.upstream origin/main", b"# branch.ab +0 -0"))
    assert status == {"head": "main", "upstream": "origin/main", "ahead": 0, "gone": False,
                      "paths": []}


def test_ahead_with_changed_untracked_renamed_and_conflicted_files():
    status = check.parse_status(z(
        b"# branch.oid 250c95", b"# branch.head main", b"# branch.upstream origin/main",
        b"# branch.ab +2 -1",
        b"1 .M N... 100644 100644 100644 7898 7898 DIARY.md",
        b"2 R. N... 100644 100644 100644 aaaa aaaa R100 new name.md", b"old name.md",
        b"u UU N... 100644 100644 100644 100644 a b c caf\xc3\xa9.txt",
        b"? c d \xc3\xa9",
        b"! ignored/"))
    assert status["ahead"] == 2
    assert status["paths"] == ["DIARY.md", "new name.md", "café.txt", "c d é"]


def test_an_upstream_whose_ref_is_gone():
    status = check.parse_status(z(b"# branch.oid 1", b"# branch.head main",
                                  b"# branch.upstream origin/main"))
    assert status["gone"] is True and status["ahead"] is None


def test_no_upstream_at_all():
    status = check.parse_status(z(b"# branch.oid 1", b"# branch.head main"))
    assert status["upstream"] is None and status["gone"] is False and status["ahead"] is None


# Sizes

def test_sizes_are_said_in_plain_units():
    assert check.size_text(0) == "0 bytes"
    assert check.size_text(999) == "999 bytes"
    assert check.size_text(1500) == "1.5 kB"
    assert check.size_text(3_400_000) == "3.4 MB"
    assert check.size_text(2_000_000_000) == "2.0 GB"


# From findings to the report

def test_nothing_wrong_is_exit_0_with_the_facts_listed():
    lines, code = check.report([check.fact("a fact"), check.fact("another")])
    assert code == 0
    assert lines == ["-- Nothing to tell.", "-- Facts:", "a fact", "another"]


def test_problems_come_first_and_make_exit_1():
    lines, code = check.report([check.fact("a fact"), check.problem("a problem")])
    assert code == 1
    assert lines == ["-- To tell the person you work for (1):", "a problem", "-- Facts:", "a fact"]


def test_a_shorter_diary_is_the_first_line_of_all():
    lines, code = check.report([check.problem("a problem"), check.fact("f"),
                                check.problem("the diary is shorter", first=True)])
    assert lines[:3] == ["-- To tell the person you work for (2):", "the diary is shorter",
                         "a problem"]
    assert code == 1


def test_what_cannot_be_told_is_exit_3_even_beside_a_problem():
    lines, code = check.report([check.problem("a problem"), check.cannot("no lobster.conf")])
    assert code == 3
    assert lines[:3] == ["-- To tell the person you work for (2):", "a problem",
                         "no lobster.conf"]


# git stash list --format=%gd%x00%ci%x00%gs ("Things checked" 11)

def test_each_stash_is_read_as_its_name_its_time_and_gits_words_newest_first():
    out = ("stash@{0}\x002026-11-02 08:15:00 +0000\x00WIP on main: 250c951 Two\n"
           "stash@{1}\x002026-11-01 09:30:00 +0100\x00On main: café, \"q\" $HOME\n").encode()
    assert check.parse_stashes(out) == [
        ("stash@{0}", "2026-11-02 08:15:00 +0000", "WIP on main: 250c951 Two"),
        ("stash@{1}", "2026-11-01 09:30:00 +0100", "On main: café, \"q\" $HOME"),
    ]


def test_no_stash_is_an_empty_list():
    assert check.parse_stashes(b"") == []
    assert check.parse_stashes(b"\n") == []


def test_a_stash_line_without_the_separators_is_kept_whole_as_its_name():
    assert check.parse_stashes(b"stash@{0}: WIP on main\n") == [("stash@{0}: WIP on main", "", "")]
