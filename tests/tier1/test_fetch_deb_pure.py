"""fetch-deb's pure parts: the names it is given, finding the program and the library folders in
what was unpacked, the wrapper's text and the export line (PLAN.md "Request 24")."""
import os
import shlex
import subprocess

import pytest

from lobstertools.fetchdeb import (
    Refused,
    check_names,
    export_line,
    find_program,
    library_dirs,
    wrapper_text,
)


def test_good_names_pass():
    check_names("rsvg-convert", "RSVG_CONVERT", ["librsvg2-bin", "librsvg2-2", "libc++1", "a.b"])


@pytest.mark.parametrize("program", ["", "bin/rsvg-convert", "..", ".", "a b", "$(x)"])
def test_a_program_that_is_not_a_plain_name_is_refused(program):
    with pytest.raises(Refused) as caught:
        check_names(program, "V", ["p"])
    assert str(caught.value) == "--program must be a plain program name, not %r" % program


@pytest.mark.parametrize("var", ["", "1A", "A-B", "A B", "café"])
def test_a_variable_that_is_not_a_name_is_refused(var):
    with pytest.raises(Refused) as caught:
        check_names("p", var, ["p"])
    assert str(caught.value) == ("--var must be letters, figures and _, starting with a letter or "
                                 "_: %r" % var)


@pytest.mark.parametrize("package", ["-o", "Lib", "a", "lib rsvg", "lib;rm", "lib/x", "x=1.0",
                                     "../x"])
def test_a_package_that_is_not_a_debian_package_name_is_refused(package):
    with pytest.raises(Refused) as caught:
        check_names("p", "V", ["ok-package", package])
    assert str(caught.value) == ("not a Debian package name (small letters, figures, + - and ., "
                                 "starting with a letter or figure): %r" % package)


def test_no_packages_is_refused():
    with pytest.raises(Refused) as caught:
        check_names("p", "V", [])
    assert str(caught.value) == "name at least one package"


def make(root, *paths):
    for path in paths:
        full = os.path.join(str(root), path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as handle:
            handle.write("x")


def test_the_program_is_found_in_usr_bin_first(tmp_path):
    make(tmp_path, "usr/bin/tool", "bin/tool")
    assert find_program(str(tmp_path), "tool") == str(tmp_path / "usr" / "bin" / "tool")


def test_the_program_is_found_in_the_other_bin_folders(tmp_path):
    make(tmp_path, "usr/sbin/tool")
    assert find_program(str(tmp_path), "tool") == str(tmp_path / "usr" / "sbin" / "tool")


def test_a_missing_program_is_none(tmp_path):
    make(tmp_path, "usr/bin/other", "usr/share/tool")
    assert find_program(str(tmp_path), "tool") is None


def test_library_folders_are_those_holding_shared_objects(tmp_path):
    make(tmp_path, "usr/lib/aarch64-linux-gnu/librsvg-2.so.2.48.0",
         "usr/lib/aarch64-linux-gnu/gdk-pixbuf-2.0/2.10.0/loaders/libpixbufloader-svg.so",
         "lib/x86_64-linux-gnu/libz.so.1", "usr/share/doc/librsvg2-2/copyright", "usr/bin/tool")
    assert library_dirs(str(tmp_path)) == [
        str(tmp_path / "lib" / "x86_64-linux-gnu"),
        str(tmp_path / "usr" / "lib" / "aarch64-linux-gnu"),
        str(tmp_path / "usr" / "lib" / "aarch64-linux-gnu" / "gdk-pixbuf-2.0" / "2.10.0" / "loaders")]


def test_no_shared_objects_no_library_folders(tmp_path):
    make(tmp_path, "usr/bin/tool")
    assert library_dirs(str(tmp_path)) == []


def test_the_wrapper_sets_the_libraries_and_runs_the_program():
    text = wrapper_text("/w/rsvg/root/usr/bin/rsvg-convert", ["/w/rsvg/root/usr/lib/a"],
                        ["librsvg2-bin", "librsvg2-2"])
    assert text == (
        "#!/bin/sh\n"
        "# Made by lobster-tools' fetch-deb from: librsvg2-bin librsvg2-2\n"
        "LD_LIBRARY_PATH=/w/rsvg/root/usr/lib/a${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}\n"
        "export LD_LIBRARY_PATH\n"
        "exec /w/rsvg/root/usr/bin/rsvg-convert \"$@\"\n")


def test_a_wrapper_with_no_libraries_only_runs_the_program():
    assert wrapper_text("/w/root/usr/bin/t", [], ["t"]) == (
        "#!/bin/sh\n# Made by lobster-tools' fetch-deb from: t\nexec /w/root/usr/bin/t \"$@\"\n")


def test_the_wrapper_quotes_hostile_paths_so_sh_runs_them_as_they_are(tmp_path):
    odd = tmp_path / "it's \"q\" $HOME `x` \\ café"
    program = odd / "root" / "usr" / "bin" / "tool"
    lib = odd / "root" / "usr" / "lib"
    os.makedirs(str(program.parent))
    os.makedirs(str(lib))
    program.write_text('#!/bin/sh\nprintf "%s\\n" "$LD_LIBRARY_PATH" "$@"\n', encoding="utf-8")
    program.chmod(0o755)
    wrapper = tmp_path / "wrapper"
    wrapper.write_text(wrapper_text(str(program), [str(lib)], ["t"]), encoding="utf-8")
    wrapper.chmod(0o755)
    env = {"PATH": "/usr/bin:/bin", "LD_LIBRARY_PATH": "/before"}
    done = subprocess.run([str(wrapper), "a b", "$c"], capture_output=True, text=True, env=env,
                          check=False)
    assert done.stdout.splitlines() == [str(lib) + ":/before", "a b", "$c"]


def test_the_export_line_is_quoted():
    assert export_line("RSVG_CONVERT", "/w/a b/bin/rsvg-convert") == (
        "export RSVG_CONVERT=" + shlex.quote("/w/a b/bin/rsvg-convert"))
