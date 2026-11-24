"""Prepare the current meeting and gate copies on owner confirmation."""

from base64 import b64encode
from dataclasses import replace
from datetime import date
from hashlib import sha256
import re

from .changes import read_changes, recorded_change_deciders, validate_changes
from .content import design_notices, project_relative, read_content
from .corrections import pending_corrections, validate_corrections
from .documents import prd_is_draft, read_approved_prd, read_meeting_form
from .lock_transaction import pending_replacements, write_transaction
from .meeting_design import (
    PAGE_LAYOUT_A, PDF_LAYOUT_C, PDF_LAYOUT_C_REVISED, PDF_PAPERS, load_design, prepare_design, saved_pdf_layout,
    studio_fonts, validate_snapshot, with_pdf_paper,
)
from .meeting_design_colors import COLOR_CHOICE, chosen_palette, given_color_choice, valid_color_choice
from .meeting_design_fonts import frozen_font_path, replace_font_payloads, saved_font_fallback
from .page import ANSWERS, DESIGN, DESIGN_NOTICES, DOCS_LATER, MeetingView
from .page_html import render_html
from .pdf_text import validate_meeting_pdf_text
from .project_secrets import SecretCheck
from .promises import promise_results
from .saved_answers import checked_docs_answers
from .screen_snapshot import require_screen_checks, screen_map, screen_snapshot
from .screens import add_picture, weekly_ignore_writes
from .setup import PROJECT_FILE, build_dates, scope_approval_message
from .storage import Refusal, WEEKLY, iso_date, json_text


WEEKS = WEEKLY / "weeks"
PAGES = WEEKLY / "pages"
SCOPE_DRAFT_NOTICE = PAGES / ".scope-draft-notice.json"
WEEK_NAME = re.compile(r"week-([1-9][0-9]*)\.json")
OPEN_DECISIONS_UNAVAILABLE = (
    "The last meeting's open decisions could not be read. Ask the owner which questions are still open."
)


def week_file(number):
    return WEEKS / f"week-{number}.json"


def content_file(number):
    return PAGES / f"week-{number}-content.json"


def page_file(number):
    return PAGES / f"week-{number}.html"


def legacy_copy_file(number):
    return PAGES / f"week-{number}-client.txt"


def pdf_file(number):
    return PAGES / f"week-{number}.pdf"


def week_numbers(files):
    directory = files.path(WEEKS)
    if not directory.exists():
        return []
    if not directory.is_dir():
        raise Refusal("Use a folder for the weekly records in docs/weekly/weeks.")
    numbers = [match[1] for path in directory.iterdir() if (match := WEEK_NAME.fullmatch(path.name))]
    try:
        return sorted(map(int, numbers))
    except ValueError:
        raise Refusal("Use a valid week number in each weekly record filename.") from None


def newest_number(files, before=None):
    return next((number for number in reversed(week_numbers(files)) if before is None or number < before), 0)


def next_week_number(files, newest):
    return max(newest, read_meeting_form(files).last_number) + 1


def correct_date(files, args):
    if any(read_week(files, number)["mode"] == "build" for number in reversed(week_numbers(files))):
        raise Refusal("A week record already exists.",
                      "Later delivery date changes belong in the meeting decision and record flow.")
    project = files.read_json(PROJECT_FILE, optional=True)
    if project is None:
        raise Refusal("Run start to set up weekly meetings before correcting the delivery date.")
    if not isinstance(project, dict) or "planned_end" not in project:
        raise Refusal("Check the saved planned_end in docs/weekly/project.json.")
    if project.get("mode") != "build":
        raise Refusal("Use enter-build once the scope is approved to set the delivery date.")
    planned_end = iso_date(args.planned_end, "planned_end")
    files.write_json(PROJECT_FILE, dict(project, planned_end=planned_end))
    return [f"Corrected the planned delivery date to {planned_end}."]


