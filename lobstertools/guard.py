"""script-guard: a Claude Code PreToolUse hook that refuses scripts and loops before they run
(Request 34 from bernstein; PLAN.md "Settled" 79 and 81-84).

It reads a shell command as the shell would, with a small reader of its own (quotes, backslashes,
operators, $( ), backticks, heredocs, redirections), and judges only the words that the shell would
run as commands: quoted text, a heredoc's body and an argument are never judged.
"""
import argparse
import json
import os
import re
import sys
import time

from lobstertools import config

NON_CODE, CODE = "non-code", "code"
LOOPS = ("for", "while", "until", "select")
SHELLS = ("sh", "bash", "zsh", "dash", "ksh", "fish", "csh", "tcsh")
PYTHON = re.compile(r"python(\d+(\.\d+)?)?\Z")
OTHER_INTERPRETERS = ("perl", "ruby", "node", "osascript", "php", "lua", "Rscript")
OPENING = ("if", "then", "elif", "else", "do", "!", "{")
CLOSING = ("fi", "done", "esac", "}")
ONLY_ASKING = ("--version", "--help", "-V", "-h", "-v")
OPERATORS = ("&&", "||", ";;", ";&", "|&", ";", "&", "|", "(", ")", "\n")
REDIRECTS = ("<<<", "<<-", "<<", "<>", "<&", "<", "&>>", "&>", ">>", ">&", ">|", ">")
ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(\[[^]]*\])?\+?=")


class Unreadable(Exception):
    """A command this reader cannot follow: allowed, with a line on standard error ("Settled" 82)."""


class Word:
    def __init__(self, value, quoted):
        self.value, self.quoted = value, quoted


