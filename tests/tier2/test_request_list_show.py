"""request list and request show: the register, worked out from this mailbox and the request
files each time, and one request with its replies (PLAN.md "`request`", "Settled" 56, 60, 62)."""
import json

DAY1, DAY4 = "2026-10-10T10:00:00+01:00", "2026-10-13T12:00:00+01:00"


def listing(world, *more):
    code, out, err = world.rq("list", "--json", *more)
    assert (code, err) == (0, ""), err
    return json.loads(out)


def draft(world, to, title, need="A need.\n"):
    world.rq("new", "--to", to, "--title", title)
    number = len(world.requests())
    world.fill("%02d" % number, need)
    return "%02d" % number


def sent(world, to, title):
    number = draft(world, to, title)
    code, _, err = world.rq("send", number)
    assert code == 0, err
    return next(e["id"] for e in listing(world)["asked"] if e["number"] == int(number))


def test_a_mailbox_with_no_requests_says_so_and_exits_0(world):
    code, out, err = world.rq("list")
    assert (code, out, err) == (0, "No requests for or from a\n", "")
    assert listing(world) == {"mailbox": "a", "asked": [], "asked_of": [], "not_counted": []}


def test_each_request_this_mailbox_asked_has_its_state(world):
    draft(world, "b", "Drafted")
    id_sent = sent(world, "b", "Sent")
    id_open = sent(world, "c", "Answered open")
    id_new = sent(world, "b", "Answered new")
    id_closed = sent(world, "c", "Closed")
    world.move("ack", "c", id_open)
    reply_open = world.reply("c", id_open)
    world.move("ack", "a", reply_open)
    world.reply("b", id_new)
    reply_closed = world.reply("c", id_closed)
    world.move("done", "a", reply_closed)
    world.at(DAY4)
    states = [(e["number"], e["to"], e["title"], e["state"], e["days"])
              for e in listing(world)["asked"]]
    assert states == [(1, "b", "Drafted", "drafted", None), (2, "b", "Sent", "sent", 3),
                      (3, "c", "Answered open", "answered", 3),
                      (4, "b", "Answered new", "answered", 3), (5, "c", "Closed", "closed", None)]
    assert listing(world)["asked"][1]["id"] == id_sent


def test_the_lines_say_what_the_json_says(world):
    draft(world, "b", "Drafted")
    id_ = sent(world, "c", "Sent one")
    asked = world.send("b", "a", "Request 05: Theirs")
    world.at(DAY4)
    code, out, err = world.rq("list")
    assert (code, err) == (0, "")
    row = "  %s  %-16s  %-10s  %-12s  %-7s  %s\n"
    assert out == (
        "Asked by a (2):\n"
        + row % ("01", "to b", "-", "drafted", "-", "Drafted")
        + row % ("02", "to c", "2026-10-10", "sent", "3 days", "Sent one")
        + "Asked of a (1):\n"
        + row % ("05", "from b", "2026-10-10", "waiting here", "3 days", "Theirs"))
    data = listing(world)
    assert data["asked"][1] == {
        "number": 2, "to": "c", "title": "Sent one", "state": "sent", "id": id_,
        "date": "2026-10-10T09:00:00Z", "days": 3,
        "file": str(world.project / "requests" / "request-02-sent-one.md"), "replies": []}
    assert data["asked_of"] == [{
        "number": 5, "from": "b", "title": "Theirs", "state": "waiting here", "id": asked,
        "date": "2026-10-10T09:00:00Z", "box": "new",
        "days": 3, "replies": []}]


def test_each_request_asked_of_this_mailbox_has_its_state(world):
    waiting = world.send("b", "a", "Request 01: Waiting")
    claimed = world.send("b", "a", "Request 02: Claimed")
    answered = world.send("c", "a", "Request 02: Answered")
    done = world.send("c", "a", "Request 03: Done")
    world.move("ack", "a", claimed)
    world.move("ack", "a", answered)
    reply = world.reply("a", answered)
    world.move("done", "a", done)
    data = listing(world)["asked_of"]
    assert [(e["from"], e["number"], e["state"]) for e in data] == [
        ("b", 1, "waiting here"), ("b", 2, "claimed"), ("c", 2, "answered"), ("c", 3, "done here")]
    assert data[2]["replies"] == [{"id": reply, "from": "a", "date": "2026-10-10T09:00:00Z",
                                   "box": "sent"}]
    assert data[0]["id"] == waiting
    assert data[3]["days"] is None


def test_a_request_with_two_replies_is_closed_only_when_both_are_done(world):
    id_ = sent(world, "b", "Two answers")
    first = world.reply("b", id_, "First.\n")
    world.at("2026-10-10T10:05:00+01:00")
    second = world.reply("b", id_, "Second.\n")
    world.move("done", "a", first)
    [entry] = listing(world)["asked"]
    assert entry["state"] == "answered"
    assert [r["id"] for r in entry["replies"]] == [first, second]
    world.move("done", "a", second)
    assert listing(world)["asked"][0]["state"] == "closed"


def test_a_reply_to_a_reply_belongs_to_the_request(world):
    id_ = sent(world, "b", "Asked")
    answer = world.reply("b", id_)
    world.move("done", "a", answer)
    question = world.reply("a", answer, "A question back.\n")
    again = world.reply("b", question, "The answer to that.\n")
    [entry] = listing(world)["asked"]
    assert entry["state"] == "answered"
    assert [r["id"] for r in entry["replies"]] == [answer, again]