def read_week(files, number):
    row = files.read_json(week_file(number))
    if (not isinstance(row, dict) or type(row.get("number")) is not int
            or row["number"] != number or row.get("mode") not in ("docs", "build")
            or row.get("language", "en") not in ("en", "ar")
            or type(row.get("held")) is not bool):
        raise Refusal(f"Fix the record for week {number}.")
    iso_date(row.get("meeting_date"), "meeting_date")
    build = row["mode"] == "build"
    if build:
        iso_date(row.get("end_before"), "end_before")
    elif any(key in row for key in ("end_before", "end_after", "signed_by", "signed_on")):
        raise Refusal(f"Restore the docs record for week {number} without delivery date or signature fields.")
    if row.get("locked_on"):
        iso_date(row["locked_on"], "locked_on")
        if build and not row["held"] and row.get("end_after", row["end_before"]) != row["end_before"]:
            raise Refusal("A missed meeting must keep the same delivery date.")
    if row["held"]:
        if build:
            iso_date(row.get("end_after"), "end_after")
        elif type(row.get("decisions_left")) is not int or row["decisions_left"] < 0:
            raise Refusal("Check the decisions left in the recorded week.")
        attendees = row.get("attendees")
        if (not isinstance(attendees, list) or not attendees
                or not all(isinstance(person, str) and person.strip() for person in attendees)):
            raise Refusal("Check who attended the recorded meeting.")
        answers = row.get("answers")
        keys = {key for key, _ in ANSWERS}
        fields = {"id", "answer", "days"}
        allowed_fields = (fields,) if build else (fields, fields | {"decided_by"})
        if not isinstance(answers, list) or any(
            not isinstance(entry, dict) or set(entry) not in allowed_fields
            or not isinstance(entry["id"], str) or not isinstance(entry["answer"], str)
            or type(entry["days"]) is not int
            or (entry["answer"] not in keys if build else entry["days"] != 0)
            or ("decided_by" in entry and (entry["answer"] == DOCS_LATER
                                          or not isinstance(entry["decided_by"], str)
                                          or not entry["decided_by"].strip()))
            for entry in answers
        ):
            raise Refusal("Check the answers in the recorded week.")
    return row


def is_missed(week):
    return not week["held"] and bool(week.get("locked_on"))


def require_meeting(week):
    if is_missed(week):
        raise Refusal(f'No meeting was held on {week["meeting_date"]}.')


def read_project(files):
    project = files.read_json(PROJECT_FILE, optional=True)
    if project is None:
        raise Refusal("Run start to set up weekly meetings.")
    if (not isinstance(project, dict) or project.get("mode") not in ("docs", "build")
            or any(not isinstance(project.get(key), str) for key in ("project", "client", "meeting_day"))
            or not project["project"] or not project["meeting_day"]
            or not isinstance(project.get("attendees"), list)
            or not all(isinstance(person, str) for person in project["attendees"])):
        raise Refusal("Fix the setup in docs/weekly/project.json.")
    if project["mode"] == "build":
        iso_date(project.get("scope_approved_on"), "scope_approved_on")
        iso_date(project.get("planned_end"), "planned_end")
    elif any(project.get(key, "") != "" for key in ("scope_approved_on", "planned_end")):
        raise Refusal("Keep the scope approval and delivery dates empty in docs mode.")
    if project.get("language") not in ("en", "ar"):
        raise Refusal("Set language to en or ar in docs/weekly/project.json.")
    if "pdf_paper" in project and project["pdf_paper"] not in PDF_PAPERS:
        raise Refusal("Set pdf_paper to design or white in docs/weekly/project.json.")
    if COLOR_CHOICE in project and not valid_color_choice(project[COLOR_CHOICE]):
        raise Refusal("Restore the meeting_colors choice in docs/weekly/project.json.")
    return project


