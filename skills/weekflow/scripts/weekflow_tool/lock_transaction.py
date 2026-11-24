"""Recover weekly writes before another command reads the project."""

from base64 import b64decode, b64encode
from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
import re

from .meeting_design_fonts import FROZEN_FONT_DIR, FROZEN_FONT_TARGET, FONT_LIMIT, OversizedFile, read_regular
from .picture_bytes import PICTURE_NAME_PATTERN
from .storage import Refusal, WEEKLY, json_text


LEGACY_UNDO_FILE = WEEKLY / ".weekflow-lock.json"
UNDO_FILE = WEEKLY / ".weekflow-undo.json"
REDACTION_FILE = WEEKLY / ".weekflow-removal.json"
REDACTION_STAGE = ".weekflow-removal-stage"
TARGET = re.compile(
    r"docs/weekly/(?:\.gitignore|project\.json|changes\.json|promises\.json|screens\.json|corrections\.json|"
    r"weeks/week-[1-9][0-9]*\.json|"
    r"pages/(?:[^/\r\n]+\.json|week-[1-9][0-9]*(?:-client\.txt|\.html|\.pdf)))"
)
PICTURE_TARGET = re.compile(rf"docs/weekly/screens/{PICTURE_NAME_PATTERN}")
PICTURE_CHECK_TARGET = re.compile(rf"docs/weekly/screens/\.checked/{PICTURE_NAME_PATTERN}\.json")
PICTURE_HISTORY_TARGET = re.compile(r"docs/weekly/screens/\.history/pictures\.json")


@dataclass(frozen=True)
class RemovalRecovery:
    weeks: list
    warnings: list
    picture: bool


def journal_path(files, relative):
    path = files.path(relative)
    if not path.exists() and not path.is_symlink():
        return
    return files.write_path(relative)


def recover_legacy_lock(files):
    path = journal_path(files, LEGACY_UNDO_FILE)
    if path is None:
        return
    before = files.read_json(LEGACY_UNDO_FILE)
    if (not isinstance(before, dict) or set(before) != {"number", "week", "changes"}
            or type(before["number"]) is not int or before["number"] < 1):
        raise Refusal("Restore the lock recovery file from a backup.")
    try:
        week = WEEKLY / "weeks" / f'week-{before["number"]}.json'
        snapshots = [(WEEKLY / "changes.json", b64decode(before["changes"], validate=True)),
                     (week, b64decode(before["week"], validate=True))]
    except (TypeError, ValueError):
        raise Refusal("Restore the lock recovery file from a backup.") from None
    list(checked_targets(files, (relative for relative, _ in snapshots)))
    for relative, data in snapshots:
        publish_entry(files, relative, data)
    os.unlink(path)


def checked_targets(files, paths):
    seen = set()
    for relative in paths:
        name = relative.as_posix()
        allowed = any(pattern.fullmatch(name) for pattern in (
            TARGET, PICTURE_TARGET, PICTURE_CHECK_TARGET, PICTURE_HISTORY_TARGET, FROZEN_FONT_TARGET,
        ))
        if not allowed or relative in seen:
            raise Refusal("Check the files listed in the weekly recovery record.")
        destination = files.write_path(relative)
        seen.add(relative)
        yield destination


def check_frozen_font_data(entries):
    for relative, data in entries:
        if (data is not None and FROZEN_FONT_TARGET.fullmatch(relative.as_posix())
                and sha256(data).hexdigest() != relative.stem):
            raise Refusal("Restore the frozen font that matches its saved digest.")


def updates(files, writes, retire):
    entries = [(Path(relative), None) for relative in retire]
    entries.extend((Path(relative), data.encode("utf-8") if isinstance(data, str) else data)
                   for relative, data in writes)
    paths = checked_targets(files, (relative for relative, _ in entries))
    check_frozen_font_data(entries)
    return [(relative, data, destination) for (relative, data), destination in zip(entries, paths)
            if data is not None or destination.exists()]