class Reader:
    """Splits shell text into words and operators. The text inside $( ), backticks, <( ) and an
    unquoted heredoc's body is kept in self.inner, to be judged as commands of its own."""

    def __init__(self, text):
        self.text, self.i, self.inner, self.pending = text, 0, [], []

    def tokens(self, closing=False):
        """Words and operators up to the end, or (closing) to the ) that closes a $( )."""
        found, depth, text = [], 0, self.text
        while True:
            self.skip_blanks()
            if self.i >= len(text):
                if closing:
                    raise Unreadable("a $( ) is not closed")
                self.read_heredocs()
                return found
            char = text[self.i]
            if char == "#":
                while self.i < len(text) and text[self.i] != "\n":
                    self.i += 1
                continue
            if char == "\n":
                self.i += 1
                self.read_heredocs()
                found.append("\n")
                continue
            if char == ")" and closing and depth == 0:
                self.i += 1
                return found
            if text.startswith(("<(", ">("), self.i):
                self.i += 2
                self.inner.append(self.substitution())
                found.append(Word("", True))
                continue
            operator = self.operator()
            if operator:
                depth += {"(": 1, ")": -1}.get(operator, 0)
                found.append(operator)
                if operator in ("<<", "<<-"):
                    self.heredoc(operator)
                continue
            word = self.word()
            if word is not None:
                found.append(word)

    def skip_blanks(self):
        text = self.text
        while self.i < len(text):
            if text[self.i] in " \t":
                self.i += 1
            elif text.startswith("\\\n", self.i):
                self.i += 2
            else:
                break

    def operator(self):
        for each in REDIRECTS + OPERATORS:
            if self.text.startswith(each, self.i):
                self.i += len(each)
                return each
        return None

    def word(self):
        text, value, quoted = self.text, [], False
        start = self.i
        while self.i < len(text):
            char = text[self.i]
            if char in " \t\n;&|()<>":
                if char in "<>" and self.i > start and text[start:self.i].isdigit():
                    return None  # a file descriptor before a redirection: 2>&1
                break
            quoted = quoted or char in "'\"\\"
            if char == "\\":
                if text.startswith("\\\n", self.i):
                    self.i += 2
                    continue
                value.append(text[self.i + 1:self.i + 2])
                self.i += 2
            elif char == "'":
                end = text.find("'", self.i + 1)
                if end < 0:
                    raise Unreadable("a ' is not closed")
                value.append(text[self.i + 1:end])
                self.i = end + 1
            elif char == '"':
                self.i += 1
                value.append(self.expanding('"'))
            elif text.startswith("$'", self.i):
                value.append(self.ansi_quoted())
                quoted = True
            else:
                value.append(self.dollar_or_char())
        return Word("".join(value), quoted)

    def ansi_quoted(self):
        text, self.i = self.text, self.i + 2
        start = self.i
        while self.i < len(text):
            if text[self.i] == "\\":
                self.i += 2
            elif text[self.i] == "'":
                self.i += 1
                return text[start:self.i - 1]
            else:
                self.i += 1
        raise Unreadable("a $' is not closed")

    def dollar_or_char(self):
        """One piece of an unquoted or double-quoted word: a $( ), a $(( )), a ${ }, a backtick
        substitution or one character, read and left as text."""
        text = self.text
        if text.startswith("$((", self.i):
            return self.balanced("$((", "((", "))", "a $(( )) is not closed")
        if text.startswith("$(", self.i):
            self.i += 2
            self.inner.append(self.substitution())
            return "$( )"
        if text.startswith("${", self.i):
            return self.balanced("${", "{", "}", "a ${ } is not closed")
        if text[self.i] == "`":
            end = self.i + 1
            while end < len(text) and text[end] != "`":
                end += 2 if text[end] == "\\" else 1
            if end >= len(text):
                raise Unreadable("a ` is not closed")
            self.inner.append(re.sub(r"\\([`$\\])", r"\1", text[self.i + 1:end]))
            self.i = end + 1
            return "` `"
        self.i += 1
        return text[self.i - 1]

    def balanced(self, opening, deeper, closing, why):
        text, start, depth = self.text, self.i, 0
        self.i += len(opening)
        while self.i < len(text):
            if text.startswith(closing, self.i):
                if depth == 0:
                    self.i += len(closing)
                    return text[start:self.i]
                depth -= 1
                self.i += len(closing)
            elif text.startswith(deeper, self.i):
                depth += 1
                self.i += len(deeper)
            else:
                self.i += 1
        raise Unreadable(why)

    def substitution(self):
        """The text of a $( ) or <( ) whose opening has been read, up to its closing )."""
        start = self.i
        self.tokens(closing=True)
        return self.text[start:self.i - 1]

    def expanding(self, closing):
        """The rest of a double-quoted string (closing '"'), or of a heredoc's body (closing None):
        backslashes, $( ), ${ } and backticks are read; everything else is text."""
        text, value = self.text, []
        while self.i < len(text):
            char = text[self.i]
            if char == closing:
                self.i += 1
                return "".join(value)
            if char == "\\" and text[self.i + 1:self.i + 2] in ('$', '`', '"', '\\', '\n'):
                value.append(text[self.i + 1])
                self.i += 2
            elif char in "$`":
                value.append(self.dollar_or_char())
            else:
                value.append(char)
                self.i += 1
        if closing:
            raise Unreadable('a " is not closed')
        return "".join(value)

    def heredoc(self, operator):
        self.skip_blanks()
        if self.i >= len(self.text) or self.text[self.i] in "\n;&|()<>":
            raise Unreadable("a heredoc has no delimiter")
        delimiter = self.word()
        self.pending.append((delimiter.value, delimiter.quoted, operator == "<<-"))

    def read_heredocs(self):
        """At the end of a line: the bodies of the heredocs opened on it, in order."""
        for delimiter, quoted, tabs in self.pending:
            text, start = self.text, self.i
            while self.i < len(text):
                end = text.find("\n", self.i)
                end = len(text) if end < 0 else end
                line = text[self.i:end]
                self.i = min(end + 1, len(text))
                if (line.lstrip("\t") if tabs else line) == delimiter:
                    break
            if not quoted:
                body = Reader(text[start:self.i])
                body.expanding(None)
                self.inner.extend(body.inner)
        self.pending = []


class Command:
    """One simple command as the shell would run it: its words (assignments and redirections
    taken out), whether it is a loop or a function definition, and whether something is fed to
    its standard input (a heredoc, a here-string or a pipe)."""

    def __init__(self):
        self.words, self.loop, self.function, self.fed, self.stdin_file = [], None, None, False, None


def commands(text):
    """Every simple command in TEXT, those inside $( ), backticks and heredoc bodies included."""
    reader = Reader(text)
    found = parse(reader.tokens())
    for inner in reader.inner:
        found.extend(commands(inner))
    return found