def project_for_week(project, week):
    # Live appearance choices only apply when preparing a meeting.
    project = {key: value for key, value in project.items() if key not in {"pdf_paper", COLOR_CHOICE}}
    project["language"] = week.get("language", "en")
    if week["mode"] == "docs":
        return dict(project, mode="docs", scope_approved_on="", planned_end="")
    return project


def require_running_project(files):
    if read_meeting_form(files).stopped:
        raise Refusal("The meeting form records Stop. The project stopped.")


def enter_build(files, args):
    require_running_project(files)
    project = read_project(files)
    if project["mode"] == "build":
        raise Refusal("Weekly meetings are already in build mode.")
    prd = read_approved_prd(files)
    if prd is None:
        raise Refusal("Enter build mode once the PRD is stamped Approved.")
    number = newest_number(files)
    if number:
        week = read_week(files, number)
        if not week.get("locked_on"):
            if week["held"] or "answers" in week:
                raise Refusal(f"Lock week {number} before entering build mode.")
            raise Refusal(f"Record and lock week {number} or run no-meeting if it was not held.")
    planned_end, message = build_dates(prd, args.planned_end)
    open_decisions = build_entry_questions(files, number)
    files.write_json(PROJECT_FILE, dict(project, mode="build", planned_end=planned_end,
                                       scope_approved_on=prd.scope_approved_on))
    return [f"Entered build mode. {scope_approval_message(prd)}", message, *open_decisions]


def waiting_changes(files, *, only_ids=None):
    waiting = [{key: value for key, value in row.items() if key not in {"decided_by", "decided_week"}}
               for row in read_changes(files)
               if row["status"] == "waiting" and (only_ids is None or row["id"] in only_ids)]
    missing = [f'Give the days for {row["id"]} ({row["what"]}).'
               for row in waiting if row.get("days_added") is None]
    if missing:
        raise Refusal(*missing)
    return waiting


def check_recorded_totals(view):
    if view.is_docs:
        checked_docs_answers({entry["id"]: entry["answer"] for entry in view.week["answers"]},
                             view.content["decisions"])
        expected = [{"id": decision["id"], "answer": answer, "days": 0}
                    for decision, answer, _ in view.running_docs_decisions() if answer is not None]
        recorded = [{key: entry[key] for key in ("id", "answer", "days")}
                    for entry in view.week["answers"]]
        if expected != recorded or view.decisions_left != view.week["decisions_left"]:
            raise Refusal("The recorded answers and decisions left do not match the saved decisions.")
        return
    answers, end = [], view.end_before
    for change, answer, days, end in view.running_decisions():
        if answer is not None:
            answers.append({"id": change["id"], "answer": answer, "days": days})
    if answers != view.week["answers"] or end != view.end_after:
        raise Refusal("The recorded answers and delivery date do not match the saved changes.")


def meeting_slot(files, *, recorded_message):
    """Find the week to write and the locked week it follows, if any."""
    number = newest_number(files)
    prior = read_week(files, number) if number else None
    if prior and not prior.get("locked_on"):
        if prior["held"] or "answers" in prior:
            raise Refusal(recorded_message)
        previous_number = newest_number(files, before=number)
        return number, read_week(files, previous_number) if previous_number else None, prior
    return next_week_number(files, number), prior, None


def screen_picture(files, args):
    number = newest_number(files)
    if number:
        week = read_week(files, number)
        if not week["held"] and not week.get("locked_on"):
            return add_picture(files, args, number)
    return add_picture(files, args, next_week_number(files, number))


def validate_meeting_order(meeting_date, previous):
    if previous and previous.get("locked_on") and meeting_date < previous["meeting_date"]:
        raise Refusal(f'The meeting date cannot be before the last locked week ({previous["meeting_date"]}).')


def previous_delivery_date(project, previous):
    if previous and previous["mode"] == "build" and previous.get("locked_on"):
        return previous.get("end_after", previous["end_before"])
    return project["planned_end"]


