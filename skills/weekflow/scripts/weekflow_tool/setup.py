"""Start the weekly record once the required facts are known."""

from .documents import has_project_docs, read_approved_prd, read_meeting_form, read_project_name
from .meeting_design import prepare_design
from .pdf_text import DISPLAY, validate_pdf_text
from .screens import ensure_weekly_ignores
from .storage import Refusal, iso_date
from .text_fields import one_line


PROJECT_FILE = "docs/weekly/project.json"


def project_text_design(files, project=None):
    """Resolve the current Arabic fonts for inputs saved before a meeting."""
    if project is None:
        project = files.read_json(PROJECT_FILE, optional=True)
    if isinstance(project, dict) and project.get("language") == "ar":
        return prepare_design(files, "ar")[0]
    return None


def build_dates(prd, supplied_end):
    """Get the delivery date used for build mode and report its source."""
    if supplied_end is not None:
        end = iso_date(supplied_end, "planned_end")
        return end, f"Used planned_end {end} supplied with --planned-end."
    if prd.planned_end is None:
        raise Refusal("Give the agreed date for planned_end in YYYY-MM-DD format with --planned-end.")
    planned = prd.planned_end
    return planned.value, (
        f"Read planned_end {planned.value} from docs/prd.md:{planned.number}. "
        f"PRD line reads \"{one_line(planned.source)}\""
    )


def scope_approval_message(prd):
    note = f" {prd.approval_note}" if prd.approval_note else ""
    return f"Read scope approval date {prd.scope_approved_on}{note} from docs/prd.md:2."


def start(files, args) -> list[str]:
    if files.path(PROJECT_FILE).exists():
        raise Refusal("Weekly meetings are already set up in docs/weekly/project.json.")

    prd = read_approved_prd(files)
    form = read_meeting_form(files)
    client = form.client if args.client is None else args.client
    attendees = form.attendees if args.attendee is None else args.attendee
    attendees = [name for person in attendees if (name := one_line(person))]
    has_docs = prd is not None or has_project_docs(files)
    project = prd.project if prd else read_project_name(files, form)
    if prd is None and not project:
        project = args.project_name or ""

    state = {
        "project": one_line(project),
        "client": one_line(client),
        "meeting_day": one_line(args.meeting_day or ""),
        "language": args.language or "",
        "attendees": attendees,
        "mode": "build" if prd else "docs",
        "scope_approved_on": prd.scope_approved_on if prd else "",
        "planned_end": "",
    }
    required = []
    if not state["project"]:
        required.append("Add the project name to the PRD title to supply project." if prd
                        else "Give the project name with --project.")
    if not state["meeting_day"]:
        required.append("Give the usual meeting day for meeting_day.")
    if not state["language"]:
        required.append("Choose en or ar for language.")
    date_message = ""
    if prd:
        try:
            state["planned_end"], date_message = build_dates(prd, args.planned_end)
        except Refusal as error:
            required.extend(error.messages)

    optional = [
        f"Ask the owner once about {name}, an optional field."
        for name in ("client", "attendees") if not state[name]
    ]
    if required:
        raise Refusal(*required, *optional)

    design = project_text_design(files, state)
    validate_pdf_text(state["project"], "project", DISPLAY, design=design)
    validate_pdf_text(state["client"], "client", design=design)
    for position, attendee in enumerate(attendees, 1):
        validate_pdf_text(attendee, f"attendees item {position}", design=design)
    files.write_path(PROJECT_FILE)
    ensure_weekly_ignores(files)
    files.write_json(PROJECT_FILE, state, new=True)
    messages = ["Weekly meetings are set up."]
    if not has_docs:
        messages.append("No project-docs files were found. Work from what the owner gives you.")
    if prd and prd.approval_note:
        messages.append(scope_approval_message(prd))
    if prd and args.planned_end is None:
        messages.append(date_message)
    if not prd:
        messages.append("Started in docs mode. Delivery date is set when the scope is approved.")
    return [*messages, *optional]