def journal_rows(entries):
    return [{"path": relative.as_posix(),
             "data": b64encode(data).decode("ascii") if data is not None else None}
            for relative, data in entries]


def read_entries(files, rows):
    if not isinstance(rows, list) or not rows:
        raise Refusal("Check the files listed in the weekly recovery record.")
    entries = []
    try:
        for row in rows:
            if not isinstance(row, dict) or set(row) != {"path", "data"}:
                raise ValueError
            data = row["data"]
            entries.append((Path(row["path"]), b64decode(data, validate=True) if data is not None else None))
    except (TypeError, ValueError):
        raise Refusal("Check the files listed in the weekly recovery record.") from None
    list(checked_targets(files, (relative for relative, _ in entries)))
    check_frozen_font_data(entries)
    return entries


def publish_entry(files, relative, data):
    destination = files.write_path(relative)
    if data is None:
        destination.unlink(missing_ok=True)
    else:
        if FROZEN_FONT_TARGET.fullmatch(relative.as_posix()):
            previous, _ = previous_font(files, relative)
        else:
            previous = destination.read_bytes() if destination.exists() else None
        if previous != data:
            files.write_batch([(relative, data)])


def previous_font(files, relative):
    try:
        data = read_regular(files, relative, FONT_LIMIT)
    except OversizedFile:
        return None, True
    return data, data is not None and sha256(data).hexdigest() != relative.stem


def redaction_stage(files, relative):
    return files.write_path(relative.with_name(REDACTION_STAGE))