def preceding_meetings(files, before_week):
    """Find the last held meeting and consecutive missed dates before this draft."""
    missed_dates = []
    for number in reversed(week_numbers(files)):
        if number >= before_week:
            continue
        week = read_week(files, number)
        if week["held"]:
            return number, list(reversed(missed_dates))
        if is_missed(week):
            missed_dates.append(week["meeting_date"])
    return 0, list(reversed(missed_dates))


def carry_needs(files, content, last_held):
    if last_held is None:
        return
    earlier, _ = read_content(files, content_file(last_held["number"]), saved=True, mode=last_held["mode"],
                              language=last_held.get("language", "en"),
                              check_live_proof=False, optional=True)
    if earlier is None:
        content["prior_needs_unavailable"] = True
        return
    addressed = {need["text"] for need in content["needs"]}
    addressed.update(content.get("received", []))
    missing = [f'Carry forward or mark as received: {need["text"]}.'
               for need in earlier["needs"] if need["text"] not in addressed]
    if missing:
        raise Refusal(*missing)
    return earlier


def open_docs_decisions(earlier, week):
    answers = checked_docs_answers({entry["id"]: entry["answer"] for entry in week["answers"]},
                                   earlier["decisions"])
    open_decisions = [row for row in earlier["decisions"] if answers.get(row["id"]) in (None, DOCS_LATER)]
    if len(open_decisions) != week["decisions_left"]:
        raise Refusal("Restore the last meeting's recorded decisions before carrying them forward.")
    return open_decisions


def build_entry_questions(files, newest):
    try:
        last_held, _ = preceding_meetings(files, newest + 1)
        if not last_held:
            return []
        week = read_week(files, last_held)
        if week["mode"] != "docs" or not week["decisions_left"]:
            return []
        earlier, _ = read_content(files, content_file(last_held), saved=True, mode="docs",
                                  language=week.get("language", "en"),
                                  check_live_proof=False, optional=True)
        if earlier is None:
            return [OPEN_DECISIONS_UNAVAILABLE]
        decisions = open_docs_decisions(earlier, week)
    except (Refusal, OSError):
        return [OPEN_DECISIONS_UNAVAILABLE]
    return ["Open questions from the last docs meeting. Settle them or log them as changes.",
            *(f'{row["id"]} {row["question"]}' for row in decisions)]


def carry_decisions(content, earlier, last_held):
    open_decisions = []
    if last_held is not None and last_held["mode"] == "docs":
        if earlier is not None:
            open_decisions = open_docs_decisions(earlier, last_held)
        elif last_held["decisions_left"]:
            content["prior_decisions_unavailable"] = True
    settled = content.get("settled", [])
    earlier_questions = {row["question"] for row in open_decisions}
    unknown = [f'Use the exact text of an earlier open question in settled. Found {question!r}.'
               for question in settled if question not in earlier_questions]
    if unknown:
        raise Refusal(*unknown)
    now = {row["id"]: row["question"] for row in content["decisions"]}
    missing = [f'Carry forward open decision {row["id"]}: {row["question"]}'
               for row in open_decisions if now.get(row["id"]) != row["question"]
               and row["question"] not in settled]
    if missing:
        raise Refusal(*missing)


def correction_snapshot(files, number, draft, saved, content):
    if draft is not None and saved is not None:
        frozen = isinstance(saved, dict) and saved.get("corrections_frozen") is True
        if draft.get("owner_confirmed_on") or frozen:
            if not isinstance(saved, dict):
                raise Refusal("Restore the content from the confirmed meeting.")
            content["corrections_frozen"] = True
            return validate_corrections(saved.get("corrections", []))
    return pending_corrections(files, number)


