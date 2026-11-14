"""`handover --diary FILE` records the diary's length as a header the tool writes, for
session-check to read back exactly; and `start` says to run session-check (Request 16; PLAN.md
"Settled" 43)."""
HID = "2026-10-10-0900-b-handover-2026-10-10-09-00z"


def test_handover_with_diary_writes_its_line_count_as_a_header_in_both_copies(run, root, two,
                                                                               tmp_path):
    diary = tmp_path / "my diary.md"
    diary.write_bytes("café\n".encode() * 2383)
    code, _out, err = run("handover", "--root", str(root), "--as", "b", "--diary", str(diary), "-",
                         stdin="Stopped at 4.\n")
    assert (code, err) == (0, "")
    for box in ("new", "sent"):
        data = (root / "b" / box / (HID + ".md")).read_bytes()
        head = data.partition(b"\n\n")[0].decode("utf-8").splitlines()
        assert head[5:] == ["Diary-Lines: 2383", head[-1]]
        assert head[-1].startswith("Body-SHA-256: ")
        assert data.endswith(b"\n\nStopped at 4.\n")


def test_handover_without_diary_writes_no_such_header(run, root, two):
    run("handover", "--root", str(root), "--as", "b", "-", stdin="Stopped.\n")
    assert b"Diary-Lines" not in (root / "b" / "new" / (HID + ".md")).read_bytes()


def test_handover_dry_run_shows_the_header_and_writes_nothing(run, root, two, tmp_path):
    diary = tmp_path / "DIARY.md"
    diary.write_bytes(b"a\nb\n")
    code, out, _ = run("handover", "--root", str(root), "--as", "b", "--diary", str(diary),
                       "--dry-run", "-", stdin="x\n")
    assert code == 0
    assert "\nDiary-Lines: 2\n" in out
    assert list((root / "b" / "new").iterdir()) == []


def test_handover_with_a_diary_that_is_not_there_is_refused_and_sends_nothing(run, root, two,
                                                                              tmp_path):
    code, out, err = run("handover", "--root", str(root), "--as", "b", "--diary",
                         str(tmp_path / "nope.md"), "-", stdin="x\n")
    assert (code, out) == (2, "")
    assert err == ("lobster-mail handover: --diary %s: no such file, so its length cannot be "
                   "recorded; nothing was sent\n" % (tmp_path / "nope.md"))
    assert list((root / "b" / "new").iterdir()) == []


def test_start_says_to_run_session_check(run, root, two):
    code, out, _ = run("start", "--root", str(root), "--as", "b")
    assert code == 0
    assert ("\n1. Read the project's guidance as usual; the handover above says where the last "
            "session stopped.\n   Then, from the project's folder, run session-check (it sits "
            "beside lobster-mail) and\n   tell the person you work for what it says:\n"
            "   session-check start --session NAME\n2. ") in out
