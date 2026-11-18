"""Shared set-up for the request tests: a scratch mail root with mailboxes a, b and c, and a
project folder for a whose lobster.conf says KIND=code and SELF=a."""
import contextlib
import io

import pytest

from lobstertools import mail, request


def call(module, argv, stdin=""):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = module.main(list(argv), stdin=io.StringIO(stdin))
        except SystemExit as exit_:
            code = exit_.code if isinstance(exit_.code, int) else 1
    return code, out.getvalue(), err.getvalue()


@pytest.fixture
def world(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for name in ("LOBSTER_MAIL_ROOT", "LOBSTER_MAIL_AS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LOBSTER_MAIL_NOW", "2026-10-10T10:00:00+01:00")
    root = tmp_path / "mail"
    for name in ("a", "b", "c"):
        code, _, err = call(mail, ["init", name, "--root", str(root)])
        assert code == 0, err
    project = tmp_path / "a-code"
    project.mkdir()
    (project / "lobster.conf").write_text("KIND=code\nSELF=a\n", encoding="utf-8")
    return World(root, project, monkeypatch)


class World:
    def __init__(self, root, project, monkeypatch):
        self.root, self.project, self.monkeypatch = root, project, monkeypatch

    def at(self, stamp):
        self.monkeypatch.setenv("LOBSTER_MAIL_NOW", stamp)

    def rq(self, *argv, project=None, stdin=""):
        """request VERB ... for the project (a, unless another folder is given)."""
        argv = list(argv) + ["--root", str(self.root), "--project", str(project or self.project)]
        return call(request, argv, stdin)

    def lm(self, *argv, stdin=""):
        return call(mail, list(argv) + ["--root", str(self.root)], stdin)

    def send(self, me, them, subject, body="A body.\n"):
        code, out, err = self.lm("send", "--as", me, "--to", them, "--subject", subject, "-",
                                 "--json", stdin=body)
        assert code == 0, err
        return mail.json.loads(out)["id"]

    def reply(self, me, id_, body="An answer.\n"):
        code, out, err = self.lm("reply", "--as", me, id_, "-", "--json", stdin=body)
        assert code == 0, err
        return mail.json.loads(out)["id"]

    def move(self, verb, me, id_):
        code, _, err = self.lm(verb, "--as", me, id_)
        assert code == 0, err

    def requests(self):
        folder = self.project / "requests"
        return sorted(p.name for p in folder.iterdir()) if folder.exists() else []

    def files(self):
        """Every message file under the root, with its bytes."""
        return {str(p.relative_to(self.root)): p.read_bytes()
                for p in self.root.glob("*/*/*.md")}

    def fill(self, number_text, need="A need.\n"):
        path = next((self.project / "requests").glob("request-%s-*.md" % number_text))
        path.write_text(path.read_text("utf-8").replace("## Need\n", "## Need\n\n" + need), "utf-8")
        return path
