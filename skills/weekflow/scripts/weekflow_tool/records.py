"""Record a held meeting, make its copy, and close the week."""

from dataclasses import replace
from datetime import date

from .changes import CHANGES, read_changes
from .client_pdf import render_pdf
from .lock_transaction import write_transaction
from .meeting_design import fallback_notice
from .meetings import (
    confirmed_view, content_file, current_week, legacy_copy_file, page_file, pdf_file, require_meeting, week_file,
)
from .page import DOCS_LATER, charged_days, move_date
from .pdf_artifact import current_pdf, require_current_pdf, stamp_pdf, used_font_fallback
from .pdf_text import validate_meeting_pdf_text, validate_pdf_text
from .promises import new_promises
from .saved_answers import selected_answers
from .screen_snapshot import require_screen_checks
from .screens import ensure_weekly_ignores
from .storage import Refusal, iso_date, json_text
from .text_fields import one_line


STATUS = {"yes": "approved", "later": "later", "no": "refused"}


def unlocked_week(files, *, meeting_required=False):
    week = current_week(files)
    if meeting_required:
        require_meeting(week)
    if week.get("locked_on"):
        raise Refusal("This week is locked. Prepare the next meeting.")
    return week


def checked_change(rows, shown):
    row = rows.get(shown["id"])
    if row is None or row["status"] != "waiting":
        raise Refusal(f'{shown["id"]} is no longer waiting.')
    if row.get("days_added") != shown["days_added"]:
        raise Refusal(f'The days for {shown["id"]} no longer match the meeting page.')
    return row


def build_outcome(files, view, selected, decider):
    prior = {entry["id"] for entry in view.week.get("answers", [])}
    rows = read_changes(files) if selected or prior else []
    by_id = {row["id"]: row for row in rows}
    answers = []
    for shown in view.changes:
        change_id = shown["id"]
        if change_id in selected or change_id in prior:
            row = checked_change(by_id, shown)
            row["decided_by"] = decider if change_id in selected else ""
        if change_id in selected:
            answer = selected[change_id]
            answers.append({"id": change_id, "answer": answer, "days": charged_days(shown, answer)})
    moved = move_date(view.end_before, sum(entry["days"] for entry in answers))
    writes = [(CHANGES, json_text(rows))] if selected or prior else []
    return {"answers": answers, "end_after": moved.isoformat()}, writes


def docs_outcome(view, selected, decider):
    answers, remaining = [], 0
    for decision, answer, remaining in view.running_docs_decisions(selected):
        if answer is None:
            continue
        entry = {"id": decision["id"], "answer": answer, "days": 0}
        if answer != DOCS_LATER:
            entry["decided_by"] = decider
        answers.append(entry)
    return {"answers": answers, "decisions_left": remaining}


def record(files, args):
    week = unlocked_week(files, meeting_required=True)
    view = confirmed_view(files, week, for_record=True, recover_fonts=True)
    if view.meeting > date.today():
        raise Refusal("The meeting date is in the future. Prepare the meeting again with the real date.")
    selected = selected_answers(args, view)
    attendees = [one_line(person) for person in args.attendee]
    if not all(attendees):
        raise Refusal("Give the name or role of each attendee.")
    decider = one_line(args.decided_by or "")
    needs_decider = (any(answer != DOCS_LATER for answer in selected.values())
                     if view.is_docs else bool(selected))
    if needs_decider and not decider:
        raise Refusal("Give who decided with --decided-by.")
    if selected and decider:
        validate_pdf_text(decider, "--decided-by", design=view.design, allow_fallback=True)

    outcome, writes = ((docs_outcome(view, selected, decider), []) if view.is_docs
                       else build_outcome(files, view, selected, decider))
    updated = dict(week, held=True, attendees=attendees, **outcome)
    updated.pop("signed_on", None)
    updated.pop("signed_by", None)
    build_deciders = {} if view.is_docs else dict.fromkeys(selected, decider)
    validate_meeting_pdf_text(replace(view, week=updated, build_deciders=build_deciders), allow_fallback=True)
    number = week["number"]
    writes = [*recovered_files(view), (week_file(number), json_text(updated)), *writes]
    write_transaction(files, writes, retire=(pdf_file(number), legacy_copy_file(number)))
    messages = [f"Recorded the meeting for week {number}."]
    if view.design.missing_roles:
        messages.append(fallback_notice(view.design, pdf=False))
    if week["held"]:
        if view.is_docs:
            messages.append("The old PDF no longer applies. Make a new PDF.")
        else:
            messages.append("The old PDF and signature no longer apply. Make a new PDF.")
        if not view.is_docs and updated["end_after"] != week["end_before"]:
            messages.append("A new paper signature is needed.")
    return messages


def recovered_files(view):
    writes = list(view.design.assets.items())
    if view.restored_page is not None:
        writes.append((page_file(view.week["number"]), view.restored_page))
    return writes