def draft_path(files, argument):
    relative = project_relative(files, argument)
    if (relative.parent != PAGES or relative.suffix != ".json" or relative == SCOPE_DRAFT_NOTICE
            or "\r" in relative.name or "\n" in relative.name):
        raise Refusal("Keep the meeting draft as a JSON file directly in docs/weekly/pages/.")
    # Removal must be able to replace the draft itself, not just read through it.
    path = files.write_path(relative)
    if path.exists() and not any(entry.name == path.name for entry in path.parent.iterdir()):
        raise Refusal("Use the draft's exact filename in docs/weekly/pages/.")
    return relative


def check_prepare_content(files, argument):
    relative = draft_path(files, argument)
    check = SecretCheck(files)
    if not check.secrets:
        return check
    try:
        source = files.read_text(relative, optional=True)
    except Refusal:
        # Report unreadable or invalid JSON at the ordinary content validation step.
        source = None
    if source is not None:
        check.check_json(source)
    for replacement in pending_replacements(files, relative):
        try:
            source = replacement.decode("utf-8-sig")
        except UnicodeError:
            continue
        check.check_json(source)
    return check


def new_design_notices(content, saved, messages):
    printed = design_notices(saved.get(DESIGN_NOTICES)) if isinstance(saved, dict) else []
    unseen = []
    for message in messages:
        digest = sha256(message.encode("utf-8")).hexdigest()
        if digest not in printed:
            printed.append(digest)
            unseen.append(message)
    if printed:
        content[DESIGN_NOTICES] = printed
    return unseen


def saved_appearance(files, saved, week, language):
    if not isinstance(saved, dict):
        return None
    snapshot = saved.get(DESIGN)
    if snapshot is not None or language != "en" or DESIGN in saved:
        try:
            validate_snapshot(snapshot, language)
        except Refusal:
            # Preparation can replace a missing or damaged draft snapshot.
            return None
    design = load_design(files, snapshot, language=language, recover_fonts=True,
                         page=page_file(week["number"]))
    if design.missing_roles:
        raise Refusal("Restore the fonts saved with the meeting before preparing it again.")
    return design


def prepare_appearance(files, args, project, draft, saved, week, language):
    given = given_color_choice(args)
    saved_choice = project.get(COLOR_CHOICE)
    if draft and draft.get("owner_confirmed_on"):
        frozen = saved_appearance(files, saved, week, language)
        if frozen is not None:
            if given is not None and given != saved_choice:
                raise Refusal("This week is confirmed. Choose different colours when you prepare the next week.")
            previous_paper = (frozen.pdf or {}).get("paper", "design")
            if args.pdf_paper is not None and args.pdf_paper != previous_paper:
                raise Refusal("This week is confirmed. Choose different PDF paper when you prepare the next week.")
            return frozen, [], None

    design, notices = prepare_design(files, language)
    choice = None
    if not design.has_project_values:
        choice = given or saved_choice
        if choice is None:
            frozen = saved_appearance(files, saved, week, language)
            if frozen is None:
                raise Refusal("Keep the standard colours or give your main colour. "
                              "Use --colors standard or --main-color '#RRGGBB', with optional "
                              "--background-color and --text-color.")
            if args.pdf_paper is None:
                return frozen, notices, None
            design = replace(frozen, source_main=frozen.colors["main"])
        elif choice != "standard":
            palette, messages = chosen_palette(choice)
            design = replace(design, source_main=choice["main"], **palette)
            notices.extend(messages)

    previous_design = saved.get(DESIGN) if isinstance(saved, dict) else None
    if draft is None:
        pdf_layout = PDF_LAYOUT_C_REVISED if week["mode"] == "build" else PDF_LAYOUT_C
        page_layout = PAGE_LAYOUT_A
    else:
        pdf_layout = saved_pdf_layout(previous_design)
        page_layout = previous_design.get("page_layout") if isinstance(previous_design, dict) else None
        if page_layout != PAGE_LAYOUT_A:
            page_layout = None
    design, pdf_notices = with_pdf_paper(
        replace(design, page_layout=page_layout), args.pdf_paper or project.get("pdf_paper"), layout=pdf_layout,
    )
    return design, [*notices, *pdf_notices], choice


