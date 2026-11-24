"""Read project files and replace records inside docs/weekly."""

from contextlib import contextmanager, suppress
from datetime import date
import json
import os
from pathlib import Path, PureWindowsPath
import re
from tempfile import mkstemp


WEEKLY = Path("docs/weekly")


class Refusal(Exception):
    """A command could not proceed."""

    def __init__(self, *messages):
        super().__init__(*messages)
        self.messages = messages


def iso_date(value, label):
    if isinstance(value, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError:
            pass
    raise Refusal(f"{label} must be a real date in YYYY-MM-DD format.")


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def stage_file(path, data, temporary_files):
    handle, name = mkstemp(dir=path.parent, prefix=".weekflow-")
    temporary = Path(name)
    temporary_files.append(temporary)
    with os.fdopen(handle, "wb") as file:
        file.write(data)
    return temporary


def create_parents(directory, created):
    if directory.is_dir():
        return
    create_parents(directory.parent, created)
    try:
        directory.mkdir()
    except FileExistsError:
        if not directory.is_dir():
            raise
        return
    created.append(directory)


def remove_empty_parents(created):
    for directory in reversed(created):
        if not any(directory.iterdir()):
            directory.rmdir()


class ProjectFiles:
    def __init__(self, folder):
        self.requested_root = Path(folder).absolute()
        self.root = self.requested_root.resolve()
        if not self.root.is_dir():
            raise Refusal("Choose an existing project folder.")

    def path(self, relative):
        relative = Path(relative)
        if relative.anchor or PureWindowsPath(str(relative)).anchor or ".." in relative.parts:
            raise Refusal("Use a path inside the project folder.")
        path = self.root / relative
        try:
            resolved = path.resolve()
        except RuntimeError:
            raise Refusal("Remove the loop in the project path and try again.") from None
        if not resolved.is_relative_to(self.root):
            raise Refusal("Use a path that stays inside the project folder.")
        return path

    @contextmanager
    def command(self):
        if os.name != "posix":
            yield
            return
        # Lock the existing folder without creating a file on a refusal.
        from fcntl import LOCK_EX, flock

        folder = os.open(self.root, os.O_RDONLY)
        try:
            flock(folder, LOCK_EX)
            yield
        finally:
            os.close(folder)

    def read_text(self, relative, optional=False):
        path = self.path(relative)
        if optional and not path.exists() and not path.is_symlink():
            return None
        try:
            if path.is_file():
                return path.read_bytes().decode("utf-8-sig")
        except (OSError, UnicodeError):
            pass
        raise Refusal(f"Read {relative} as a UTF-8 file or replace it and try again.")

    def read_json(self, relative, optional=False):
        text = self.read_text(relative, optional=optional)
        if text is None:
            return None
        try:
            value = json.loads(text)
        except (ValueError, RecursionError):
            raise Refusal(f"Fix the JSON in {relative} and try again.") from None
        if value is None:
            raise Refusal(f"Fill in the JSON in {relative} and try again.")
        return value

    def write_path(self, relative):
        relative = Path(relative)
        if not relative.is_relative_to(WEEKLY) or relative == WEEKLY:
            raise Refusal("Write files inside docs/weekly.")
        path = self.path(relative)
        current = path
        while current != self.root:
            if current.is_symlink():
                raise Refusal("Replace links on the output path with files or folders inside docs/weekly.")
            if current.exists() and not (current.is_file() if current == path else current.is_dir()):
                raise Refusal(f"Fix the output path for {relative} and try again.")
            current = current.parent
        return path

    def write_json(self, relative, value, new=False):
        self.write_text(relative, json_text(value), new=new)

    def write_text(self, relative, text, new=False):
        if not new:
            self.write_batch([(relative, text)])
            return

        path = self.write_path(relative)
        data = text.encode("utf-8")
        created = []
        try:
            create_parents(path.parent, created)
            try:
                handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                raise Refusal(f"{path.name} already exists.") from None
            try:
                with os.fdopen(handle, "wb") as file:
                    file.write(data)
            except BaseException:
                path.unlink()
                raise
        except BaseException:
            remove_empty_parents(created)
            raise

    def write_batch(self, entries, *, retire=()):
        destinations = [(self.write_path(relative), data.encode("utf-8") if isinstance(data, str) else data)
                        for relative, data in entries]
        prior_copies = [self.write_path(relative) for relative in retire]
        keep_originals = len(destinations) > 1 or bool(prior_copies)
        pending = []
        temporary_files = []
        created = []
        retired = []
        failed = False
        keep_backups = False
        try:
            for path, data in destinations:
                create_parents(path.parent, created)
                draft = stage_file(path, data, temporary_files)
                original = None
                if keep_originals and path.exists():
                    original = stage_file(path, path.read_bytes(), temporary_files)
                pending.append((draft, path, original))

            for prior_copy in prior_copies:
                if not prior_copy.exists():
                    continue
                retired_copy = stage_file(prior_copy, b"", temporary_files)
                # Move the old copy away before any updated draft becomes visible.
                os.replace(prior_copy, retired_copy)
                retired.append((prior_copy, retired_copy))
            for draft, path, _ in pending:
                os.replace(draft, path)
        except BaseException:
            failed = True
            keep_backups = True
            for draft, path, original in reversed(pending):
                # A successful replace consumed its staged file.
                if draft.exists():
                    continue
                if original is None:
                    path.unlink()
                else:
                    os.replace(original, path)
            for prior_copy, retired_copy in reversed(retired):
                os.replace(retired_copy, prior_copy)
            keep_backups = False
            raise
        finally:
            # Leave recovery files in place if the filesystem also refused rollback.
            if not keep_backups:
                for temporary in temporary_files:
                    # A busy staging file does not undo publication or rollback.
                    with suppress(OSError):
                        temporary.unlink(missing_ok=True)
                if failed:
                    remove_empty_parents(created)
