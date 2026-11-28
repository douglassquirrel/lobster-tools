"""each runs the command once for each item, in order, never through a shell."""

HOSTILE = ["two words", "$(touch pwned) `x` ; | & > out", "\\ \"q\" 'q'", "caf\u00e9 \u65e5\u672c",
           "--looks-like-a-flag"]



def test_each_item_reaches_the_command_as_one_unchanged_argument(bench):
    code, out, err = bench.run("a", "b c", "--", "archive-ask", "--day={}", "--quiet")
    assert (code, err) == (0, "err 1\nerr 2\n")
    assert out == ("[1/2] archive-ask --day=a --quiet\nout 1\nexit 0\n"
                   "[2/2] archive-ask '--day=b c' --quiet\nout 2\nexit 0\n"
                   "2 ran: 2 succeeded, 0 failed\n")
    assert bench.argv(1) == [b"--day=a", b"--quiet"]
    assert bench.argv(2) == [b"--day=b c", b"--quiet"]
    assert bench.log() == ["ran 1", "ran 2"]


def test_hostile_items_are_passed_byte_for_byte_and_nothing_is_run_by_a_shell(bench):
    listing = bench.tmp / "list.txt"
    listing.write_text("\n".join(HOSTILE) + "\n", "utf-8")
    code, _, err = bench.run("--from", str(listing), "--", "archive-ask")
    assert code == 0, err
    assert [bench.argv(n) for n in range(1, 6)] == [[item.encode("utf-8")] for item in HOSTILE]
    assert not (bench.tmp / "pwned").exists() and not (bench.tmp / "out").exists()


def test_the_command_reads_nothing_on_standard_input(bench):
    code, _, err = bench.run("--from", "-", "--", "archive-ask", stdin="a\nb\n")
    assert code == 0, err
    assert (bench.stdin(1), bench.stdin(2)) == (b"", b"")
