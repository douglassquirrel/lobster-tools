"""--dry-run runs nothing; an empty list runs nothing and is not a failure."""


def test_dry_run_prints_each_line_it_would_run_and_runs_none(bench):
    code, out, err = bench.run("--dry-run", "a", "b c", "--", "archive-ask", "--day={}")
    assert (code, err) == (0, "")
    assert out == ("would run [1/2] archive-ask --day=a\n"
                   "would run [2/2] archive-ask '--day=b c'\n"
                   "dry run: 2 would run, none run\n")
    assert bench.log() == []


def test_an_empty_list_runs_nothing_and_exits_0(bench):
    listing = bench.tmp / "list.txt"
    listing.write_text("\n  \n", "utf-8")
    code, out, err = bench.run("--from", str(listing), "--", "archive-ask")
    assert (code, out, err) == (0, "no items: nothing run\n", "")
    assert bench.log() == []


def test_an_empty_standard_input_runs_nothing(bench):
    code, out, _ = bench.run("--from", "-", "--", "archive-ask", stdin="")
    assert (code, out) == (0, "no items: nothing run\n")
