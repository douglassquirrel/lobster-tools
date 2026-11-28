"""each stops at the first failure unless --go-on, and says how far it got."""


def test_stops_at_the_first_failure_and_says_what_was_not_run(bench):
    bench.exits(2, 1)
    code, out, _ = bench.run("a", "b", "c", "d", "--", "archive-ask")
    assert code == 1
    assert bench.log() == ["ran 1", "ran 2"]
    assert out.splitlines()[-3:] == [
        "out 2", "exit 1",
        "stopped at the first failure: 2 of 4 ran (1 succeeded, 1 failed), 2 not run"]


def test_go_on_runs_every_item_and_exits_1_if_any_failed(bench):
    bench.exits(2, 1)
    bench.exits(3, 7)
    code, out, _ = bench.run("--go-on", "a", "b", "c", "d", "--", "archive-ask")
    assert code == 1
    assert bench.log() == ["ran 1", "ran 2", "ran 3", "ran 4"]
    assert [line for line in out.splitlines() if line.startswith("exit")] == [
        "exit 0", "exit 1", "exit 7", "exit 0"]
    assert out.splitlines()[-1] == "4 ran: 2 succeeded, 2 failed"


def test_go_on_with_no_failure_exits_0(bench):
    code, out, _ = bench.run("--go-on", "a", "b", "--", "archive-ask")
    assert (code, out.splitlines()[-1]) == (0, "2 ran: 2 succeeded, 0 failed")


def test_a_command_ended_by_a_signal_of_its_own_is_a_failure(bench):
    (bench.stub / "kill-1").write_text("")
    code, out, _ = bench.run("a", "b", "--", "archive-ask")
    assert code == 1
    assert out.splitlines() == [
        "[1/2] archive-ask a", "out 1", "ended by signal 9",
        "stopped at the first failure: 1 of 2 ran (0 succeeded, 1 failed), 1 not run"]


def test_a_command_that_cannot_be_started_is_a_failure_and_says_why(bench):
    import os

    from each_helpers import STUB
    os.symlink(str(STUB.parent / "eachbroken"), str(bench.bin / "broken-tool"))
    code, out, _ = bench.run("a", "b", "--", "broken-tool")
    assert code == 1
    assert out.splitlines() == [
        "[1/2] broken-tool a", "could not start: Exec format error",
        "stopped at the first failure: 1 of 2 ran (0 succeeded, 1 failed), 1 not run"]


def test_a_stop_while_an_item_runs_starts_no_more_and_puts_the_handlers_back(bench, monkeypatch):
    import signal

    from lobstertools import each
    ran = []

    def fake_run_item(argv, relay):
        ran.append(argv)
        signal.raise_signal(signal.SIGTERM)
        signal.raise_signal(signal.SIGINT)  # a second stop: the first is the one reported
        return 0

    monkeypatch.setattr(each, "run_item", fake_run_item)
    before = signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT)
    code, out, _ = bench.run("a", "b", "c", "--", "archive-ask")
    assert (code, ran) == (143, [["archive-ask", "a"]])
    assert out.splitlines() == [
        "[1/3] archive-ask a", "exit 0",
        "stopped by signal 15: 1 of 3 ran (1 succeeded, 0 failed), 2 not run"]
    assert (signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT)) == before
