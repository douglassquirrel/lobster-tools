import pytest

from lobstertools import config


def test_reads_key_value_lines_with_comments_quotes_blank_lines_and_home():
    text = '# the mail root\n\nMAIL_ROOT = "~/projects/mail"\nOTHER=\'plain\'  \n'
    assert config.parse_conf(text, home="/Users/s") == {
        "MAIL_ROOT": "/Users/s/projects/mail",
        "OTHER": "plain",
    }


def test_a_line_without_an_equals_sign_is_reported_with_its_number():
    with pytest.raises(config.ConfigError) as caught:
        config.parse_conf("MAIL_ROOT=~/m\nthis is not a setting\n", home="/h")
    assert "line 2" in str(caught.value)


def test_root_comes_from_the_flag_then_the_variable_then_the_file():
    assert config.resolve_root("/flag", "/env", {"MAIL_ROOT": "/file"}) == "/flag"
    assert config.resolve_root(None, "/env", {"MAIL_ROOT": "/file"}) == "/env"
    assert config.resolve_root(None, None, {"MAIL_ROOT": "/file"}) == "/file"
    assert config.resolve_root(None, "", {}) is None
