"""Check meeting content against secret settings without quoting their values."""

from collections import deque
from dataclasses import dataclass, field
import json
import os
from pathlib import Path, PureWindowsPath
import re
from stat import S_ISLNK, S_ISREG
from urllib.parse import unquote, urlsplit

from .storage import Refusal, WEEKLY
from .text_fields import one_line


SKIP_DIRS = {".git", "node_modules", ".venv", "venv", ".virtualenv", "virtualenv"}
EXAMPLES = {".env.example", ".env.sample", ".env.template"}
PLACEHOLDERS = {
    "changeme", "change-me", "change_me", "example", "none", "null", "true", "false",
    "0", "1", "yes", "no", "on", "off", "enabled", "disabled",
}
LONG_CREDENTIAL_WORDS = ("password", "passwd", "passphrase", "secret", "token", "credential")
JOINED_CREDENTIAL_MARKERS = (*LONG_CREDENTIAL_WORDS, "apikey", "accesskey", "privatekey")
JOINED_NOUN_ENDINGS = tuple(form for word in (*LONG_CREDENTIAL_WORDS, "key", "pwd")
                            for form in (word, word + "s"))
EDGE_ONLY_NOUNS = {"pass", "passes"}
AUTH_WORDS = {"auth", "auths"}
AUTH_LOCATORS = {"url", "host", "domain"}
ORDINARY_WORDS = {"author", "keyboard", "keywords", "monkey", "compass", "passenger", "secretary"}
DEPLOYMENT_WORDS = {"prod", "dev", "staging", "test", "local"}
CAMEL_EDGE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
JOINED_DEPLOYMENT_END = re.compile(rf"(?:{'|'.join(sorted(DEPLOYMENT_WORDS))})+$")
ASSIGNMENT = re.compile(r"^[ \t]*(?:export[ \t]+)?([A-Za-z_][A-Za-z_0-9]*)[ \t]*=[ \t]*", re.M)
QUOTED = {
    quote: re.compile(rf"{quote}((?:\\[\s\S]|[^{quote}\\])*){quote}[ \t]*(?:#[^\r\n]*)?(?=\r?$)", re.M)
    for quote in ("'", '"')
}
ESCAPES = {"n": "\n", "r": "\r", "t": "\t", "a": "\a", "b": "\b", "f": "\f", "v": "\v"}


def settings_paths(files):
    pending = [Path()]
    while pending:
        relative = pending.pop()
        try:
            with os.scandir(files.path(relative)) as entries:
                children = sorted(entries, key=lambda entry: entry.name)
            if relative.parts and any(entry.name == "pyvenv.cfg" and entry.is_file(follow_symlinks=False)
                                      for entry in children):
                continue
            for entry in children:
                child = relative / entry.name
                if entry.is_dir(follow_symlinks=False):
                    if entry.name not in SKIP_DIRS and child != WEEKLY:
                        pending.append(child)
                elif entry.name == ".env" or (entry.name.startswith(".env.") and entry.name not in EXAMPLES):
                    yield child
        except OSError:
            raise Refusal(f"Read the project settings folder {relative.as_posix()} and try again.") from None


def settings_target(files, relative):
    # Resolve components locally. A chain that leaves the project is rejected even
    # if its last link would lead back inside.
    current = files.root
    components = deque(relative.parts)
    links = 0
    while components:
        part = components.popleft()
        if part == "..":
            if current == files.root:
                raise ValueError
            current = current.parent
            continue
        target = current / part
        mode = target.lstat().st_mode
        if S_ISLNK(mode):
            links += 1
            if links > 40:
                raise ValueError
            destination = Path(os.readlink(target))
            if destination.is_absolute():
                root = files.root if destination.is_relative_to(files.root) else files.requested_root
                destination = destination.relative_to(root)
                current = files.root
            elif destination.anchor:
                raise ValueError
            components.extendleft(reversed(destination.parts))
        else:
            current = target
            if not components and not S_ISREG(mode):
                raise ValueError
    return current.relative_to(files.root)


def settings(source):
    position = 0
    while assignment := ASSIGNMENT.search(source, position):
        start = assignment.end()
        quote = source[start:start + 1]
        if quote in QUOTED:
            match = QUOTED[quote].match(source, start)
            if match is None:
                raise ValueError
            escapes = {"\\": "\\", quote: quote}
            if quote == '"':
                escapes.update(ESCAPES)
            value = re.sub(r"\\(.)", lambda item: escapes.get(item[1], item[0]), match[1])
            position = match.end()
        else:
            end = source.find("\n", start)
            position = len(source) if end < 0 else end + 1
            value = source[start:position].strip()
            if value.startswith("#") and source[start - 1] in " \t":
                value = ""
            else:
                value = re.split(r"[ \t]+#", value, maxsplit=1)[0].rstrip()
        yield assignment[1], value