def parse(tokens):
    found, current, piped, i = [], Command(), False, 0

    def finish():
        nonlocal current
        if current.words or current.loop or current.function:
            found.append(current)
        current = Command()

    while i < len(tokens):
        token = tokens[i]
        i += 1
        if isinstance(token, Word):
            at_start = not current.words and not current.loop
            if at_start and not token.quoted:
                if token.value in LOOPS:
                    current.loop = token.value
                    if token.value in ("while", "until"):
                        found.append(current)
                        current = Command()
                    continue
                if token.value in OPENING + CLOSING:
                    continue
                if token.value == "function":
                    name = tokens[i].value if i < len(tokens) and isinstance(tokens[i], Word) else ""
                    current.function = name
                    i += 1
                    finish()
                    continue
                if token.value == "case":
                    raise Unreadable("case is not read")
                if token.value == "[[":
                    while i < len(tokens) and not (isinstance(tokens[i], Word)
                                                   and tokens[i].value == "]]"):
                        i += 1
                    i += 1
                    continue
            if current.loop and current.loop in ("for", "select"):
                continue
            if not current.words and ASSIGNMENT.match(token.value) and not token.quoted:
                continue
            current.words.append(token.value)
            current.fed = current.fed or piped
            continue
        if token in REDIRECTS:
            target = tokens[i] if i < len(tokens) and isinstance(tokens[i], Word) else None
            if target is not None:
                i += 1
            if token in ("<<", "<<-", "<<<"):
                current.fed = True
            elif token == "<" and target is not None:
                current.stdin_file = target.value
            continue
        if token == "(" and len(current.words) == 1 and i < len(tokens) and tokens[i] == ")":
            current.function, current.words = current.words[0], []
            i += 1
            finish()
            continue
        if token == "(" and i < len(tokens) and tokens[i] == "(" and not current.words:
            while i < len(tokens) and not (tokens[i] == ")" and tokens[i + 1:i + 2] == [")"]):
                i += 1
            i += 2
            continue
        finish()
        piped = token in ("|", "|&")
    finish()
    return found


TEMPORARY = ("/tmp", "/private/tmp", "/var/folders", "/private/var/folders")


class Place:
    """Where a command is judged: the project's kind and folder, the working folder, and the
    temporary folders (by default /tmp, /var/folders, which holds a session's scratchpad, and
    $TMPDIR)."""

    def __init__(self, kind, project, cwd, temp):
        self.kind, self.ganglion = kind, kind == NON_CODE
        self.project = os.path.realpath(project) if project else None
        self.cwd = cwd or project or os.getcwd()
        if temp is None:
            temp = TEMPORARY + ((os.environ["TMPDIR"],) if os.environ.get("TMPDIR") else ())
        self.temp = [os.path.realpath(folder) for folder in temp]

    def path(self, word):
        """WORD as the file it names: ~, $HOME and $TMPDIR put in, relative to the working folder."""
        for name in ("HOME", "TMPDIR"):
            value = os.environ.get(name, "")
            word = word.replace("${%s}" % name, value).replace("$%s" % name, value)
        word = os.path.expanduser(word)
        return os.path.realpath(os.path.join(self.cwd, word))

    def temporary(self, word):
        return within(self.path(word), self.temp)

    def in_project(self, word):
        return self.project is not None and within(self.path(word), [self.project])


def within(path, folders):
    return any(path == folder or path.startswith(folder.rstrip("/") + "/") for folder in folders)


def starts_hash_bang(path):
    try:
        with open(path, "rb") as handle:
            return handle.read(2) == b"#!"
    except OSError:
        return False


def judge(command, kind, project=None, cwd=None, temp=None):
    """Why COMMAND is refused for a project of KIND in folder PROJECT, run from CWD, or None when
    it is allowed. TEMP: the temporary folders (None for the usual ones). Raises Unreadable when
    the command cannot be read."""
    if kind not in (NON_CODE, CODE):
        return None
    return judge_in(command, Place(kind, project, cwd, temp))


def judge_in(command, place):
    for each in commands(command):
        reason = judge_one(each, place)
        if reason:
            return reason
    return None


def judge_one(command, place):
    if command.loop:
        return "a loop (%s)" % command.loop if place.ganglion else None
    if command.function is not None:
        return ("a shell function definition (%s)" % command.function
                if place.ganglion else None)
    for words, keeps_input in unwrapped(command.words):
        inner = Command()
        inner.words = words
        if keeps_input:
            inner.fed, inner.stdin_file = command.fed, command.stdin_file
        reason = judge_words(inner, place)
        if reason:
            return reason
    return None


