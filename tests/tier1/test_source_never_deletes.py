"""CLAUDE.md non-negotiable 1: the package never deletes and never runs anything. Pinned by reading
the source: a delete or a subprocess named anywhere in it is a failure, before any test runs it."""
import pathlib
import re

PACKAGE = pathlib.Path(__file__).resolve().parents[2]
SOURCES = sorted((PACKAGE / "lobstertools").glob("*.py")) + [PACKAGE / "lobster-mail"]
FORBIDDEN = re.compile(r"os\.remove\b|os\.unlink\b|shutil\.rmtree\b|\.unlink\(|\brmdir\b|\bsubprocess\b")


def test_the_source_names_no_delete_and_no_subprocess():
    assert len(SOURCES) >= 4, SOURCES
    found = []
    for path in SOURCES:
        for number, text in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if FORBIDDEN.search(text):
                found.append("%s:%d: %s" % (path.name, number, text.strip()))
    assert found == []
