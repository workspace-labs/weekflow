"""Save promises and the results supplied by the owner."""

import re

from .pdf_text import validate_pdf_text
from .storage import Refusal, WEEKLY, json_text
from .text_fields import one_line


PROMISES = WEEKLY / "promises.json"
RESULTS = {"done": "done", "not-finished": "not finished"}
FIELDS = {"id", "made_week", "what", "status", "checked_week", "note"}


def promise_number(value):
    if isinstance(value, str) and re.fullmatch(r"P-[0-9]{3,}", value):
        try:
            number = int(value[2:])
            if number and value == f"P-{number:03d}":
                return number
        except ValueError:
            pass
    return None


def has_text(value):
    return isinstance(value, str) and bool(value.strip())


def valid_fields(row):
    if not isinstance(row, dict) or set(row) - FIELDS:
        return False
    made_week = row.get("made_week")
    if type(made_week) is not int or made_week < 1 or not has_text(row.get("what")):
        return False
    status = row.get("status")
    if status == "open":
        return "checked_week" not in row and "note" not in row
    checked_week = row.get("checked_week")
    if status not in RESULTS.values() or type(checked_week) is not int or checked_week <= made_week:
        return False
    return has_text(row.get("note")) if "note" in row or status == "not finished" else True


def validate_promises(rows):
    if not isinstance(rows, list):
        raise Refusal("Save promises.json as a list of promises.")
    seen = set()
    for position, row in enumerate(rows, start=1):
        if not valid_fields(row):
            raise Refusal(f"Fix the fields in promise row {position}.")
        number = promise_number(row.get("id"))
        if number is None or number in seen:
            raise Refusal(f"Give promise row {position} a unique promise ID like P-001.")
        seen.add(number)
    return rows


def read_promises(files):
    rows = files.read_json(PROMISES, optional=True)
    return [] if rows is None else validate_promises(rows)


def new_promises(files, number, upcoming):
    """Return the next Promises sheet write to include in the lock transaction."""
    rows = read_promises(files)
    first_id = max((promise_number(row["id"]) for row in rows), default=0) + 1
    rows.extend({"id": f"P-{index:03d}", "made_week": number,
                 "what": item["text"], "status": "open"}
                for index, item in enumerate(upcoming, start=first_id))
    return PROMISES, json_text(rows)


def promise_results(files, number, last_held_number):
    earlier = [row for row in read_promises(files) if row["made_week"] < number]
    waiting = [f'Give the result for {row["id"]} ({row["what"]}).'
               for row in earlier if row["status"] == "open"]
    if waiting:
        raise Refusal(*waiting)
    return [row for row in earlier if last_held_number < row["checked_week"] <= number]


def check_promise(files, args):
    from .meetings import newest_number, next_week_number, read_week, week_file

    if promise_number(args.id) is None:
        raise Refusal("Give a promise ID like P-001.")
    note = one_line(args.note or "")
    if args.status == "not-finished" and not note:
        raise Refusal("Give a note for a promise that was not finished.")

    rows = read_promises(files)
    promise = next((row for row in rows if row["id"] == args.id), None)
    if promise is None:
        raise Refusal(f"There is no saved promise with ID {args.id}.")
    checked_week = promise.get("checked_week")
    if checked_week and files.path(week_file(checked_week)).is_file():
        if read_week(files, checked_week).get("locked_on"):
            raise Refusal(f"{args.id} was checked in a locked week.")

    newest = newest_number(files)
    current = read_week(files, newest) if newest else None
    if current and not current.get("locked_on"):
        if current["held"] or current.get("owner_confirmed_on"):
            raise Refusal("This meeting is confirmed or recorded. Prepare a meeting again before checking a promise.")
        number = newest
    else:
        number = next_week_number(files, newest)
    if promise["made_week"] >= number or (checked_week and checked_week != number):
        raise Refusal(f"{args.id} cannot be checked in this meeting.")

    from .setup import project_text_design

    validate_pdf_text(note, "--note", design=project_text_design(files))
    promise.update(status=RESULTS[args.status], checked_week=number)
    if note:
        promise["note"] = note
    else:
        promise.pop("note", None)
    files.write_json(PROMISES, rows)
    return [f"Saved the owner's result for {args.id} in week {number}."]
