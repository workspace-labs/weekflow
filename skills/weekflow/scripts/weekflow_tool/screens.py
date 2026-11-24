"""Keep the ordered screen list and the evidence for each saved picture."""

from datetime import date
from fnmatch import fnmatchcase
from hashlib import sha256
from pathlib import Path
import re

from .lock_transaction import write_transaction
from .pdf_text import BOLD, validate_pdf_text
from .picture_bytes import PICTURE_NAME_PATTERN, SCREEN_ID_PATTERN, clean_picture, read_regular_picture
from .storage import Refusal, WEEKLY, iso_date, json_text
from .text_fields import one_line


SCREENS_FILE = WEEKLY / "screens.json"
SCREEN_DIR = WEEKLY / "screens"
HISTORY_FILE = SCREEN_DIR / ".history" / "pictures.json"
IGNORE_FILE = WEEKLY / ".gitignore"
APP_FLOW = Path("docs/app-flow/app-flow.md")
SCREEN_ID = re.compile(SCREEN_ID_PATTERN)
PICTURE_NAME = re.compile(PICTURE_NAME_PATTERN)
DIGEST = re.compile(r"[a-f0-9]{64}")
SCREEN_COLUMNS = {"id", "order", "name", "state", "source", "picture", "picture_kind",
                  "taken_on", "previous_picture", "owner_checked_on"}
STATES = {"finished": "finished", "being-built": "being built", "not-built": "not built"}
FLOW_SCREEN = re.compile(r"^[0-9\u0660-\u0669\u06f0-\u06f9]+\.\s+([^:\r\n]+):\s*\S")
FLOW_SKETCH = re.compile(r"\s*\[\s*(?:form|list|grid|detail|done|message|blank)\s*\]$", re.IGNORECASE)
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
MAX_ID = 40


def weekly_ignore_writes(files):
    path = files.write_path(IGNORE_FILE)
    original = path.read_bytes() if path.is_file() else b""
    lines = original.removeprefix(b"\xef\xbb\xbf").splitlines()
    missing = []
    for directory in (b"screens", b"pages"):
        rule = directory + b"/"
        covered = False
        for line in lines:
            line = line.rstrip(b" ")
            negated = line.startswith(b"!")
            pattern = line.removeprefix(b"!").removeprefix(b"/").removeprefix(b"**/").removesuffix(b"/")
            if not line.startswith(b"#") and fnmatchcase(directory, pattern):
                covered = not negated
        if not covered:
            missing.append(rule)
    if missing:
        separator = b"\r\n" if b"\r\n" in original else b"\n"
        gap = separator if original and not original.endswith(b"\n") else b""
        return [(IGNORE_FILE, original + gap + separator.join(missing) + separator)]
    return []


def ensure_weekly_ignores(files):
    writes = weekly_ignore_writes(files)
    if writes:
        files.write_batch(writes)


def screen_id(value):
    if not isinstance(value, str) or len(value) > MAX_ID or not SCREEN_ID.fullmatch(value):
        raise Refusal("Use a screen ID of up to 40 lowercase letters, digits and single hyphens.")
    return value


def screen_name(value, *, check_font=True, design=None):
    if not isinstance(value, str) or not one_line(value):
        raise Refusal("Give the screen a name.")
    name = one_line(value)
    if check_font:
        validate_pdf_text(name, "screen name", BOLD, design=design)
    return name


def picture_reference(reference, owner=None):
    name = reference.removeprefix("screens/") if isinstance(reference, str) else ""
    match = PICTURE_NAME.fullmatch(name)
    if match is None or reference != "screens/" + name or owner is not None and match["id"] != owner:
        raise Refusal("Give the saved picture path for this screen, starting with screens/.")
    screen_id(match["id"])
    if match["capture"] != "design":
        iso_date(match["capture"], "The picture's capture date")
    return match


def picture_relative(reference, screen_id=None):
    return SCREEN_DIR / picture_reference(reference, screen_id)[0]


def check_relative(reference):
    return SCREEN_DIR / ".checked" / (picture_reference(reference)[0] + ".json")


def picture_details(reference):
    capture = picture_reference(reference)["capture"]
    return ("design", None) if capture == "design" else ("screenshot", capture)


def picture_digest(reference):
    return picture_reference(reference)["digest"]


def picture_path(files, reference):
    return files.write_path(picture_relative(reference))


def read_saved_picture(files, reference, *, allow_missing=False):
    try:
        data = read_regular_picture(picture_path(files, reference))
        if picture_digest(reference) == sha256(data).hexdigest():
            return data
    except FileNotFoundError:
        if allow_missing:
            return None
    except (OSError, Refusal):
        pass
    raise Refusal(f"The saved picture {reference} is missing or changed.")