def replace_redacted_file(files, relative, data):
    destination = files.write_path(relative)
    stage = redaction_stage(files, relative)
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage.unlink(missing_ok=True)
    handle = os.open(stage, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        os.replace(stage, destination)
    finally:
        stage.unlink(missing_ok=True)


def publish_redaction_entry(files, relative, data):
    # Only new bytes are written. Retired files are unlinked without a backup copy.
    destination = files.write_path(relative)
    redaction_stage(files, relative).unlink(missing_ok=True)
    if data is None:
        destination.unlink(missing_ok=True)
    elif not destination.exists() or destination.read_bytes() != data:
        replace_redacted_file(files, relative, data)


def undo_entries(files):
    journal = files.read_json(UNDO_FILE)
    created_font_directory = isinstance(journal, dict)
    if created_font_directory:
        if journal.keys() != {"entries", "created_font_directory"} or journal["created_font_directory"] is not True:
            raise Refusal("Check the files listed in the weekly recovery record.")
        journal = journal["entries"]
    entries = read_entries(files, journal)
    if created_font_directory and not any(FROZEN_FONT_TARGET.fullmatch(relative.as_posix())
                                          for relative, _ in entries):
        raise Refusal("Check the frozen fonts listed in the weekly recovery record.")
    return entries, created_font_directory


def recover_undo(files):
    path = journal_path(files, UNDO_FILE)
    if path is None:
        return
    entries, created_font_directory = undo_entries(files)
    for relative, data in entries:
        publish_entry(files, relative, data)
    if created_font_directory:
        directory = files.path(FROZEN_FONT_DIR)
        if not directory.is_symlink() and directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()
    os.unlink(path)


def redaction_picture_entries(entries):
    for relative, data in entries:
        if FROZEN_FONT_TARGET.fullmatch(relative.as_posix()):
            raise Refusal("Keep the frozen meeting fonts when removing details.")
        if relative.is_relative_to(WEEKLY / "screens"):
            name = relative.as_posix()
            if data is not None or not (PICTURE_TARGET.fullmatch(name)
                                        or PICTURE_CHECK_TARGET.fullmatch(name)):
                raise Refusal("A picture removal may only retire the saved file and its check.")
    return entries


def read_redaction(files):
    journal = files.read_json(REDACTION_FILE)
    if (not isinstance(journal, dict)
            or not {"weeks", "entries"} <= journal.keys() <= {"weeks", "entries", "warnings", "picture"}
            or ("picture" in journal and journal["picture"] is not True)
            or not isinstance(journal["weeks"], list)
            or any(type(number) is not int or number < 1 for number in journal["weeks"])):
        raise Refusal("Check the weekly removal recovery record.")
    warnings = journal.get("warnings", [])
    if not isinstance(warnings, list) or any(not isinstance(warning, str) for warning in warnings):
        raise Refusal("Check the warnings in the weekly removal recovery record.")
    entries = redaction_picture_entries(read_entries(files, journal["entries"]))
    picture = journal.get("picture", False) or any(
        PICTURE_TARGET.fullmatch(relative.as_posix()) for relative, _ in entries
    )
    return entries, RemovalRecovery(journal["weeks"], warnings, picture)


def recover_redaction(files):
    path = journal_path(files, REDACTION_FILE)
    if path is None:
        # An interruption before publishing the journal leaves only its staged copy.
        redaction_stage(files, REDACTION_FILE).unlink(missing_ok=True)
        return None
    entries, recovery = read_redaction(files)
    for relative, data in entries:
        publish_redaction_entry(files, relative, data)
    os.unlink(path)
    return recovery


def pending_replacements(files, relative):
    """Read writes that recovery could make to the chosen file."""
    for journal, read in ((UNDO_FILE, undo_entries), (REDACTION_FILE, read_redaction)):
        if journal_path(files, journal) is not None:
            entries, _ = read(files)
            for target, data in entries:
                if target == relative and data is not None:
                    yield data


def recover_transactions(files):
    recover_legacy_lock(files)
    recover_undo(files)
    return recover_redaction(files)


def require_no_pending_transaction(files):
    for relative in (LEGACY_UNDO_FILE, UNDO_FILE, REDACTION_FILE, WEEKLY / REDACTION_STAGE):
        path = files.path(relative)
        if path.is_symlink() or path.exists():
            raise Refusal("Resume the interrupted weekly command to complete recovery, then retry handoff.")


def write_transaction(files, writes, *, retire=()):
    entries = updates(files, writes, retire)
    if len(entries) < 2:
        for relative, data, _ in entries:
            publish_entry(files, relative, data)
        return
    before = []
    for relative, _, destination in entries:
        if FROZEN_FONT_TARGET.fullmatch(relative.as_posix()):
            previous, damaged = previous_font(files, relative)
            if damaged:
                # A repaired shared copy is safe to keep if the meeting write is rolled back.
                continue
        else:
            previous = destination.read_bytes() if destination.exists() else None
        before.append((relative, previous))
    if not before:
        for relative, data, _ in entries:
            publish_entry(files, relative, data)
        return
    journal = journal_rows(before)
    if (any(FROZEN_FONT_TARGET.fullmatch(relative.as_posix()) for relative, _, _ in entries)
            and not files.path(FROZEN_FONT_DIR).exists()):
        journal = {"entries": journal, "created_font_directory": True}
    files.write_json(UNDO_FILE, journal)
    try:
        for relative, data, _ in entries:
            publish_entry(files, relative, data)
        os.unlink(files.write_path(UNDO_FILE))
    except BaseException:
        recover_undo(files)
        raise


def write_redaction(files, writes, *, retire=(), weeks=(), warnings=(), picture=False):
    entries = updates(files, writes, retire)
    if not entries:
        return
    # A removal must never put the original name into an undo record.
    for relative, _, _ in entries:
        redaction_stage(files, relative)
    after = redaction_picture_entries([(relative, data) for relative, data, _ in entries])
    journal = {"weeks": list(weeks), "entries": journal_rows(after)}
    if picture:
        journal["picture"] = True
    if warnings:
        journal["warnings"] = list(warnings)
    replace_redacted_file(files, REDACTION_FILE, json_text(journal).encode("utf-8"))
    recover_redaction(files)
