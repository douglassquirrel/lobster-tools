"""script-guard as a PreToolUse hook: JSON on standard input, exit 2 with a plain message to
refuse, exit 0 and nothing on standard error to allow, and every refusal logged ("Settled" 84)."""
import json

GANGLION_MESSAGE = (
    "script-guard refused this command: sleep. A ganglion writes no scripts and types no loops "
    "(its rule 11).\n"
    "Use a tool: each (one command over a list), job or wait-for-file (to wait), measure in "
    "file-tools (to count or size files); a job no tool does yet is a request to a claw.\n")

CLAW_MESSAGE = (
    "script-guard refused this command: an inline program (python3 -c). A claw keeps every "
    "script it runs (its rule 20).\n"
    "Write the program as a file in kept-scripts/, with a header and a row in its README, and "
    "run that file.\n")


def test_a_ganglion_refuses_with_exit_2_and_says_why_and_what_to_use(desk):
    code, out, err = desk.hook("sleep 60", desk.ganglion())
    assert (code, out, err) == (2, "", GANGLION_MESSAGE)


def test_a_ganglion_allows_with_exit_0_and_nothing_on_either_stream(desk):
    assert desk.hook("git status && lobster-mail check --as pond", desk.ganglion()) == (0, "", "")
    assert desk.log("pond") is None


def test_a_claw_refuses_an_inline_program_and_allows_a_loop(desk):
    claw = desk.claw()
    assert desk.hook("python3 -c 'print(1)'", claw) == (2, "", CLAW_MESSAGE)
    assert desk.hook("for f in a b; do ls $f; done", claw) == (0, "", "")


def test_every_refusal_is_logged_as_one_json_line_under_the_mail_root(desk):
    pond = desk.ganglion()
    desk.hook("sleep 60", pond)
    desk.hook("python3 x.py", pond, agent_id="a-7", agent_type="general-purpose")
    assert desk.log("pond") == [
        {"time": "2026-11-28T08:30:00Z", "project": "pond", "kind": "non-code",
         "session": "s-1", "reason": "sleep", "command": "sleep 60"},
        {"time": "2026-11-28T08:30:00Z", "project": "pond", "kind": "non-code",
         "session": "s-1", "agent": "a-7", "agent_type": "general-purpose",
         "reason": "an interpreter (python3)", "command": "python3 x.py"}]


def test_the_log_keeps_the_first_300_characters_of_the_command(desk):
    command = "sleep 1 # " + "x" * 400
    desk.hook(command, desk.ganglion())
    assert desk.log("pond")[0]["command"] == command[:300]


def test_a_project_with_no_self_is_logged_under_its_folder_name(desk):
    desk.hook("sleep 1", desk.project("marsh", "KIND=non-code\n"))
    assert desk.log("marsh")[0]["project"] == "marsh"


def test_with_no_mail_root_the_refusal_stands_and_says_it_was_not_logged(desk):
    desk.monkeypatch.delenv("LOBSTER_MAIL_ROOT")
    code, _, err = desk.hook("sleep 60", desk.ganglion())
    assert code == 2
    assert err == GANGLION_MESSAGE + (
        "script-guard: this refusal is not logged: no mail root (LOBSTER_MAIL_ROOT, or MAIL_ROOT "
        "in ~/.lobster-tools.conf)\n")


def test_the_mail_root_can_come_from_the_config_file(desk):
    desk.monkeypatch.delenv("LOBSTER_MAIL_ROOT")
    (desk.home / ".lobster-tools.conf").write_text("MAIL_ROOT=%s\n" % desk.root, "utf-8")
    assert desk.hook("sleep 60", desk.ganglion())[0] == 2
    assert desk.log("pond")[0]["reason"] == "sleep"


def test_a_log_that_cannot_be_written_leaves_the_refusal_standing(desk):
    (desk.root / ".script-guard").write_text("a file where the folder should be", "utf-8")
    code, _, err = desk.hook("sleep 60", desk.ganglion())
    assert code == 2
    assert err.startswith(GANGLION_MESSAGE + "script-guard: this refusal is not logged: ")
    assert err.count("\n") == 3


def test_a_feeler_a_conductor_no_kind_and_no_lobster_conf_allow_everything(desk):
    for name, conf in (("feel", "KIND=feeler\n"), ("cond", "KIND=conductor\n"),
                       ("nokind", "SELF=nokind\n"), ("bare", None)):
        project = desk.project(name, conf)
        for command in ("sleep 60", "python3 -c 1", "for x in y; do :; done", "echo 'unclosed"):
            assert desk.hook(command, project) == (0, "", ""), (name, command)


def test_the_project_is_claude_project_dir_and_else_the_json_cwd(desk):
    pond, bare = desk.ganglion(), desk.project("bare", None)
    desk.monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(pond))
    data = {"tool_name": "Bash", "tool_input": {"command": "sleep 1"}, "cwd": str(bare)}
    assert desk.call(stdin=json.dumps(data))[0] == 2
    desk.monkeypatch.delenv("CLAUDE_PROJECT_DIR")
    assert desk.call(stdin=json.dumps(data))[0] == 0
    data["cwd"] = str(pond)
    assert desk.call(stdin=json.dumps(data))[0] == 2


def test_another_tool_an_empty_command_and_json_of_another_shape_are_allowed_quietly(desk):
    pond = desk.ganglion()
    desk.monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(pond))
    for data in ({"tool_name": "Read", "tool_input": {"command": "sleep 1"}},
                 {"tool_name": "Bash", "tool_input": {"command": "   "}},
                 {"tool_name": "Bash", "tool_input": {"command": 7}},
                 {"tool_name": "Bash", "tool_input": "sleep 1"},
                 {"tool_name": "Bash"}, [], "sleep 1", None):
        assert desk.call(stdin=json.dumps(data)) == (0, "", ""), data


def test_input_that_is_not_json_is_allowed_with_one_line(desk):
    assert desk.call(stdin="sleep 1") == (
        0, "", "script-guard: its input is not the hook's JSON; allowed\n")


def test_a_command_it_cannot_read_is_allowed_with_one_line(desk):
    assert desk.hook("echo 'unclosed; sleep 5", desk.ganglion()) == (
        0, "", "script-guard: cannot read this command (a ' is not closed); allowed\n")


def test_a_fault_of_its_own_allows_the_command_with_one_line(desk, monkeypatch):
    pond = desk.ganglion()
    (pond / "lobster.conf").write_text("not a setting\n", "utf-8")
    code, out, err = desk.hook("sleep 60", pond)
    assert (code, out) == (0, "")
    assert err.startswith("script-guard: a fault of its own (") and err.endswith("); allowed\n")
    assert err.count("\n") == 1

    def broken(*args, **kwargs):
        raise RuntimeError("invented")

    monkeypatch.setattr("lobstertools.guard.judge", broken)
    assert desk.hook("sleep 60", desk.claw()) == (
        0, "", "script-guard: a fault of its own (RuntimeError: invented); allowed\n")