def require_build_deciders(view):
    if not view.is_docs:
        for answer in view.week.get("answers", ()):
            identifier = answer["id"]
            if identifier not in view.build_deciders:
                raise Refusal(f"Use record to give who decided {identifier}.")


def client_copy(files, _args):
    week = current_week(files)
    require_meeting(week)
    if not week.get("owner_confirmed_on"):
        draft = files.read_json(content_file(week["number"]), optional=True)
        if isinstance(draft, dict):
            require_screen_checks(files, draft)
    view = confirmed_view(files, week, recover_fonts=week["held"])
    require_screen_checks(files, view.content)
    number = week["number"]
    relative = pdf_file(number)
    writes = recovered_files(view)
    missing = view.design.missing_roles
    locked = week.get("locked_on")
    locked_answered_build = locked and not view.is_docs and bool(week["answers"])
    if missing or writes or locked:
        existing = current_pdf(files, view)
        if existing is not None and (locked_answered_build or missing or writes or used_font_fallback(existing)):
            write_transaction(files, writes)
            return [f"The client PDF is at {relative.as_posix()}."]
    require_build_deciders(view)
    copy = stamp_pdf(render_pdf(view), view)
    if locked:
        path = files.write_path(relative)
        if path.is_file():
            if path.read_bytes() != copy:
                raise Refusal("Keep the existing PDF for the locked week.")
            return [f"The client PDF is at {relative.as_posix()}."]
    ensure_weekly_ignores(files)
    writes.append((relative, copy))
    write_transaction(files, writes, retire=(legacy_copy_file(number),))
    messages = [f"Made the client PDF at {relative.as_posix()}."]
    if missing:
        messages.append(fallback_notice(view.design))
    return messages


def sign(files, args):
    week = unlocked_week(files, meeting_required=True)
    if week["mode"] == "docs":
        raise Refusal("Docs meetings have no delivery date to sign for.")
    view = confirmed_view(files, week, recover_fonts=week["held"])
    if view.end_after == view.end_before:
        raise Refusal("The delivery date did not move. No signature is needed.")
    require_build_deciders(view)
    require_current_pdf(files, view)
    signer = one_line(args.by)
    if not signer:
        raise Refusal("Give who signed on paper with --by.")
    if view.project["language"] == "ar":
        validate_pdf_text(signer, "--by", design=view.design, allow_fallback=True)
    signed_on = date.fromisoformat(iso_date(args.on, "The signature date"))
    if signed_on < view.meeting or signed_on > date.today():
        raise Refusal("Use a signature date from the meeting date through today.")
    updated = dict(week, signed_by=signer, signed_on=signed_on.isoformat())
    write_transaction(files, [*recovered_files(view), (week_file(week["number"]), json_text(updated))])
    return [f'Recorded the paper signature for week {week["number"]}.']


def lock(files, _args):
    week = unlocked_week(files)
    if not week["held"]:
        raise Refusal("Record the meeting before locking the week.")
    view = confirmed_view(files, week, recover_fonts=True)
    if view.design.missing_roles:
        needs_copy = current_pdf(files, view) is None
    else:
        require_current_pdf(files, view)
        needs_copy = False
    today = date.today()
    if not view.is_docs and view.end_after != view.end_before:
        signed_by = week.get("signed_by")
        if not isinstance(signed_by, str) or not signed_by.strip() or not week.get("signed_on"):
            raise Refusal("Record the paper signature before locking a moved delivery date.")
        signed_on = date.fromisoformat(iso_date(week["signed_on"], "The signature date"))
        if not view.meeting <= signed_on <= today:
            raise Refusal("Use a signature date from the meeting date through today.")

    number = week["number"]
    writes = recovered_files(view)
    if not view.is_docs and week["answers"]:
        rows = read_changes(files)
        by_id = {row["id"]: row for row in rows}
        shown = {row["id"]: row for row in view.changes}
        for entry in week["answers"]:
            row = checked_change(by_id, shown[entry["id"]])
            if not (row.get("decided_by") or "").strip():
                raise Refusal(f'Use record to give who decided {row["id"]}.')
            row.update(status=STATUS[entry["answer"]], decided_week=number)
        writes.append((CHANGES, json_text(rows)))
    if view.content["next_week"]:
        writes.append(new_promises(files, number, view.content["next_week"]))
    messages = []
    retire = ()
    if needs_copy:
        require_screen_checks(files, view.content)
        writes.append((pdf_file(number), stamp_pdf(render_pdf(view), view)))
        ensure_weekly_ignores(files)
        retire = (legacy_copy_file(number),)
        messages.append(fallback_notice(view.design))
    writes.append((week_file(number), json_text(dict(week, locked_on=today.isoformat()))))
    write_transaction(files, writes, retire=retire)
    return [*messages, f"Locked week {number}."]