def prepare(files, args, *, secret_check):
    meeting_date = iso_date(args.date, "meeting_date")
    project = read_project(files)
    require_running_project(files)
    build = project["mode"] == "build"
    number, previous, draft = meeting_slot(
        files, recorded_message="This week is recorded. Use record to change the answers.",
    )
    language = draft.get("language", "en") if draft else project["language"]
    if not build and read_approved_prd(files) is not None:
        # Approval can stale an unconfirmed docs page while its week still needs closing.
        if draft is None or draft["mode"] != "docs" or draft.get("owner_confirmed_on"):
            raise Refusal("The PRD is approved. Run enter-build before preparing the next meeting.")
        if meeting_date != draft["meeting_date"]:
            raise Refusal(f'The PRD is approved. Prepare week {number} again with its saved date '
                          f'({draft["meeting_date"]}).')
    validate_meeting_order(meeting_date, previous)
    week = {
        "number": number,
        "meeting_date": meeting_date,
        "held": False,
        "mode": project["mode"],
    }
    if build:
        week["end_before"] = previous_delivery_date(project, previous)
    if language == "ar":
        week["language"] = language
    week["owner_confirmed_on"] = ""
    last_held_number, missed_dates = preceding_meetings(files, number)
    last_held = read_week(files, last_held_number) if last_held_number else None
    results = promise_results(files, number, last_held_number)
    content, digests = read_content(
        files, draft_path(files, args.content), mode=project["mode"], language=language,
        allowed_latin=meeting_names(project), secret_check=secret_check,
    )
    earlier = carry_needs(files, content, last_held)
    shown_screens, picture_warnings = [], []
    if build:
        last_held_date = last_held["meeting_date"] if last_held else None
        screens, pictures, picture_warnings = screen_snapshot(files, content, earlier, last_held_date)
        if screens:
            content["meeting_screens"] = screens
        shown_screens = screen_map(files, content, prepared_pictures=pictures)
    else:
        carry_decisions(content, earlier, last_held)
    saved = files.read_json(content_file(number), optional=True) if draft is not None else None
    corrections = correction_snapshot(files, number, draft, saved, content)
    for key, rows in (("meeting_promises", results), ("missed_meetings", missed_dates), ("corrections", corrections)):
        if rows:
            content[key] = rows
    # Include the evidence snapshot in the page fingerprint so edits to it are detected.
    content["source_digests"] = digests
    design, notices, choice = prepare_appearance(files, args, project, draft, saved, week, language)
    content[DESIGN] = design.snapshot
    design_messages = new_design_notices(content, saved, notices)
    waiting = waiting_changes(files) if build else []
    view = MeetingView(project_for_week(project, week), week, content, waiting, digests,
                       screen_map=shown_screens, design=design)
    validate_meeting_pdf_text(view)
    html = render_html(view)
    # Clear the old confirmation before replacing any part of the draft.
    saved_content = dict(content, meeting_changes=waiting) if build else content
    writes = [
        *weekly_ignore_writes(files),
        *design.assets.items(),
        (week_file(number), json_text(week)),
        (content_file(number), json_text(saved_content)),
        (page_file(number), html),
    ]
    updated = dict(project)
    if args.pdf_paper is not None:
        updated["pdf_paper"] = args.pdf_paper
    if choice is not None:
        updated[COLOR_CHOICE] = choice
    if updated != project:
        writes.append((PROJECT_FILE, json_text(updated)))
    retire = [pdf_file(number), legacy_copy_file(number)]
    warn_draft = False
    if build:
        warned_draft = files.write_path(SCOPE_DRAFT_NOTICE).is_file()
        if prd_is_draft(files):
            if not warned_draft:
                warn_draft = True
                writes.append((SCOPE_DRAFT_NOTICE, json_text(True)))
        elif warned_draft:
            retire.append(SCOPE_DRAFT_NOTICE)
    write_transaction(files, writes, retire=retire)
    messages = [f"Prepared {page_file(number).as_posix()}. Show the page to the owner.",
                *picture_warnings, *design_messages]
    if warn_draft:
        messages.insert(0, "The scope document is a Draft again. The existing delivery date stays.")
    warned = isinstance(saved, dict) and saved.get("prior_needs_unavailable") is True
    if content.get("prior_needs_unavailable") and not warned:
        messages.insert(0, "The last meeting's needs could not be read. "
                        "Ask the owner what the client still needs to provide.")
    warned_decisions = isinstance(saved, dict) and saved.get("prior_decisions_unavailable") is True
    if content.get("prior_decisions_unavailable") and not warned_decisions:
        messages.insert(0, OPEN_DECISIONS_UNAVAILABLE)
    return messages


