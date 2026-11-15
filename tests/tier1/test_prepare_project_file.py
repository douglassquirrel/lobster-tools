"""prepare-venv's project file, prepare-venv.conf in the project's checkout (PLAN.md "`prepare-venv`").
KEY=value lines; ENV_PREFIX, REQUIREMENTS and IMPORTS are required, the model keys optional."""
import pytest

from lobstertools.prepare import ProjectError, parse_project

HOME = "/home/someone"
FULL = ("# training-video-tools in the device shell\n"
        "ENV_PREFIX=TRAINING_VIDEO_TOOLS\n"
        "REQUIREMENTS=requirements-linux.txt\n"
        "IMPORTS=cairo numpy  soundfile kokoro_onnx PIL fontTools\n"
        "MODEL_FILES=model.onnx voices.npz\n"
        "MODEL_SETTING=SPEECH_MODEL_DIR\n"
        "MODEL_HELP=the README's \"One-time set-up of the speech model\"\n")


def test_reads_every_key_of_a_full_file():
    project = parse_project(FULL, HOME)
    assert project.prefix == "TRAINING_VIDEO_TOOLS"
    assert project.requirements == "requirements-linux.txt"
    assert project.imports == ["cairo", "numpy", "soundfile", "kokoro_onnx", "PIL", "fontTools"]
    assert project.model_files == ["model.onnx", "voices.npz"]
    assert project.model_setting == "SPEECH_MODEL_DIR"
    assert project.model_help == "the README's \"One-time set-up of the speech model\""


def test_the_model_keys_are_optional_and_the_help_has_a_default():
    project = parse_project("ENV_PREFIX=P\nREQUIREMENTS=r.txt\nIMPORTS=numpy\n", HOME)
    assert (project.model_files, project.model_setting) == ([], None)
    assert project.model_help == "the project's README"


@pytest.mark.parametrize("missing", ["ENV_PREFIX", "REQUIREMENTS", "IMPORTS"])
def test_refuses_a_file_without_a_required_key(missing):
    text = "".join(line + "\n" for line in ("ENV_PREFIX=P", "REQUIREMENTS=r.txt", "IMPORTS=numpy")
                   if not line.startswith(missing))
    with pytest.raises(ProjectError) as caught:
        parse_project(text, HOME)
    assert str(caught.value) == "it has no %s line" % missing


def test_refuses_an_empty_required_value():
    with pytest.raises(ProjectError) as caught:
        parse_project("ENV_PREFIX=P\nREQUIREMENTS=r.txt\nIMPORTS=\n", HOME)
    assert str(caught.value) == "it has no IMPORTS line"


def test_refuses_a_key_it_does_not_know_so_a_misspelling_is_caught():
    with pytest.raises(ProjectError) as caught:
        parse_project("ENV_PREFIX=P\nREQUIREMENTS=r.txt\nIMPORTS=numpy\nMODEL_FILE=m.onnx\n", HOME)
    assert str(caught.value) == ("it has a key prepare-venv does not know: MODEL_FILE (the keys are "
                                 "ENV_PREFIX, REQUIREMENTS, IMPORTS, MODEL_FILES, MODEL_SETTING, "
                                 "MODEL_HELP)")


def test_refuses_a_line_that_is_not_key_value():
    with pytest.raises(ProjectError) as caught:
        parse_project("ENV_PREFIX=P\nnumpy\n", HOME)
    assert str(caught.value) == "line 2 is not KEY=value: 'numpy'"


@pytest.mark.parametrize("name", ["os; import shutil", "numpy()", "1abc", "a..b", "café", "class",
                                  "$(rm)", "a.", "__import__('os')"])
def test_refuses_an_import_that_is_not_a_dotted_module_name(name):
    with pytest.raises(ProjectError) as caught:
        parse_project("ENV_PREFIX=P\nREQUIREMENTS=r.txt\nIMPORTS=numpy %s\n" % name, HOME)
    assert str(caught.value).startswith("IMPORTS holds something that is not a module name: ")


def test_takes_dotted_module_names():
    project = parse_project("ENV_PREFIX=P\nREQUIREMENTS=r.txt\nIMPORTS=a.b_c._d PIL.Image\n", HOME)
    assert project.imports == ["a.b_c._d", "PIL.Image"]


@pytest.mark.parametrize("prefix", ["lower", "1ABC", "A-B", "A B", "A$B"])
def test_refuses_a_prefix_that_is_not_an_upper_case_variable_name(prefix):
    with pytest.raises(ProjectError) as caught:
        parse_project("ENV_PREFIX=%s\nREQUIREMENTS=r.txt\nIMPORTS=numpy\n" % prefix, HOME)
    assert str(caught.value) == ("ENV_PREFIX must be capital letters, figures and _, starting with "
                                 "a letter: %r" % prefix)


@pytest.mark.parametrize("setting", ["1X", "A-B", "A B", "A=B"])
def test_refuses_a_model_setting_that_is_not_a_key(setting):
    with pytest.raises(ProjectError) as caught:
        parse_project("ENV_PREFIX=P\nREQUIREMENTS=r.txt\nIMPORTS=numpy\nMODEL_SETTING=%s\n"
                      % setting, HOME)
    assert str(caught.value) == ("MODEL_SETTING must be letters, figures and _, starting with a "
                                 "letter or _: %r" % setting)


@pytest.mark.parametrize("name", ["sub/model.onnx", "..", ".", "../x"])
def test_refuses_a_model_file_that_is_not_a_plain_file_name(name):
    with pytest.raises(ProjectError) as caught:
        parse_project("ENV_PREFIX=P\nREQUIREMENTS=r.txt\nIMPORTS=numpy\nMODEL_FILES=%s\n" % name,
                      HOME)
    assert str(caught.value) == ("MODEL_FILES must be plain file names in the model folder, "
                                 "not %r" % name)


@pytest.mark.parametrize("path", ["/etc/requirements.txt", "../other/requirements.txt",
                                  "a/../../x.txt", "~/r.txt"])
def test_refuses_requirements_outside_the_checkout(path):
    with pytest.raises(ProjectError) as caught:
        parse_project("ENV_PREFIX=P\nREQUIREMENTS=%s\nIMPORTS=numpy\n" % path, HOME)
    assert str(caught.value) == ("REQUIREMENTS must name a file inside the checkout, relative to "
                                 "it: %r" % path.replace("~", HOME))


def test_takes_requirements_in_a_subfolder():
    project = parse_project("ENV_PREFIX=P\nREQUIREMENTS=linux/req.txt\nIMPORTS=numpy\n", HOME)
    assert project.requirements == "linux/req.txt"