def skip_options(words, with_value="", long_with_value=(), clusters=True):
    """The position of the first word that is not an option. WITH_VALUE: the letters whose value
    is the next word when nothing is attached to them."""
    i = 0
    while i < len(words):
        word = words[i]
        if word == "--":
            return i + 1
        if word.startswith("--"):
            i += 2 if word in long_with_value else 1
            continue
        if not word.startswith("-") or word == "-":
            return i
        letters = word[1:]
        if letters[:1] in with_value and len(letters) == 1:
            i += 2
            continue
        if clusters and letters[-1:] in with_value and not letters[:1] in with_value:
            i += 2
            continue
        i += 1
    return i


def unwrapped(words):
    """The commands WORDS runs, each as (words, whether it keeps this command's standard input):
    the command itself, or what a wrapper (env, nohup, time, command, exec, nice, timeout,
    caffeinate, xargs, find -exec, job add --, each --, secrets run --) runs, looked through as
    often as wrappers are nested. None for a wrapper that runs nothing."""
    if not words:
        return []
    name, rest = os.path.basename(words[0]), words[1:]
    if name == "env":
        i = skip_options(rest, with_value="uPCS", long_with_value=("--unset", "--chdir"))
        while i < len(rest) and ASSIGNMENT.match(rest[i]):
            i += 1
        return unwrapped(rest[i:])
    if name in ("nohup", "time"):
        return unwrapped(rest[skip_options(rest):])
    if name == "command":
        if any(word in ("-v", "-V") for word in rest[:skip_options(rest)]):
            return []
        return unwrapped(rest[skip_options(rest):])
    if name == "exec":
        return unwrapped(rest[skip_options(rest, with_value="a"):])
    if name == "nice":
        return unwrapped(rest[skip_options(rest, with_value="n"):])
    if name == "caffeinate":
        return unwrapped(rest[skip_options(rest, with_value="tw"):])
    if name == "timeout":
        i = skip_options(rest, with_value="sk", long_with_value=("--signal", "--kill-after"))
        return unwrapped(rest[i + 1:])
    if name == "xargs":
        i = skip_options(rest, with_value="EIJLnPRSsad", clusters=False)
        return [(found, False) for found, _ in unwrapped(rest[i:])]
    if name == "find":
        found, i = [], 0
        while i < len(rest):
            if rest[i] in ("-exec", "-execdir", "-ok", "-okdir"):
                end = i + 1
                while end < len(rest) and rest[end] not in (";", "+"):
                    end += 1
                found.extend((each, False) for each, _ in unwrapped(rest[i + 1:end]))
                i = end
            i += 1
        return found
    if name in ("job", "each", "secrets"):
        return unwrapped(rest[rest.index("--") + 1:]) if "--" in rest else []
    return [(words, True)]


def judge_words(command, place):
    words = command.words
    name = os.path.basename(words[0])
    if name == "eval":
        return judge_in(" ".join(words[1:]), place)
    if name == "sleep":
        return "sleep" if place.ganglion else None
    if name in SHELLS:
        return judge_shell(name, words[1:], command, place)
    spec = OPTIONS.get("python" if PYTHON.match(name) else name)
    if spec is None:
        return judge_by_path(words[0], place)
    if words[1:] and all(word in ONLY_ASKING for word in words[1:]):
        return None
    if place.ganglion:
        return "an interpreter (%s)" % name
    what, how = program_of(spec, words[1:], command)
    if what == "inline":
        return "an inline program (%s %s)" % (name, how)
    return in_temporary(how, place) if what == "file" else None


def in_temporary(word, place):
    return "a script in a temporary folder (%s)" % word if place.temporary(word) else None


def judge_by_path(word, place):
    """A command run by its path: a file starting with #! from the project or a temporary folder,
    in a ganglion; from a temporary folder, in a claw ("Settled" 79)."""
    if "/" not in word or not starts_hash_bang(place.path(word)):
        return None
    if place.ganglion:
        if place.in_project(word) or place.temporary(word):
            return "a script run by its path from the project or a temporary folder (%s)" % word
        return None
    return in_temporary(word, place)