def checked_picture(files, reference, digest):
    relative = check_relative(reference)
    files.write_path(relative)
    receipt = files.read_json(relative, optional=True)
    if (not isinstance(receipt, dict) or set(receipt) != {"digest", "checked_on"}
            or receipt["digest"] != digest):
        return None
    checked_on = iso_date(receipt["checked_on"], "The picture check date")
    return checked_on if checked_on <= date.today().isoformat() else None


def validate_screen(row):
    if not isinstance(row, dict) or set(row) != SCREEN_COLUMNS:
        raise Refusal("Use the saved screen columns in docs/weekly/screens.json.")
    code = screen_id(row["id"])
    if (type(row["order"]) is not int or row["order"] < 1
            or row["name"] != screen_name(row["name"], check_font=False)
            or row["state"] not in STATES.values() or row["source"] not in ("owner", "frameflow")):
        raise Refusal(f"Check the saved screen row for {code}.")
    if row["picture"]:
        picture_reference(row["picture"], code)
        kind, taken = picture_details(row["picture"])
        if row["picture_kind"] != kind or row["taken_on"] != (taken or ""):
            raise Refusal(f"Check the saved picture type and date for {code}.")
        if row["owner_checked_on"]:
            iso_date(row["owner_checked_on"], "The picture check date")
    elif any(row[key] != "" for key in ("picture", "picture_kind", "taken_on", "owner_checked_on")):
        raise Refusal(f"Check the saved picture fields for {code}.")
    if row["previous_picture"]:
        picture_reference(row["previous_picture"], code)
        if row["previous_picture"] == row["picture"]:
            raise Refusal(f"Use different paths for the current and earlier pictures of {code}.")
    elif row["previous_picture"] != "":
        raise Refusal(f"Check the earlier picture for {code}.")


def read_screens(files):
    files.write_path(SCREENS_FILE)
    rows = files.read_json(SCREENS_FILE, optional=True)
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise Refusal("Use a list of screens in docs/weekly/screens.json.")
    for row in rows:
        validate_screen(row)
    if len({row["id"] for row in rows}) != len(rows) or len({row["order"] for row in rows}) != len(rows):
        raise Refusal("Give each saved screen a different ID and order.")
    return sorted(rows, key=lambda row: row["order"])


def blank_screen(code, order, name, source):
    return {"id": code, "order": order, "name": name, "state": "not built", "source": source,
            "picture": "", "picture_kind": "", "taken_on": "", "previous_picture": "", "owner_checked_on": ""}


def names_in_flow(text, *, design=None):
    in_story = False
    fence = None
    found = {}
    for line in text.splitlines():
        marker = FENCE.match(line)
        if fence:
            if re.fullmatch(rf" {{0,3}}{re.escape(fence[0])}{{{len(fence)},}}\s*", line):
                fence = None
            continue
        if marker:
            fence = marker[1]
        elif line.startswith("## "):
            in_story = True
        elif line.startswith("# ") or line.startswith("### "):
            in_story = False
        elif in_story and (match := FLOW_SCREEN.match(line.strip())):
            name = screen_name(FLOW_SKETCH.sub("", match[1].strip()), design=design)
            found.setdefault(name.casefold(), name)
    if not found:
        raise Refusal("No numbered screen rows were found in docs/app-flow/app-flow.md.")
    return found


def import_flow(files, _args):
    from .setup import project_text_design

    names = names_in_flow(files.read_text(APP_FLOW), design=project_text_design(files))
    rows = read_screens(files)
    taken = {row["id"] for row in rows}
    present = {row["name"].casefold() for row in rows}
    order = rows[-1]["order"] if rows else 0
    added = []
    serial = 0
    for key, name in names.items():
        if key not in present:
            serial += 1
            while f"screen-{serial}" in taken:
                serial += 1
            code = f"screen-{serial}"
            taken.add(code)
            order += 1
            added.append(blank_screen(code, order, name, "frameflow"))
    ensure_weekly_ignores(files)
    if added:
        files.write_json(SCREENS_FILE, rows + added)
    messages = [f"Added {len(added)} screen(s) from the flow."]
    messages.extend(f'{row["id"]}: {row["name"]}' for row in added)
    messages.extend(f'{row["name"]} ({row["id"]}) is no longer in the flow. Kept it in the screen list.'
                    for row in rows if row["name"].casefold() not in names)
    return messages