def without_number(word):
    stem = word.rstrip("0123456789")
    if stem != word and stem not in DEPLOYMENT_WORDS:
        return stem.removesuffix("v")
    return stem


def name_words(name):
    # Retain underscore components alongside camel-case words so mixed
    # capitalization cannot hide a joined credential marker.
    joined, split = [], []
    for part in filter(None, name.split("_")):
        folded = without_number(part.lower())
        pieces = [folded] if folded in ORDINARY_WORDS else [
            without_number(word.lower()) for word in CAMEL_EDGE.split(part)
        ]
        # Do not reintroduce a matched ordinary word through the joined view.
        joined.append(pieces[-1] if ORDINARY_WORDS.intersection(pieces) else folded)
        split.extend(pieces)
    return joined, split


def last_meaningful(words):
    return next((word for word in reversed(words) if word and word not in DEPLOYMENT_WORDS), "")


def credential_noun(word):
    stem = without_number(JOINED_DEPLOYMENT_END.sub("", word))
    return stem not in ORDINARY_WORDS and (word in EDGE_ONLY_NOUNS or stem.endswith(JOINED_NOUN_ENDINGS))


def is_secret_setting(name, value):
    joined, split = name_words(name)
    words = set(joined + split) - ORDINARY_WORDS
    endings = {last_meaningful(joined), last_meaningful(split)}
    has_credential = any(credential_noun(word) or any(marker in word for marker in JOINED_CREDENTIAL_MARKERS)
                         for word in words)
    if not has_credential:
        if AUTH_WORDS.isdisjoint(words) or not AUTH_LOCATORS.isdisjoint(endings):
            return False
        if "method" in endings and one_line(value).casefold() == "password":
            return False
    if len(value) < 8 and (value.isalpha() or value.isdigit()):
        return any(credential_noun(word) for word in endings)
    return True


def decoded_url_part(part):
    try:
        return unquote(part, errors="strict")
    except UnicodeError:
        return part


def credential_values(name, value):
    if is_secret_setting(name, value):
        yield value
    try:
        url = urlsplit(value)
    except ValueError:
        return
    if url.username is not None and url.password:
        yield value
        password = decoded_url_part(url.password)
        if len(password) >= 8 or password != decoded_url_part(url.username):
            yield url.password
            yield password


def credential_forms(name, value):
    for candidate in credential_values(name, value):
        normal = one_line(candidate)
        if normal and normal.casefold() not in PLACEHOLDERS:
            yield candidate
            yield normal


@dataclass(frozen=True)
class Secret:
    name: str
    source: Path
    pattern: re.Pattern = field(repr=False)


def read_secrets(files):
    for relative in settings_paths(files):
        try:
            target = settings_target(files, relative)
            source = files.read_text(target)
            for name, value in settings(source):
                for form in dict.fromkeys(credential_forms(name, value)):
                    pattern = re.escape(form)
                    if len(form) < 8:
                        pattern = rf"(?<!\w){pattern}(?!\w)"
                    yield Secret(name, relative, re.compile(pattern))
        except (OSError, Refusal, ValueError):
            raise Refusal(f"Read {relative.as_posix()} as a settings file inside the project, "
                          "then prepare again.") from None


class SecretCheck:
    def __init__(self, files):
        self.secrets = tuple(read_secrets(files))

    def match(self, value):
        normal = one_line(value)
        return next((secret for secret in self.secrets
                     if secret.pattern.search(value) or secret.pattern.search(normal)), None)

    def safe_label(self, label, fallback):
        return fallback if self.match(label) else label

    def check_json(self, source):
        try:
            # Inspect repeated keys and their values before the normal decoder
            # collapses them into the draft's final values.
            data = json.loads(source, object_pairs_hook=tuple)
        except (ValueError, RecursionError):
            return
        self.check(data)

    def check(self, data):
        if not self.secrets:
            return
        pending = [("the content", data)]
        while pending:
            location, value = pending.pop()
            if isinstance(value, str):
                secret = self.match(value)
                if secret is not None:
                    name = self.safe_label(secret.name, "[setting name hidden]")
                    source = self.safe_label(secret.source.as_posix(), "[settings path hidden]")
                    where = self.safe_label(location, "the content")
                    raise Refusal(f"Project secret setting {name} in {source} matches {where}. "
                                  "Remove the value from the content file and prepare again.")
            elif isinstance(value, (dict, tuple)):
                entries = value.items() if isinstance(value, dict) else value
                for number, (key, entry) in enumerate(entries, start=1):
                    position = f"key {number} in {location}"
                    label = self.safe_label(key, f"field {number}")
                    child = f"{location} → {label}"
                    pending.extend(((child, entry), (position, key)))
                    if key == "source" and isinstance(entry, str):
                        pending.append((child, PureWindowsPath(entry).as_posix()))
            elif isinstance(value, list):
                pending.extend((f"item {number} in {location}", entry)
                               for number, entry in enumerate(value, start=1))