def no_meeting(files, args):
    meeting_date = iso_date(args.date, "meeting_date")
    today = date.today().isoformat()
    if meeting_date > today:
        raise Refusal("The meeting date is in the future. Use a date through today to record a missed meeting.")
    project = read_project(files)
    number, previous, draft = meeting_slot(
        files, recorded_message="This week is recorded. Lock it before recording a missed meeting.",
    )
    validate_meeting_order(meeting_date, previous)
    week = {"number": number, "meeting_date": meeting_date, "held": False, "mode": project["mode"]}
    language = draft.get("language", "en") if draft else project["language"]
    if language == "ar":
        week["language"] = language
    if project["mode"] == "build":
        delivery_date = previous_delivery_date(project, previous)
        week.update(end_before=delivery_date, end_after=delivery_date)
    week["locked_on"] = today
    retire = (page_file(number), content_file(number), pdf_file(number), legacy_copy_file(number)) if draft else ()
    write_transaction(files, [(week_file(number), json_text(week))], retire=retire)
    return [f"No meeting was held on {meeting_date}. Locked week {number}."]


def current_week(files):
    number = newest_number(files)
    if not number:
        raise Refusal("Prepare a meeting first.")
    return read_week(files, number)


def matching_page_view(actual, view, *, recover_fonts=False):
    content = view.content
    carryover_versions = (False, True) if content.get("missed_meetings") or content.get("corrections") else (False,)
    font_versions = (False, True) if not view.is_docs and DESIGN not in content else (False,)
    raw = actual
    restored_roles = {role for role, meta in view.design.fonts.items()
                      if frozen_font_path(meta["digest"]) in view.design.assets}
    missing_roles = set(view.design.missing_roles)
    marked_roles = set()
    if recover_fonts:
        actual, marked_roles = saved_font_fallback(actual)
        if any(role not in view.design.fonts or view.design.fonts[role]["source"] != "project"
               for role in marked_roles):
            return None
    masked = dict.fromkeys((restored_roles | missing_roles) - marked_roles, b"")
    marked_payloads = {role: b64encode(studio_fonts(view.design.language)[1][role]) for role in marked_roles}
    for legacy_fonts in font_versions:
        for legacy_dates in carryover_versions:
            candidate = replace(view, legacy_carryover_dates=legacy_dates, legacy_build_fonts=legacy_fonts)
            markup = render_html(candidate, legacy_build_fonts=legacy_fonts)
            expected = markup.encode("utf-8")
            if raw == expected:
                return candidate
            if not (masked or marked_payloads):
                continue
            expected = replace_font_payloads(expected, {**masked, **marked_payloads})
            if replace_font_payloads(actual, masked) == expected:
                if not missing_roles:
                    return replace(candidate, restored_page=markup)
                if restored_roles - marked_roles:
                    payloads = {role: b64encode(view.design.font_data[role])
                                for role in restored_roles - marked_roles}
                    repaired = replace_font_payloads(raw, payloads)
                    if repaired != raw:
                        return replace(candidate, restored_page=repaired.decode("utf-8"))
                return candidate
    return None