def upsert_screen(files, args):
    from .setup import project_text_design

    code = screen_id(args.id)
    rows = read_screens(files)
    row = next((item for item in rows if item["id"] == code), None)
    if row is None:
        order = rows[-1]["order"] + 1 if rows else 1
        row = blank_screen(code, order, screen_name(args.name, design=project_text_design(files)), "owner")
        rows.append(row)
    elif args.name is not None:
        row["name"] = screen_name(args.name, design=project_text_design(files))
    if args.order is not None:
        if type(args.order) is not int or args.order < 1:
            raise Refusal("Use a whole screen order starting at 1.")
        if any(item is not row and item["order"] == args.order for item in rows):
            raise Refusal(f"Screen order {args.order} is already used.")
        row["order"] = args.order
    if args.state is not None:
        row["state"] = STATES[args.state]
    ensure_weekly_ignores(files)
    files.write_json(SCREENS_FILE, sorted(rows, key=lambda item: item["order"]))
    return [f'Saved screen {code} ({row["name"]}).']


def find_screen(rows, code):
    screen_id(code)
    row = next((item for item in rows if item["id"] == code), None)
    if row is None:
        raise Refusal(f"There is no saved screen with ID {code}.")
    return row


def picture_date(row, kind, argument):
    if kind == "design":
        if argument is not None:
            raise Refusal("Leave out --taken-on for a design.")
        if row["state"] != "not built":
            raise Refusal("Use a design only for a screen marked not built.")
        return ""
    if row["state"] == "not built":
        raise Refusal("A screenshot needs a screen marked finished or being built.")
    taken = iso_date(argument, "--taken-on for a screenshot")
    if taken > date.today().isoformat():
        raise Refusal("Use a screenshot taken today or earlier.")
    return taken


def read_history(files):
    files.write_path(HISTORY_FILE)
    saved = files.read_json(HISTORY_FILE, optional=True)
    if saved is None:
        return {}
    if not isinstance(saved, dict) or not all(DIGEST.fullmatch(key) for key in saved):
        raise Refusal("Check the saved picture dates.")
    return {key: value if value == "design" else iso_date(value, "A saved picture date")
            for key, value in saved.items()}


def available_picture(files, prefix, ext):
    serial = 1
    while True:
        reference = f"screens/{prefix}-{serial}.{ext}"
        if not picture_path(files, reference).exists() and not files.write_path(check_relative(reference)).exists():
            return reference
        serial += 1


def referenced_picture_date(rows, digest):
    dates = set()
    for row in rows:
        for reference in (row["picture"], row["previous_picture"]):
            if reference and picture_digest(reference) == digest:
                dates.add(picture_details(reference)[1] or "design")
    return "design" if "design" in dates else min(dates, default=None)


def add_picture(files, args, number):
    rows = read_screens(files)
    row = find_screen(rows, args.id)
    taken = picture_date(row, args.kind, args.taken_on)
    ext, data = clean_picture(Path(args.file))
    digest = sha256(data).hexdigest()
    history = read_history(files)
    first_seen = history.get(digest) or referenced_picture_date(rows, digest)
    if taken and first_seen == "design":
        raise Refusal("These same picture bytes were already saved as a design.")
    if taken and first_seen is not None and first_seen < taken:
        raise Refusal(f"These same picture bytes were already saved as taken on {first_seen}.")
    if (row["picture"] and row["taken_on"] == taken and row["picture_kind"] == args.kind
            and picture_digest(row["picture"]) == digest
            and read_saved_picture(files, row["picture"], allow_missing=True) is not None):
        return [f'This picture is already saved as {row["picture"]}.']

    prefix = f'{args.id}-w{number}-{taken or "design"}-{digest}'
    reference = available_picture(files, prefix, ext)
    if row["picture"] and row["picture"] != reference:
        row["previous_picture"] = row["picture"]
    row.update(picture=reference, picture_kind=args.kind, taken_on=taken, owner_checked_on="")
    writes = [(picture_relative(reference), data), (SCREENS_FILE, json_text(rows))]
    earliest = taken if taken and (first_seen is None or taken < first_seen) else first_seen
    earliest = earliest or "design"
    if history.get(digest) != earliest:
        history[digest] = earliest
        writes.append((HISTORY_FILE, json_text(history)))
    ensure_weekly_ignores(files)
    write_transaction(files, writes)
    return [f"Saved {reference}. Ask the owner to check it for customer data."]


def check_picture(files, args):
    rows = read_screens(files)
    row = find_screen(rows, args.id)
    reference = args.file if args.file is not None else row["picture"]
    if not reference and args.file is None:
        raise Refusal(f"Save a picture before checking screen {args.id}.")
    picture_reference(reference, args.id)
    digest = sha256(read_saved_picture(files, reference)).hexdigest()
    today = date.today().isoformat()
    writes = [(check_relative(reference), json_text({"digest": digest, "checked_on": today}))]
    if reference == row["picture"]:
        row["owner_checked_on"] = today
        writes.append((SCREENS_FILE, json_text(rows)))
    write_transaction(files, writes)
    return [f"Recorded the owner's check for {reference}."]
