"""prepare-venv's pure parts: the import line, the export lines, one setting written into a
config's text, the model check and the inside-the-checkout test (PLAN.md "`prepare-venv`")."""
import os
import shlex

import pytest

from lobstertools.prepare import export_lines, import_line, is_inside, model_problems, with_setting

HOSTILE = "/tmp/a b/it's \"q\" $HOME `x` \\ café</script>"


def test_the_import_line_is_built_from_the_names():
    assert import_line(["cairo", "numpy", "PIL.Image"]) == "import cairo, numpy, PIL.Image"


def test_export_lines_with_a_config():
    assert export_lines("TVT", "/v/bin/python", "/c/tvt.conf") == [
        "export TVT_PYTHON=/v/bin/python", "export TVT_CONF=/c/tvt.conf",
        "export PYTHONDONTWRITEBYTECODE=1"]


def test_export_lines_without_a_config():
    assert export_lines("P", "/v/bin/python", None) == [
        "export P_PYTHON=/v/bin/python", "export PYTHONDONTWRITEBYTECODE=1"]


def test_export_lines_quote_what_a_shell_would_split_and_give_it_back_byte_for_byte():
    lines = export_lines("P", HOSTILE + "/bin/python", HOSTILE + "/p.conf")
    assert lines[0] == "export P_PYTHON=" + shlex.quote(HOSTILE + "/bin/python")
    assert shlex.split(lines[0]) == ["export", "P_PYTHON=" + HOSTILE + "/bin/python"]
    assert shlex.split(lines[1]) == ["export", "P_CONF=" + HOSTILE + "/p.conf"]


def test_a_config_that_already_says_it_needs_no_change():
    assert with_setting("A=1\nMODEL=/m\n", "MODEL", "/m") is None


def test_a_quoted_value_that_says_it_needs_no_change():
    assert with_setting("MODEL=\"/m n\"\n", "MODEL", "/m n") is None


def test_a_missing_file_gets_the_one_line():
    assert with_setting(None, "MODEL", "/m") == "MODEL=/m\n"


def test_an_absent_setting_is_added_at_the_end_every_other_line_kept():
    text = "# my settings\nA = 1\n\nB='two words'\n"
    assert with_setting(text, "MODEL", "/m") == text + "MODEL=/m\n"


def test_a_last_line_without_a_newline_is_ended_before_the_setting():
    assert with_setting("A=1", "MODEL", "/m") == "A=1\nMODEL=/m\n"


def test_a_different_value_is_replaced_in_its_place():
    text = "A=1\n  MODEL = /old\nB=2\n# MODEL=/commented\n"
    assert with_setting(text, "MODEL", "/new") == "A=1\nMODEL=/new\nB=2\n# MODEL=/commented\n"


def test_a_similar_key_is_not_taken_for_the_setting():
    assert with_setting("MODEL_X=/x\n", "MODEL", "/m") == "MODEL_X=/x\nMODEL=/m\n"


def test_a_hostile_value_is_written_as_it_is():
    assert with_setting("", "MODEL", HOSTILE) == "MODEL=%s\n" % HOSTILE


def test_a_config_that_is_not_key_value_is_refused():
    with pytest.raises(ValueError) as caught:
        with_setting("A=1\nnot a setting\n", "MODEL", "/m")
    assert str(caught.value) == "line 2 is not KEY=value: 'not a setting'"


def test_a_complete_model_folder_has_no_problems(tmp_path):
    (tmp_path / "model.onnx").write_bytes(b"x")
    (tmp_path / "voices.npz").write_bytes(b"x")
    assert model_problems(str(tmp_path), ["model.onnx", "voices.npz"], "the README") == []


def test_a_missing_model_folder_is_one_message(tmp_path):
    folder = str(tmp_path / "no model")
    assert model_problems(folder, ["model.onnx", "voices.npz"], "the README") == [
        "the model folder %s does not exist; get the model as the README says" % folder]


def test_each_missing_model_file_is_named(tmp_path):
    (tmp_path / "voices.npz").write_bytes(b"x")
    (tmp_path / "model.onnx").mkdir()
    assert model_problems(str(tmp_path), ["model.onnx", "voices.npz", "extra.bin"], "X") == [
        "the model folder %s has no model.onnx; get it as X says" % tmp_path,
        "the model folder %s has no extra.bin; get it as X says" % tmp_path]


def test_a_model_folder_with_no_files_named_only_has_to_exist(tmp_path):
    assert model_problems(str(tmp_path), [], "X") == []


def test_inside_the_checkout_and_the_checkout_itself(tmp_path):
    checkout = tmp_path / "proj"
    checkout.mkdir()
    assert is_inside(str(checkout / "venv"), str(checkout))
    assert is_inside(str(checkout), str(checkout))
    assert is_inside(str(checkout / "a" / ".." / "b"), str(checkout))
    assert not is_inside(str(tmp_path / "proj-venv"), str(checkout))
    assert not is_inside(str(tmp_path / "venv"), str(checkout))


def test_inside_the_checkout_through_a_symbolic_link(tmp_path):
    checkout = tmp_path / "proj"
    checkout.mkdir()
    os.symlink(str(checkout), str(tmp_path / "link"))
    assert is_inside(str(tmp_path / "link" / "venv"), str(checkout))
    assert is_inside(str(checkout / "venv"), str(tmp_path / "link"))
