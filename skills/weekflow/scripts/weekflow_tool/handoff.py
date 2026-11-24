"""Verify the locked date history and print rows for the owner's final check."""

from datetime import date
import re

from .changes import CHANGES, read_changes
from .lock_transaction import require_no_pending_transaction
from .meetings import read_project, read_week, week_numbers
from .page import charged_days, move_date
from .records import STATUS
from .setup import PROJECT_FILE
from .storage import Refusal, iso_date, json_text
from .text_fields import one_line


OWNER = "the owner"


def locked_build_weeks(files):
    weeks = []
    for number in week_numbers(files):
        try:
            week = read_week(files, number)
        except Refusal as error:
            raise Refusal(*(f"Week {number}: {message}" for message in error.messages)) from None
        if not week.get("locked_on"):
            raise Refusal(f"Close and lock week {number} before handing over the dates.")
        if week["mode"] == "build":
            weeks.append(week)
    if not weeks:
        raise Refusal("Record and lock a build week before handing over the dates.")
    return weeks


def check_locked_history(weeks, changes, planned):
    by_id = {change["id"]: change for change in changes}
    answered = set()
    agreed = planned
    for week in weeks:
        number = week["number"]
        answers = week.get("answers", [])
        if not week["held"] and answers != []:
            raise Refusal(f"Restore week {number} without answers because it was a missed meeting.")
        if week["end_before"] != agreed.isoformat():
            raise Refusal(f"Check week {number}. Its end_before is {week['end_before']}, "
                          f"but the earlier record gives {agreed}.")
        for entry in answers:
            change_id = entry["id"]
            change = by_id.get(change_id)
            answer = entry["answer"]
            if change_id in answered or change is None or change["status"] != STATUS[answer]:
                raise Refusal(f"Check the recorded answer for {change_id!r} in week {number} "
                              f"against {CHANGES}.")
            if answer == "yes" and change["decided_week"] != number:
                raise Refusal(f"Check the decided week for {change_id}. Its recorded answer is in week {number}.")
            days = charged_days(change, answer)
            if entry["days"] != days:
                raise Refusal(f"Check the recorded answer for {change_id} in week {number}. "
                              f"It adds {entry['days']} days and should add {days}.")
            answered.add(change_id)
        try:
            agreed = move_date(agreed, sum(entry["days"] for entry in answers))
        except Refusal as error:
            raise Refusal(f"Week {number}: {error.messages[0]}") from None
        saved = week.get("end_after", week["end_before"])
        if saved != agreed.isoformat():
            raise Refusal(f"Check week {number}. Its recorded answers give {agreed}, but end_after is {saved}.")
    for change in changes:
        if change["status"] == "approved" and change["id"] not in answered:
            raise Refusal(f"Find the recorded approval for {change['id']} in locked build week "
                          f"{change['decided_week']} before handing over the dates.")


def date_row(row_id, kind, value, source, confirmed, **details):
    return {"id": row_id, "kind": kind, "date": value, "source": source, "confirmed": confirmed, **details}


def delay_rows(delays, confirmed):
    for number, (value, what, days, reason) in enumerate(delays, 1):
        row_id = f"delay-{number}"
        value = iso_date(value, f"{row_id} date")
        try:
            count = int(days) if re.fullmatch(r"[+-]?[0-9]+", days) else 0
        except ValueError:
            count = 0
        if not count:
            raise Refusal(f"Give {row_id} a non-zero whole number of calendar days.")
        what, reason = one_line(what), one_line(reason)
        for field, text in (("what", what), ("reason", reason)):
            if not text:
                raise Refusal(f"Ask the owner for {field} on {row_id}.")
        yield date_row(row_id, "delay", value, OWNER, confirmed, what=what, days_added=count, reason=reason)


def check_dates(start, planned, real, events):
    for row_id, end in (("planned-end", planned), ("real-end", real)):
        if start > end:
            raise Refusal(f"Check the start and {row_id} dates with the owner. Start {start} is after {end}.")
    for row in events:
        event = date.fromisoformat(row["date"])
        if not start <= event <= real:
            raise Refusal(f"Check {row['id']} with the owner. Its date {event} is outside {start} through {real}.")
    calculated = move_date(planned, sum(row["days_added"] for row in events))
    if calculated != real:
        difference = (real - calculated).days
        raise Refusal(f"The recorded days give {calculated} and the real end is {real} "
                      f"(difference {difference:+d} calendar days from calculated to real). "
                      f"Ask the owner for the missing delay or the correct date.")


def preview(row):
    line = f"{row['id']} · {row['kind']} · {row['date']} · {row['source']}"
    if "what" in row:
        line += f" · {row['days_added']:+d} days\n   {row['what']!r}\n   Reason {row['reason']!r}"
        if "asked_by" in row:
            line += f"\n   Asked by {row['asked_by']!r}"
    return line


def handoff(files, args):
    require_no_pending_transaction(files)
    project = read_project(files)
    if project["mode"] != "build":
        raise Refusal("Finish the docs stage and enter build mode before handing over the dates.")
    weeks = locked_build_weeks(files)
    changes = read_changes(files)
    for change in changes:
        if change["status"] == "waiting":
            raise Refusal(f"{change['id']} is still waiting. Ask the owner for a decision and lock its week.")
    planned = date.fromisoformat(project["planned_end"])
    check_locked_history(weeks, changes, planned)

    start = date.fromisoformat(iso_date(args.start, "The start row (--start)"))
    real = date.fromisoformat(iso_date(args.real_end, "The real-end row (--real-end)"))
    events = [date_row(change["id"], "change request", change["date"],
                       f"{CHANGES}, {change['id']}, decided week {change['decided_week']}", args.confirmed,
                       **{field: change[field] for field in ("what", "reason", "asked_by", "days_added")})
              for change in changes if change["status"] == "approved"]
    events.extend(delay_rows(args.delay, args.confirmed))
    check_dates(start, planned, real, events)
    rows = [date_row("start", "start", start.isoformat(), OWNER, args.confirmed),
            date_row("planned-end", "planned end", planned.isoformat(), f"{PROJECT_FILE} (planned_end)",
                     args.confirmed),
            date_row("real-end", "real end", real.isoformat(), OWNER, args.confirmed), *events]
    payload = json_text(rows)
    try:
        payload.encode("utf-8")
    except UnicodeEncodeError:
        raise Refusal("Restore valid Unicode text in the date events before handing them over.") from None
    heading = "Dates confirmed by the owner" if args.confirmed else "Dates for the owner to confirm"
    return [heading, *(f"{number}. {preview(row)}" for number, row in enumerate(rows, 1)),
            "Dates JSON", payload.rstrip("\n")]
