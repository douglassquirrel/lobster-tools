"""request answer, request close, and the command started as a program (PLAN.md "`request`")."""
import json
import os
import pathlib
import subprocess
import sys

from request_helpers import call

from lobstertools import request

CHECKOUT = pathlib.Path(__file__).resolve().parents[2]


def sent(world, to, title):
    world.rq("new", "--to", to, "--title", title)
    number = "%02d" % len(world.requests())
    world.fill(number)
    code, out, err = world.rq("send", number, "--json")
    assert code == 0, err
    return json.loads(out)["id"]


def test_answer_replies_to_the_request_found_by_asker_and_number(world, tmp_path):
    world.send("b", "a", "Request 05: From b")
    from_c = world.send("c", "a", "Request 05: From c")
    body = tmp_path / "answer.md"
    body.write_bytes(b"Built: $(not run) `x` </script> caf\xc3\xa9\n")
    code, out, err = world.rq("answer", "c", "5", str(body), "--json")
    assert (code, err) == (0, "")
    result = json.loads(out)
    assert (result["to"], result["in_reply_to"], result["subject"]) == (
        "c", from_c, "Re: Request 05: From c")
    data = (world.root / "c" / "new" / (result["id"] + ".md")).read_bytes()
    assert data.partition(b"\n\n")[2] == body.read_bytes()
    code, out, _ = world.rq("list", "--json")
    states = [(e["from"], e["state"]) for e in json.loads(out)["asked_of"]]
    assert states == [("b", "waiting here"), ("c", "answered")]


def test_answer_takes_the_body_from_standard_input(world):
    asked = world.send("b", "a", "Request 01: x")
    code, out, err = world.rq("answer", "b", "01", "-", stdin="Done.\n")
    assert (code, err) == (0, "")
    assert out.startswith("Replied ")
    assert any(asked in p.read_text("utf-8") for p in (world.root / "b" / "new").iterdir())


def test_answer_dry_run_writes_nothing(world, tmp_path):
    world.send("b", "a", "Request 01: x")
    body = tmp_path / "answer.md"
    body.write_text("Done.\n", "utf-8")
    before = world.files()
    code, out, err = world.rq("answer", "b", "01", str(body), "--dry-run")
    assert (code, err) == (0, "")
    assert out.startswith("Would reply ")
    assert world.files() == before


def test_answer_to_a_request_this_mailbox_was_not_sent_is_refused(world, tmp_path):
    sent(world, "b", "Ours, to b")
    body = tmp_path / "answer.md"
    body.write_text("Done.\n", "utf-8")
    before = world.files()
    code, out, err = world.rq("answer", "b", "01", str(body))
    assert (code, out) == (3, "")
    assert err == "request answer: no request 01 from b in a's mailbox\n"
    assert world.files() == before


def test_answer_to_one_of_two_requests_with_one_number_is_refused(world, tmp_path):
    world.send("b", "a", "Request 05: Once")
    world.send("b", "a", "Request 05: Twice")
    code, _, err = world.rq("answer", "b", "05", "-", stdin="x\n")
    assert code == 3
    assert err.endswith("; answer the one meant with lobster-mail reply ID\n")


def test_close_marks_every_reply_to_the_request_done(world):
    id_ = sent(world, "b", "Asked")
    first = world.reply("b", id_, "One.\n")
    world.move("ack", "a", first)
    second = world.reply("b", id_, "Two.\n")
    before = world.files()
    code, out, err = world.rq("close", "1")
    assert (code, err) == (0, "")
    assert out == "Done %s: open/ -> done/\nDone %s: new/ -> done/\n" % (first, second)
    after = world.files()
    assert sorted(after.values()) == sorted(before.values())
    assert {k for k in after if k.startswith("a/done/")} == {
        "a/done/%s.md" % first, "a/done/%s.md" % second}
    code, out, _ = world.rq("list", "--json")
    assert json.loads(out)["asked"][0]["state"] == "closed"


def test_close_dry_run_moves_nothing(world):
    id_ = sent(world, "b", "Asked")
    reply = world.reply("b", id_)
    before = world.files()
    code, out, err = world.rq("close", "01", "--dry-run")
    assert (code, err) == (0, "")
    assert out == "Would move %s: new/ -> done/\n" % reply
    assert world.files() == before


def test_close_of_a_request_with_no_reply_is_refused(world):
    sent(world, "b", "Asked")
    code, out, err = world.rq("close", "01")
    assert (code, out) == (3, "")
    assert err == "request close: request 01 has no reply yet; nothing to close\n"


def test_close_of_a_request_already_closed_is_refused(world):
    id_ = sent(world, "b", "Asked")
    world.move("done", "a", world.reply("b", id_))
    code, _, err = world.rq("close", "01")
    assert code == 3
    assert err == "request close: every reply to request 01 is in done/ already\n"


def test_close_of_a_request_this_mailbox_never_made_is_refused(world):
    code, _, err = world.rq("close", "04")
    assert code == 3
    assert err == "request close: a has no request 04: none sent, no file\n"


def test_no_verb_is_a_usage_error_naming_the_verbs(world):
    code, _, err = call(request, [])
    assert code == 2
    assert err.endswith("request: a verb is needed: new, send, list, show, answer, close\n")


def run_program(*argv, cwd):
    env = dict(os.environ, LOBSTER_MAIL_NOW="2026-10-10T10:00:00+01:00")
    return subprocess.run([sys.executable, str(CHECKOUT / "request")] + list(argv), cwd=cwd, check=False,
                          env=env, capture_output=True, text=True)


def test_help_runs_as_a_program_and_names_every_verb(tmp_path):
    done = run_program("--help", cwd=tmp_path)
    assert done.returncode == 0
    for verb in ("new", "send", "list", "show", "answer", "close"):
        assert verb in done.stdout


def test_list_runs_as_a_program_from_the_project_folder(world):
    world.send("b", "a", "Request 03: Theirs")
    done = run_program("list", "--root", str(world.root), cwd=world.project)
    assert (done.returncode, done.stderr) == (0, "")
    assert done.stdout.startswith("Asked of a (1):\n  03  from b ")
