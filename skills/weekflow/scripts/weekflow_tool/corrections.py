"""Record dated additions to locked weeks and select what the next meeting shows."""

from datetime import date
import re

from .pdf_text import BOLD, BODY, validate_pdf_text
from .storage import Refusal, WEEKLY, iso_date
from .text_fields import one_line


CORRECTIONS = WEEKLY / "corrections.json"
DETAILS = ("what", "reason", "by")
FIELDS = {"id", "date", "week", "kind", *DETAILS}


def correction_number(value):
    if isinstance(value, str) and re.fullmatch(r"X-[0-9]{3,}", value):
        try:
            number = int(value[2:])
            if number and value == f"X-{number:03d}":
                return number
        except ValueError:
            pass
    return None


def validate_corrections(rows):
    if not isinstance(rows, list):
        raise Refusal("Save the corrections as a list.")
    found = set()
    for position, row in enumerate(rows, 1):
        if (not isinstance(row, dict) or set(row) != FIELDS
                or type(row["week"]) is not int or row["week"] < 1
                or row["kind"] not in ("correction", "removal")
                or any(not isinstance(row[key], str) or not row[key].strip() for key in DETAILS)):
            raise Refusal(f"Fix the fields in correction row {position}.")
        number = correction_number(row["id"])
        if number is None or number in found:
            raise Refusal(f"Give correction row {position} a unique ID like X-001.")
        iso_date(row["date"], f"The date in correction row {position}")
        found.add(number)
    return rows


def read_corrections(files):
    rows = files.read_json(CORRECTIONS, optional=True)
    return [] if rows is None else validate_corrections(rows)


def correction_details(args, *, check_fonts=True, design=None):
    details = {key: one_line(getattr(args, key)) for key in DETAILS}
    missing = [f"Fill in --{key}." for key, value in details.items() if not value]
    if missing:
        raise Refusal(*missing)
    if check_fonts:
        validate_correction_text(details, design)
    return details


def validate_correction_text(details, design=None):
    for key, value in details.items():
        validate_pdf_text(value, f"--{key}", BOLD if key == "what" else BODY, design=design)


def add_corrections(rows, weeks, *, kind, day, details):
    last = max((correction_number(row["id"]) for row in rows), default=0)
    return rows + [{"id": f"X-{number:03d}", "date": day, "week": week, "kind": kind, **details}
                   for number, week in enumerate(weeks, last + 1)]


def correct(files, args):
    from .meetings import read_week, week_file
    from .setup import project_text_design

    number = args.week
    if not files.path(week_file(number)).is_file() or not read_week(files, number).get("locked_on"):
        raise Refusal("Choose a locked week for the correction.")
    rows = add_corrections(read_corrections(files), [number], kind="correction",
                           day=date.today().isoformat(),
                           details=correction_details(args, design=project_text_design(files)))
    files.write_json(CORRECTIONS, rows)
    return [f'Recorded correction {rows[-1]["id"]} for week {number}.']


def pending_corrections(files, before_week):
    from .meetings import content_file, read_week, week_numbers

    rows = read_corrections(files)
    if not rows:
        return []
    shown = set()
    for number in week_numbers(files):
        if number >= before_week:
            break
        week = read_week(files, number)
        if week["held"] and week.get("owner_confirmed_on"):
            content = files.read_json(content_file(number), optional=True)
            if content is None:
                # With no snapshot, this meeting cannot prove a correction was shown.
                continue
            if not isinstance(content, dict):
                raise Refusal(f"Restore the saved content for week {number}.")
            shown.update(row["id"] for row in validate_corrections(content.get("corrections", [])))
    return [row for row in rows if row["id"] not in shown]