def fresh_view(files, week, *, check_live_proof=False, for_record=False,
               allow_missing_page=False, snapshot_only=False, recover_fonts=False):
    remake = "Prepare the meeting again and show the page to the owner."
    if week["held"]:
        remake = "Restore the files that match the confirmed meeting page."
    try:
        project = project_for_week(read_project(files), week)
        number = week["number"]
        check_live_proof = check_live_proof or not (week.get("owner_confirmed_on") or snapshot_only)
        content, digests = read_content(
            files, content_file(number), saved=True, mode=week["mode"], language=project["language"],
            allowed_latin=meeting_names(project), check_live_proof=check_live_proof,
        )
        changes, changes_match = [], True
        if week["mode"] == "build":
            changes = validate_changes(content.pop("meeting_changes"))
            if any(row["status"] != "waiting" or row.get("days_added") is None for row in changes):
                raise Refusal("Check the saved decision list for this meeting.")
            if for_record:
                # Compare only the decisions shown, keeping their original order in the view.
                shown = {row["id"]: row for row in changes}
                waiting = waiting_changes(files, only_ids=shown)
                changes_match = {row["id"]: row for row in waiting} == shown
            else:
                changes_match = snapshot_only or week["held"] or waiting_changes(files) == changes
        if changes_match:
            relative = page_file(number)
            design = load_design(files, content.get(DESIGN), language=project["language"],
                                 recover_fonts=recover_fonts, page=relative)
            deciders = (recorded_change_deciders(read_changes(files), week)
                        if week["mode"] == "build" and week.get("answers") else {})
            view = MeetingView(project, week, content, changes, digests,
                               screen_map=screen_map(files, content), design=design, build_deciders=deciders)
            if week["held"]:
                check_recorded_totals(view)
            path = files.path(page_file(number))
            if design.assets or design.missing_roles:
                path = files.write_path(relative)
            if not path.exists() and not path.is_symlink():
                if allow_missing_page or design.missing_roles:
                    return view
                if design.assets:
                    return replace(view, restored_page=render_html(view))
            if path.is_file():
                matched = matching_page_view(path.read_bytes(), view, recover_fonts=recover_fonts)
                if matched is not None:
                    return matched
    except Refusal as error:
        raise Refusal(*error.messages, remake) from None
    except OSError:
        pass
    raise Refusal("The meeting page does not match the current files.", remake)


def confirm(files, _args):
    week = current_week(files)
    require_meeting(week)
    if week.get("locked_on"):
        raise Refusal("This week is locked. Prepare the next meeting.")
    view = fresh_view(files, week, check_live_proof=True)
    require_screen_checks(files, view.content)
    if not week.get("owner_confirmed_on"):
        number = week["number"]
        last_held, _ = preceding_meetings(files, number)
        if promise_results(files, number, last_held) != view.content.get("meeting_promises", []):
            raise Refusal("Promise results changed. Prepare the meeting again before confirming it.")
        if (not view.content.get("corrections_frozen")
                and pending_corrections(files, number) != view.content.get("corrections", [])):
            raise Refusal("Corrections changed. Prepare the meeting again before confirming it.")
    week["owner_confirmed_on"] = date.today().isoformat()
    number = week["number"]
    files.write_json(week_file(number), week)
    return [f"Recorded the owner's confirmation for week {number}."]


def confirmed_view(files, week, *, for_record=False, allow_missing_page=False, recover_fonts=False):
    require_meeting(week)
    if not week.get("owner_confirmed_on"):
        raise Refusal("Get the owner's confirmation on the meeting page first.")
    iso_date(week["owner_confirmed_on"], "owner_confirmed_on")
    return fresh_view(files, week, for_record=for_record, allow_missing_page=allow_missing_page,
                      recover_fonts=recover_fonts)


def meeting_names(project):
    return (project["project"], project["client"], *project["attendees"])
