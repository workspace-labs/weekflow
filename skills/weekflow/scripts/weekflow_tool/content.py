"""Read a meeting draft and check each finished item against a project file."""

from hashlib import sha256
from pathlib import Path, PureWindowsPath
import re

from .corrections import validate_corrections
from .docs_content import read_docs_fields
from .meeting_design import validate_snapshot
from .page import DESIGN, DESIGN_NOTICES, PICTURE_REMOVAL_ANSWERS
from .promises import validate_promises
from .screen_snapshot import read_app_ran, read_screen_snapshot
from .storage import Refusal, WEEKLY, iso_date
from .text_fields import read_latin_names, required_text as text, validate_arabic_text


def project_relative(files, argument):
    path = Path(argument)
    if path.is_absolute():
        try:
            return path.relative_to(files.root)
        except ValueError:
            # The owner may have opened the project through a link.
            resolved = path.resolve()
            if resolved.is_relative_to(files.root):
                return resolved.relative_to(files.root)
            raise Refusal("Keep the meeting content file inside the project folder.") from None
    return path


def items(value, key):
    rows = value.get(key, [])
    if not isinstance(rows, list):
        raise Refusal(f"Write {key} as a list in the meeting content file.")
    for number, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise Refusal(f"Write item {number} in {key} as an object with text.")
        yield text(row.get("text"), f"item {number} in {key}"), row


def received_items(data):
    values = data.get("received", [])
    if not isinstance(values, list):
        raise Refusal("Write received as a list of the exact texts of the needs received.")
    for number, value in enumerate(values, start=1):
        if text(value, f"item {number} in received") != value:
            raise Refusal(f"Use the exact need text for item {number} in received.")
    return values


def read_followups(content, data):
    if "meeting_promises" in data:
        results = validate_promises(data["meeting_promises"])
        if not results or any(row["status"] == "open" for row in results):
            raise Refusal("Restore the saved promise results.")
        content["meeting_promises"] = results
    if "missed_meetings" in data:
        dates = data["missed_meetings"]
        if not isinstance(dates, list) or not dates:
            raise Refusal("Restore the saved missed meeting dates.")
        content["missed_meetings"] = [iso_date(day, "A missed meeting date") for day in dates]
    if "corrections" in data:
        corrections = validate_corrections(data["corrections"])
        if not corrections:
            raise Refusal("Restore the saved corrections.")
        content["corrections"] = corrections
    if "corrections_frozen" in data:
        if data["corrections_frozen"] is not True:
            raise Refusal("Restore the saved correction selection.")
        content["corrections_frozen"] = True
    if "prior_needs_unavailable" in data:
        if data["prior_needs_unavailable"] is not True:
            raise Refusal("Restore the saved meeting content.")
        content["prior_needs_unavailable"] = True


def design_notices(value):
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(item for item in value if isinstance(item, str)
                              and re.fullmatch(r"[0-9a-f]{64}", item)))


def read_picture_removal_answers(data):
    if PICTURE_REMOVAL_ANSWERS not in data:
        return None
    history = data[PICTURE_REMOVAL_ANSWERS]
    message = "Restore the saved answers history for the picture removal."
    if not isinstance(history, dict) or set(history) != {"applies_to", "previous"}:
        raise Refusal(message)
    previous = history["previous"]
    if (not isinstance(previous, list) or not previous
            or not all(isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest)
                       for digest in (history["applies_to"], *previous))
            or len(set(previous)) != len(previous)):
        raise Refusal(message)
    return history


def proof(files, label, source, confirmed_digest=None):
    message = (f"Give the finished item {label!r} an existing source file "
               "inside the project and outside docs/weekly.")
    if not isinstance(source, str) or not source.strip():
        raise Refusal(message)
    relative = PureWindowsPath(source)
    if (relative.anchor or ".." in relative.parts or ":" in source
            or relative.is_relative_to(PureWindowsPath(WEEKLY))):
        raise Refusal(message)
    if confirmed_digest is not None:
        return relative.as_posix(), confirmed_digest
    try:
        path = files.path(Path(*relative.parts))
        weekly = PureWindowsPath(files.path(WEEKLY).resolve())
        if not PureWindowsPath(path.resolve()).is_relative_to(weekly) and path.is_file():
            with path.open("rb") as file:
                digest = sha256()
                for block in iter(lambda: file.read(65536), b""):
                    digest.update(block)
            return relative.as_posix(), digest.hexdigest()
    except (OSError, ValueError, Refusal):
        pass
    raise Refusal(message)