def test_messages_that_are_not_request_n_colon_title_are_named_apart_and_guessed_nothing(world):
    ids = [world.send("a", "b", "Request: an unnumbered one"),
           world.send("a", "b", "Request 18 follow-up: more"),
           world.send("b", "a", "Update on Request 4: news"),
           world.send("b", "a", "Note on Requests 1 to 3: x")]
    world.send("b", "a", "Notice: the rules changed")
    unnumbered_reply = world.reply("b", ids[0])
    data = listing(world)
    assert (data["asked"], data["asked_of"]) == ([], [])
    assert sorted(e["id"] for e in data["not_counted"]) == sorted(ids + [unnumbered_reply])
    code, out, _ = world.rq("list")
    assert code == 0
    assert out.startswith("Not counted, named as requests but not \"Request N: TITLE\" (5):\n")
    assert "  %s  sent/  Request: an unnumbered one\n" % ids[0] in out


def test_open_leaves_out_what_is_closed_and_what_is_not_counted(world):
    id_ = sent(world, "b", "Closed")
    world.move("done", "a", world.reply("b", id_))
    sent(world, "b", "Open")
    done = world.send("b", "a", "Request 01: Done")
    world.move("done", "a", done)
    world.send("b", "a", "Request 02: Waiting")
    world.send("b", "a", "Request: unnumbered")
    data = listing(world, "--open")
    assert [e["title"] for e in data["asked"]] == ["Open"]
    assert [e["title"] for e in data["asked_of"]] == ["Waiting"]
    assert data["not_counted"] == []


def test_list_moves_and_writes_nothing(world):
    id_ = sent(world, "b", "One")
    world.reply("b", id_)
    world.send("b", "a", "Request 01: Theirs")
    before, kept = world.files(), world.requests()
    world.rq("list")
    world.rq("list", "--json")
    assert (world.files(), world.requests()) == (before, kept)


def test_show_prints_this_mailboxs_request_its_ids_its_replies_and_its_state(world):
    id_ = sent(world, "b", "Speaker letters")
    reply = world.reply("b", id_)
    code, out, err = world.rq("show", "1")
    assert (code, err) == (0, "")
    path = world.project / "requests" / "request-01-speaker-letters.md"
    assert out == (
        "Request 01: Speaker letters\n"
        "  to b; sent 2026-10-10T09:00:00Z as %s\n"
        "  state: answered\n"
        "  reply from b, 2026-10-10T09:00:00Z, %s (new/)\n"
        "  file: %s\n\n%s" % (id_, reply, path, path.read_text("utf-8")))


def test_show_of_a_draft_prints_the_file(world):
    draft(world, "b", "Not yet")
    code, out, _ = world.rq("show", "01")
    assert code == 0
    assert out.startswith("Request 01: Not yet\n  to b; drafted, not sent\n  state: drafted\n")


def test_show_says_when_the_kept_file_differs_from_what_was_sent(world):
    sent(world, "b", "Changed")
    path = world.project / "requests" / "request-01-changed.md"
    path.write_text(path.read_text("utf-8") + "\nAdded after.\n", "utf-8")
    code, out, _ = world.rq("show", "1")
    assert code == 0
    assert ("  the file differs from what was sent (its SHA-256 is not the sent copy's "
            "Body-SHA-256)\n") in out
    assert not out.endswith("Added after.\n")


def test_show_project_nn_finds_the_right_one_of_two_projects_number_05(world):
    from_b = world.send("b", "a", "Request 05: From b")
    from_c = world.send("c", "a", "Request 05: From c")
    sent(world, "b", "Ours")
    code, out, err = world.rq("show", "c", "05")
    assert (code, err) == (0, "")
    assert out == (
        "Request 05 from c: From c\n"
        "  received 2026-10-10T09:00:00Z as %s (new/)\n"
        "  state: waiting here\n"
        "  for PLAN.md: (Request 05 from c, message `%s`, 10 October 2026)\n\n"
        "A body.\n" % (from_c, from_c))
    code, out, _ = world.rq("show", "b", "5")
    assert out.startswith("Request 05 from b: From b\n  received 2026-10-10T09:00:00Z as %s" % from_b)
    code, out, err = world.rq("show", "05")
    assert (code, out, err) == (3, "", "request show: a has no request 05: none sent, no file\n")
    code, out, _ = world.rq("show", "01")
    assert out.startswith("Request 01: Ours\n")


def test_show_json_has_the_fields_and_the_body(world):
    asked = world.send("b", "a", "Request 05: From b")
    code, out, _ = world.rq("show", "b", "05", "--json")
    assert code == 0
    assert json.loads(out) == {
        "number": 5, "from": "b", "title": "From b", "state": "waiting here", "id": asked,
        "date": "2026-10-10T09:00:00Z", "box": "new", "days": 0, "replies": [],
        "plan_line": "(Request 05 from b, message `%s`, 10 October 2026)" % asked,
        "body": "A body.\n"}


def test_show_of_a_request_that_does_not_exist_is_refused(world):
    code, out, err = world.rq("show", "07")
    assert (code, out) == (3, "")
    assert err == "request show: a has no request 07: none sent, no file\n"
    code, out, err = world.rq("show", "b", "07")
    assert (code, out) == (3, "")
    assert err == "request show: no request 07 from b in a's mailbox\n"


def test_show_of_two_requests_with_one_number_from_one_project_names_both(world):
    first = world.send("b", "a", "Request 05: Once")
    second = world.send("b", "a", "Request 05: Twice")
    code, out, err = world.rq("show", "b", "05")
    assert (code, out) == (3, "")
    assert err == ("request show: two requests 05 from b: %s, %s; read each with lobster-mail "
                   "read ID\n" % (first, second))


def test_show_takes_one_or_two_arguments(world):
    code, _, err = world.rq("show", "b", "05", "x")
    assert code == 2
    assert "request show: give NN for this project's own request, or PROJECT NN" in err
