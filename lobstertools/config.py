"""~/.lobster-tools.conf: KEY=value lines, # comments, optional quotes, ~ for home."""
import os


class ConfigError(Exception):
    pass


def parse_conf(text, home):
    settings = {}
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ConfigError("line %d of the config file is not KEY=value: %r" % (number, raw))
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if value == "~" or value.startswith("~/"):
            value = home + value[1:]
        settings[key.strip()] = value
    return settings


def resolve_root(flag, env, conf):
    return flag or env or conf.get("MAIL_ROOT") or None


def read_conf(home):
    path = os.path.join(home, ".lobster-tools.conf")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as handle:
        return parse_conf(handle.read(), home)