def read_finished(files, content, data, saved, check_live_proof):
    finished = list(items(data, "finished"))
    saved_digests = validate_digests(data, len(finished), required=False) if saved else None
    digests = []
    for index, (label, item) in enumerate(finished):
        confirmed_digest = None
        if not check_live_proof and saved_digests is not None:
            confirmed_digest = saved_digests[index]
        source, digest = proof(files, label, item.get("source"), confirmed_digest)
        content["finished"].append({"text": label, "source": source})
        digests.append(digest)
    return digests, saved_digests


def validate_digests(data, count, *, required):
    if "source_digests" not in data and not required:
        return None
    digests = data.get("source_digests")
    if (not isinstance(digests, list) or len(digests) != count
            or not all(isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest) for digest in digests)):
        raise Refusal("Restore the saved source evidence." if required else "Restore the saved finished-work evidence.")
    return digests


def read_content(files, relative, *, saved=False, check_live_proof=True, optional=False, mode="build",
                 language="en", allowed_latin=(), secret_check=None):
    data = files.read_json(relative, optional=optional)
    if data is None:
        return None, []
    if secret_check is not None:
        secret_check.check(data)
    if not isinstance(data, dict):
        raise Refusal("Write the meeting content as a JSON object.")

    arabic = language == "ar"
    check_language = arabic and check_live_proof
    content = {"headline": text(data.get("headline"), "the headline")}
    if arabic and "latin_names" in data:
        names = read_latin_names(data["latin_names"])
        content["latin_names"] = names
        allowed_latin = (*allowed_latin, *names)
    if check_language:
        validate_arabic_text(content["headline"], "the headline", allowed_latin)
    if mode == "build":
        content["finished"] = []
    content.update(next_week=[], needs=[])
    if mode == "docs":
        facts, sources, live_digests = read_docs_fields(files, data, check_live_proof=check_live_proof,
                                                       arabic=arabic, allowed_latin=allowed_latin)
        content.update(facts)
        saved_digests = validate_digests(data, len(sources), required=True) if saved else None
        digests = live_digests if check_live_proof else saved_digests
    else:
        digests, saved_digests = read_finished(files, content, data, saved, check_live_proof)
    for label, _ in items(data, "next_week"):
        content["next_week"].append({"text": label})
    for label, item in items(data, "needs"):
        need = {"text": label}
        if item.get("by"):
            need["by"] = iso_date(item["by"], f"The date for {label!r}")
        content["needs"].append(need)
    received = received_items(data)
    if received:
        content["received"] = received
    if mode == "build":
        app_ran = read_app_ran(data)
        if app_ran is not None:
            content["app_ran"] = app_ran
    if saved:
        read_followups(content, data)
        if DESIGN in data:
            validate_snapshot(data[DESIGN], language)
            content[DESIGN] = data[DESIGN]
        if DESIGN_NOTICES in data:
            notices = design_notices(data[DESIGN_NOTICES])
            if notices:
                content[DESIGN_NOTICES] = notices
        if mode == "docs" and "prior_decisions_unavailable" in data:
            if data["prior_decisions_unavailable"] is not True:
                raise Refusal("Restore the saved meeting content.")
            content["prior_decisions_unavailable"] = True
        if mode == "build":
            history = read_picture_removal_answers(data)
            if history is not None:
                content[PICTURE_REMOVAL_ANSWERS] = history
            screens = read_screen_snapshot(data)
            if screens:
                content["meeting_screens"] = screens
            content["meeting_changes"] = data.get("meeting_changes")
        if saved_digests is not None:
            if digests != saved_digests:
                label = "document" if mode == "docs" else "finished-work source"
                raise Refusal(f"The {label} files changed after preparation.")
            content["source_digests"] = saved_digests
        if data != content:
            raise Refusal("Restore the content saved when the meeting page was prepared.")
    if check_language:
        for key in ("finished", "needs", "next_week", "received"):
            for position, item in enumerate(content.get(key, ()), 1):
                label = item if isinstance(item, str) else item["text"]
                validate_arabic_text(label, f"item {position} in {key}", allowed_latin)
    return content, digests