class Options:
    """How an interpreter's options are read: the letters that give it a program inline, the long
    options that do, the letter that runs a module, the letters that take the next word when
    nothing is attached, the letters followed only by digits, and the letters that take the rest
    of their word."""

    def __init__(self, inline, long_inline=(), module="", next_word="", digits="", rest="",
                 long_next=()):
        self.inline, self.long_inline, self.module = inline, long_inline, module
        self.next_word, self.digits, self.rest, self.long_next = next_word, digits, rest, long_next


OPTIONS = {
    "python": Options("c", module="m", next_word="WX"),
    "perl": Options("eE", digits="0l", rest="CdDiIMmx"),
    "ruby": Options("e", next_word="CIrEFW", rest="0ixKT"),
    "node": Options("ep", long_inline=("--eval", "--print"), next_word="rC",
                    long_next=("--require", "--import", "--loader", "--conditions")),
    "osascript": Options("e", next_word="ls"),
    "php": Options("rBRE", next_word="cdzt"),
    "lua": Options("e", next_word="l"),
    "Rscript": Options("e"),
}


def program_of(spec, arguments, command):
    """What an interpreter is given to run: ("inline", how), ("file", path), ("module", name) or
    ("none", "")."""
    i = 0
    while i < len(arguments):
        word = arguments[i]
        if word == "--":
            i += 1
            break
        if word == "-":
            return "inline", "-"
        if word.startswith("--"):
            option = word.split("=", 1)[0]
            if option in spec.long_inline:
                return "inline", option
            i += 2 if option in spec.long_next and "=" not in word else 1
            continue
        if not word.startswith("-"):
            break
        letters, k = word[1:], 0
        while k < len(letters):
            letter = letters[k]
            if letter in spec.inline:
                return "inline", "-" + letter
            if letter and letter == spec.module:
                return "module", letters[k + 1:] or (arguments[i + 1:i + 2] or [""])[0]
            if letter in spec.rest:
                break
            if letter in spec.next_word:
                if k == len(letters) - 1:
                    i += 1
                break
            k += 1
            if letter in spec.digits:
                while k < len(letters) and letters[k].isdigit():
                    k += 1
        i += 1
    if i < len(arguments):
        return ("inline", "-") if arguments[i] == "-" else ("file", arguments[i])
    if command.fed:
        return "inline", "on standard input"
    if command.stdin_file is not None:
        return "file", command.stdin_file
    return "none", ""


def judge_shell(name, arguments, command, place):
    for position, word in enumerate(arguments):
        if word.startswith("-") and not word.startswith("--") and "c" in word:
            rest = [w for w in arguments[position + 1:] if not w.startswith("-")]
            return judge_in(rest[0], place) if rest else None
    given = [word for word in arguments if not word.startswith("-")]
    if place.ganglion:
        if given or command.fed or command.stdin_file is not None or "-s" in arguments:
            return "a shell given a script or standard input (%s)" % name
        return None
    if given:
        return in_temporary(given[0], place)
    if command.fed:
        return "an inline program (%s on standard input)" % name
    if command.stdin_file is not None:
        return in_temporary(command.stdin_file, place)
    return None


PROG = "script-guard"
ALLOW, REFUSE = 0, 2
ADVICE = {
    NON_CODE: ("A ganglion writes no scripts and types no loops (its rule 11).",
               ("Use a tool: each (one command over a list), job or wait-for-file (to wait), "
                "measure in file-tools (to count or size files); a job no tool does yet is a "
                "request to a claw.")),
    CODE: ("A claw keeps every script it runs (its rule 20).",
           ("Write the program as a file in kept-scripts/, with a header and a row in its "
            "README, and run that file.")),
}


def say(text):
    sys.stderr.write("%s\n" % text)


def project_settings(project):
    """The project's lobster.conf as a dict, or {} when there is none."""
    path = os.path.join(project, "lobster.conf") if project else None
    if not path or not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as handle:
        return config.parse_conf(handle.read(), os.path.expanduser("~"))


