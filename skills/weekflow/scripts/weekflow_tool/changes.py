"""Save changes and the days the owner gives them."""

import re
from datetime import date

from .pdf_text import BOLD, validate_pdf_text
from .storage import Refusal, iso_date
from .text_fields import one_line


CHANGES = "docs/weekly/changes.json"
TEXT_FIELDS = (("what", "what changed"), ("reason", "why it is needed"),
               ("asked_by", "who raised it"))
STATUSES = ("waiting", "approved", "later", "refused")
FIELDS = {"id", "date", "what", "reason", "asked_by", "days_added", "status",
          "decided_week", "decided_by"}


def change_number(value):
    if not isinstance(value, str) or not re.fullmatch(r"C-[0-9]{3,}", value):
        return None
    try:
        number = int(value[2:])
        if number and value == f"C-{number:03d}":
            return number
    except ValueError:
        return None
    return None


def nonempty_text(value):
    return isinstance(value, str) and bool(value.strip())


def invalid_change_field(row):
    if not isinstance(row, dict) or set(row) - FIELDS:
        return "fields"
    for field, _ in TEXT_FIELDS:
        if not nonempty_text(row.get(field)):
            return field
    days = row.get("days_added")
    week = row.get("decided_week")
    by = row.get("decided_by")
    status = row.get("status")
    if status not in STATUSES:
        return "status"
    if (days is not None or status == "approved") and (type(days) is not int or days < 0):
        return "days_added"
    if (week is not None or status == "approved") and (type(week) is not int or week < 1):
        return "decided_week"
    if status == "approved" and not nonempty_text(by) or by is not None and not isinstance(by, str):
        return "decided_by"
    return None


def read_changes(files):
    rows = files.read_json(CHANGES, optional=True)
    return [] if rows is None else validate_changes(rows)


def recorded_change_deciders(rows, week):
    if week["mode"] != "build":
        return {}
    answered = {entry["id"] for entry in week.get("answers", ())}
    decided_week = week["number"] if week.get("locked_on") else None
    return {row["id"]: row["decided_by"] for row in rows
            if row["id"] in answered and row.get("decided_week") == decided_week
            and nonempty_text(row.get("decided_by"))}


def validate_changes(rows):
    if not isinstance(rows, list):
        raise Refusal("Save changes.json as a list of changes.")

    seen = set()
    for position, row in enumerate(rows, start=1):
        number = change_number(row.get("id")) if isinstance(row, dict) else None
        where = f"changes.json row {position}"
        if number is not None:
            where += f" ({row['id']})"
        field = invalid_change_field(row)
        if field:
            raise Refusal(f"Fix {field} in {where}.")
        if number is None or number in seen:
            raise Refusal(f"Give changes.json row {position} a unique change ID like C-001.")
        iso_date(row.get("date"), f"The date in {where}")
        seen.add(number)
    return rows


def change(files, args):
    from .setup import project_text_design

    if args.id is not None:
        return add_days(files, args)

    values = {field: getattr(args, field) for field, _ in TEXT_FIELDS}
    missing = [f"Give {label} with --{field.replace('_', '-')}."
               for field, label in TEXT_FIELDS if not nonempty_text(values[field])]
    if missing:
        raise Refusal(*missing)

    design = project_text_design(files)
    for field, value in values.items():
        validate_pdf_text(value, "--" + field.replace("_", "-"), design=design)
    validate_pdf_text(values["what"], "--what", BOLD, design=design)

    rows = read_changes(files)
    number = max((change_number(row["id"]) for row in rows), default=0) + 1
    change_id = f"C-{number:03d}"
    rows.append({
        "id": change_id,
        "date": date.today().isoformat(),
        "what": one_line(values["what"]),
        "reason": one_line(values["reason"]),
        "asked_by": one_line(values["asked_by"]),
        "days_added": args.days,
        "status": "waiting",
        "decided_week": None,
        "decided_by": "",
    })
    files.write_json(CHANGES, rows)
    if args.days is None:
        return [f"Saved {change_id} as waiting. Ask the owner how many days to add."]
    return [f"Saved {change_id} as waiting."]


def add_days(files, args):
    if any(getattr(args, field) is not None for field, _ in TEXT_FIELDS):
        raise Refusal("Use only --id and --days when adding days to a saved change.")
    if change_number(args.id) is None:
        raise Refusal("Give a change ID like C-001.")
    if args.days is None:
        raise Refusal(f"Give the days for {args.id} with --days.")

    rows = read_changes(files)
    for row in rows:
        if row["id"] != args.id:
            continue
        if row["status"] != "waiting":
            raise Refusal(f"{args.id} is no longer waiting.")
        if row.get("days_added") is not None:
            raise Refusal(f"{args.id} already has days.")
        row["days_added"] = args.days
        files.write_json(CHANGES, rows)
        return [f"Recorded the days for {args.id}. It is still waiting."]
    raise Refusal(f"There is no saved change with ID {args.id}.")