def log_refusal(settings, project, data, reason, command):
    """One JSON line appended to .script-guard/PROJECT.log under the mail root ("Settled" 84, open
    question 110), or a line on standard error saying why it could not be."""
    root = config.resolve_root(None, os.environ.get("LOBSTER_MAIL_ROOT"),
                               config.read_conf(os.path.expanduser("~")))
    if not root:
        say("%s: this refusal is not logged: no mail root (LOBSTER_MAIL_ROOT, or MAIL_ROOT in "
            "~/.lobster-tools.conf)" % PROG)
        return
    name = os.path.basename(settings.get("SELF") or os.path.basename(project.rstrip("/")))
    line = {"time": os.environ.get("LOBSTER_GUARD_NOW")
            or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "project": name, "kind": settings.get("KIND"), "session": data.get("session_id")}
    for key in ("agent_id", "agent_type"):
        if data.get(key) is not None:
            line[key[:-3] if key == "agent_id" else key] = data[key]
    line.update({"reason": reason, "command": command[:300]})
    folder = os.path.join(root, ".script-guard")
    try:
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, name + ".log"), "a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")
    except OSError as error:
        say("%s: this refusal is not logged: %s" % (PROG, error.strerror or error))


def hook(stdin):
    try:
        data = json.loads(stdin.read())
    except ValueError:
        say("%s: its input is not the hook's JSON; allowed" % PROG)
        return ALLOW
    if not isinstance(data, dict) or data.get("tool_name") != "Bash":
        return ALLOW
    tool_input = data.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or not command.strip():
        return ALLOW
    project = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd")
    settings = project_settings(project)
    kind = settings.get("KIND")
    if kind not in ADVICE:
        return ALLOW
    try:
        reason = judge(command, kind, project, data.get("cwd") or project)
    except Unreadable as why:
        say("%s: cannot read this command (%s); allowed" % (PROG, why))
        return ALLOW
    if not reason:
        return ALLOW
    first, second = ADVICE[kind]
    say("%s refused this command: %s. %s" % (PROG, reason, first))
    say(second)
    log_refusal(settings, project, data, reason, command)
    return REFUSE


class UsageError(Exception):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise UsageError(message)


def check(argv):
    """--check: the verdict on one command, printed; exit 2 if refused. It logs nothing."""
    parser = Parser(
        prog=PROG,
        usage="%(prog)s [-h] [--check COMMAND [--kind {non-code,code}] [--project DIR]]",
        description="A Claude Code PreToolUse hook for the Bash tool: with no arguments it reads "
                    "the hook's JSON on standard input and refuses (exit 2, with the reason on "
                    "standard error) a loop, sleep or an interpreter in a ganglion "
                    "(KIND=non-code in lobster.conf), and an inline program in a claw "
                    "(KIND=code). Anything else, and any fault of its own, is exit 0.")
    parser.add_argument("--check", metavar="COMMAND", required=True,
                        help="judge COMMAND and print allowed or refused: REASON (exit 0 or 2)")
    parser.add_argument("--kind", choices=(NON_CODE, CODE),
                        help="judge as this kind of project (default: the project's lobster.conf)")
    parser.add_argument("--project", metavar="DIR",
                        help="the project folder whose lobster.conf gives the kind (default: here)")
    try:
        args = parser.parse_args(argv)
    except UsageError as error:
        say("%s: %s; nothing judged" % (PROG, error))
        return ALLOW
    project = args.project or os.getcwd()
    kind = args.kind
    if kind is None:
        if not os.path.isfile(os.path.join(project, "lobster.conf")):
            print("allowed (no lobster.conf in %s: %s refuses nothing there)" % (project, PROG))
            return ALLOW
        kind = project_settings(project).get("KIND")
        if kind not in ADVICE:
            print("allowed (KIND=%s: %s refuses nothing there)" % (kind or "", PROG))
            return ALLOW
    try:
        reason = judge(args.check, kind, project, os.getcwd())
    except Unreadable as why:
        print("allowed (cannot read it: %s)" % why)
        return ALLOW
    print("refused: %s" % reason if reason else "allowed")
    return REFUSE if reason else ALLOW


def main(argv=None, stdin=None):
    """As a hook, with no arguments: the hook's JSON on standard input, exit 2 to refuse, else 0.
    Any fault of its own allows the command (exit 0), with one line on standard error, so a broken
    guard never stops a session's work."""
    argv = sys.argv[1:] if argv is None else argv
    try:
        return check(argv) if argv else hook(stdin or sys.stdin)
    except Exception as error:  # noqa: BLE001  (a fault of its own never stops the session)
        say("%s: a fault of its own (%s: %s); allowed" % (PROG, type(error).__name__, error))
        return ALLOW
