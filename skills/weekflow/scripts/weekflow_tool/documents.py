"""Read setup facts from the project documents."""

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from .storage import Refusal
from .text_fields import arabic_words


APPROVED_STAMP = re.compile(r">\s+v[0-9]+\s*·\s+Approved\b")
APPROVAL_DATE = r" ([0-9]{4}-[0-9]{2}-[0-9]{2})"
APPROVAL_DETAILS = re.compile(APPROVAL_DATE + r"(?: by .+)?\s*")
DRAFT_STAMP = re.compile(r">\s+v[0-9]+\s*·\s+Draft\s*")
ARABIC_APPROVED_STAMP = re.compile(r">\s+الاصدار [0-9]+\s*·\s+معتمد\b")
ARABIC_APPROVAL_DETAILS = re.compile(APPROVAL_DATE + r"(?: من .+)?\s*")
ARABIC_DRAFT_STAMP = re.compile(r">\s+الاصدار [0-9]+\s*·\s+مسوده\s*")
APPROVAL_CANDIDATE = re.compile(
    r"\s*(?:>\s*)?(?:v|الاصدار\s+)[0-9]+(?:\.[0-9]+)*"
    r"\s*(?:[·–—:-]\s*)?(?:Approved|معتمد)\b",
    re.IGNORECASE,
)
ARABIC_PRD_TITLE = "متطلبات المنتج (PRD)"
ARABIC_FORM_TITLE = "نموذج اجتماع العميل"
ARABIC_MEETINGS = arabic_words("الاجتماعات التي عُقدت")
ARABIC_OPEN = arabic_words("ما زال مفتوحًا")
ARABIC_DECISION = "10. القرار"
PROJECT_DOCS = ("docs/prd.md", "docs/meeting-form.md", "docs/scope.md", "docs/trd.md",
                "DESIGN.md", "docs/data.md", "docs/security.md", "docs/handover.md",
                "docs/plan.md")
HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$")
DATES_LINE = re.compile(r"^([ \t]*)-[ \t]+\*\*Dates:\*\*[ \t]*(.*)$")
ARABIC_DATES_LINE = re.compile(r"^([ \t]*)-[ \t]+\*\*المواعيد:\*\*[ \t]*(.*)$")
DATE_WORD = re.compile(r"(?<![0-9])[0-9]{4}-[0-9]{2}-[0-9]{2}(?![0-9])")
CHANGED_ITEM = re.compile(r"^[ \t]+-[ \t]+Changed\b(.*)$")
ARABIC_CHANGED_ITEM = re.compile(r"^[ \t]+-[ \t]+تغير في\b(.*)$")
CHANGED_STAMP = re.compile(r"[ \t]+([0-9]{4}-[0-9]{2}-[0-9]{2}):[ \t]*(.*)")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
HISTORY = re.compile(r"^\s*<details\b[^>]*\bdata-[\w-]+-history\b[^>]*>")
END_DATE_NAME = r"(?:(?:end|delivery|launch|release|finish|completion) date|deadline)"
UNSET_END = re.compile(
    rf"\b(?:TBD|to be determined|undecided)\b"
    rf"|\bno\s+(?:(?:planned|agreed|target|fixed)\s+)?(?:{END_DATE_NAME}|date)\b"
    rf"|\b{END_DATE_NAME}\s+(?:is\s+)?(?:unknown|not\s+(?:set|agreed|confirmed))\b",
    re.IGNORECASE,
)
START_BEFORE_DATE = re.compile(
    r"\b(?:start(?:ing)? date|(?:work|build|development|project)\s+(?:starts?|begins?))"
    r"\s*(?:(?:is|on)\s+|:\s*)?[`*]*$",
    re.IGNORECASE,
)
ARABIC_UNSET_END = re.compile(
    r"\b(?:لم (?:يحسم|يحدد|يتحدد|يعتمد|يتفق)|غير (?:محسوم|محدد|موكد|مقرر|معروف|متفق عليه)|"
    r"بلا موعد|لا (?:يوجد )?(?:موعد|تاريخ))\b"
)
ARABIC_START_BEFORE_DATE = re.compile(
    r"\b(?:(?:(?:موعد|تاريخ)\s+)?(?:البدء|بدايه|بدء|انطلاق)|"
    r"(?:(?:العمل|البناء|التنفيذ|المشروع)\s+)?(?:يبدا|ينطلق))"
    r"(?:\s+(?:العمل|البناء|التنفيذ|المشروع|في|يوم|بتاريخ|من))*\s*[:`*]*\s*$"
)


@dataclass(frozen=True)
class DatedLine:
    value: str
    number: int
    source: str


@dataclass(frozen=True)
class ApprovedPrd:
    project: str
    scope_approved_on: str
    planned_end: Optional[DatedLine]
    approval_note: str = ""


@dataclass(frozen=True)
class MeetingForm:
    client: str
    attendees: list[str]
    last_number: int
    project: str = ""
    exists: bool = False
    latest_stage: int = 0
    stage_meetings: dict[int, int] = field(default_factory=dict)
    still_open: tuple[str, ...] = ()
    stopped: bool = False


def _calendar_date(value: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return ""


def _markdown_lines(text):
    return [line.removesuffix("\r") for line in text.split("\n")]


def _current_lines(lines):
    in_history = False
    fence = ""
    for number, line in enumerate(lines, start=1):
        marker = FENCE.fullmatch(line)
        if fence:
            if marker and marker[1].startswith(fence) and not marker[2].strip():
                fence = ""
        elif in_history or HISTORY.match(line):
            in_history = "</details>" not in line
        elif marker:
            fence = marker[1]
        else:
            yield number, line


def _changed_value(body, *, arabic=False):
    if arabic:
        move = re.fullmatch(r"من (.+?) الي (.+?)[،,]\s+لان (.+)", body)
        return move[2].strip() if move else ""
    move, separator, reason = body.partition(", because ")
    previous, arrow, current = move.partition("→")
    if separator and reason.strip() and arrow and previous.strip() and "→" not in current:
        return current.strip()
    return ""


def _planned_end(lines) -> Optional[DatedLine]:
    visible = list(_current_lines(lines))
    dates = []
    for index, (_, line) in enumerate(visible):
        if match := DATES_LINE.fullmatch(line):
            dates.append((index, match, False))
        elif match := ARABIC_DATES_LINE.fullmatch(arabic_words(line)):
            dates.append((index, match, True))
    if len(dates) != 1:
        return None

    index, dates_line, arabic = dates[0]
    number, source = visible[index]
    base_indent = len(dates_line[1].expandtabs(4))
    value = dates_line[2]
    last_line = number
    changes = []
    for changed_number, line in visible[index + 1:]:
        if changed_number != last_line + 1:
            break
        last_line = changed_number
        if not line.strip():
            continue
        expanded = line.expandtabs(4)
        indent = len(expanded) - len(expanded.lstrip())
        if indent <= base_indent:
            break
        item = ARABIC_CHANGED_ITEM.fullmatch(arabic_words(line)) if arabic else CHANGED_ITEM.fullmatch(line)
        if item:
            stamp = CHANGED_STAMP.fullmatch(item[1])
            if not stamp or not _calendar_date(stamp[1]):
                return None
            changes.append((stamp[1], changed_number, stamp[2], line))
    if changes:
        _, number, body, source = max(changes)
        value = _changed_value(body, arabic=arabic)

    if UNSET_END.search(value) or arabic and ARABIC_UNSET_END.search(value):
        return None
    candidates = list(DATE_WORD.finditer(value))
    if len(candidates) != 1:
        return None
    preceding = value[:candidates[0].start()]
    if START_BEFORE_DATE.search(preceding) or arabic and ARABIC_START_BEFORE_DATE.search(preceding):
        return None
    planned = _calendar_date(candidates[0][0])
    return DatedLine(planned, number, source) if planned else None


def _prd_lines(files):
    return _markdown_lines(files.read_text("docs/prd.md", optional=True) or "")


def prd_is_draft(files):
    lines = _prd_lines(files)
    return len(lines) > 1 and bool(DRAFT_STAMP.fullmatch(lines[1]) or
                                   ARABIC_DRAFT_STAMP.fullmatch(arabic_words(lines[1])))


def _project_title(line, *prefixes):
    title = HEADING.fullmatch(line)
    if title and title[1] == "#":
        prefix = "|".join(re.escape(value) for value in prefixes)
        return re.sub(rf"^(?:{prefix})\s*:\s*", "", title[2], flags=re.IGNORECASE).strip()
    return ""


def read_project_name(files, form):
    project = _project_title(_prd_lines(files)[0], "PRD", ARABIC_PRD_TITLE) or form.project
    if project:
        return project
    for source, prefix in (("docs/plan.md", "Plan"), ("docs/scope.md", "Scope")):
        lines = _markdown_lines(files.read_text(source, optional=True) or "")
        project = _project_title(lines[0], prefix)
        if project:
            return project
    return ""


def has_project_docs(files):
    return any(files.path(source).is_file() for source in PROJECT_DOCS)


def _split_approval_note(line: str) -> tuple[str, str]:
    stamp = line.rstrip()
    if not stamp.endswith(")"):
        return stamp, ""
    depth = 0
    for index in range(len(stamp) - 1, 0, -1):
        if stamp[index] == ")":
            depth += 1
        elif stamp[index] == "(":
            depth -= 1
            if depth == 0:
                if stamp[index - 1].isspace():
                    return stamp[:index].rstrip(), stamp[index:]
                break
    return stamp, ""


def read_approved_prd(files) -> Optional[ApprovedPrd]:
    lines = _prd_lines(files)
    number, line = next(((number, line) for number, line in enumerate(lines[1:], start=2)
                         if line.strip()), (2, ""))
    prefix = APPROVED_STAMP.match(line)
    details_pattern = APPROVAL_DETAILS
    arabic = not prefix
    normalized = line
    if not prefix:
        normalized = arabic_words(line)
        prefix = ARABIC_APPROVED_STAMP.match(normalized)
        details_pattern = ARABIC_APPROVAL_DETAILS
    if not prefix and not APPROVAL_CANDIDATE.match(normalized):
        return None
    if number != 2:
        raise Refusal(f"Move the PRD approval stamp at docs/prd.md:{number} directly below the title on line 2.")
    if not prefix:
        raise Refusal(f"Fix the format of the PRD approval stamp at docs/prd.md:{number}.")

    # Keep the source note intact when normalizing the Arabic stamp.
    stamp, note = _split_approval_note(line)
    details = details_pattern.fullmatch(arabic_words(stamp) if arabic else stamp, prefix.end())
    if not details and note:
        # A parenthesized approver can be part of a legacy stamp.
        details = details_pattern.fullmatch(normalized, prefix.end())
        note = ""
    approved_on = _calendar_date(details[1]) if details else ""
    if not approved_on:
        raise Refusal(f"Use a real approval date in YYYY-MM-DD format on docs/prd.md:{number}.")
    return ApprovedPrd(_project_title(lines[0], "PRD", ARABIC_PRD_TITLE), approved_on, _planned_end(lines), note)


def _table_cells(line: str) -> list[str]:
    line = line.strip()
    if not line.startswith("|"):
        return []
    cells = re.split(r"(?<!\\)\|", line)[1:]
    if cells and cells[-1] == "":
        cells.pop()
    return [cell.replace(r"\|", "|").strip() for cell in cells]


def _meeting_stages(value, *, arabic=False):
    if arabic:
        value = arabic_words(value).replace("،", ",")
        value = re.sub(r"^1\s+و\s*2$", "1, 2", value)
    parts = [part.strip() for part in value.split(",")]
    if parts == ["1", "2"] or (len(parts) == 1 and parts[0] in ("1", "2", "3", "4")):
        return {int(part) for part in parts}
    return set()


UNMARKED = {"", "-", "–", "—", "☐", "[ ]", "no"}
ARABIC_UNMARKED = UNMARKED | {"لا", "لم يحسم", "لم يحسم بعد"}
STOP_NOTE = re.compile(r"^stop(?:ped)?(?:[.!]?$|\s*[:—–-])", re.IGNORECASE)
ARABIC_STOP_NOTE = re.compile(r"^(?:توقف|ايقاف|توقف المشروع)(?:[.!؟]?$|\s*[:—–-])")
TABLE_SEPARATOR = re.compile(r":?-{3,}:?")


def read_meeting_form(files) -> MeetingForm:
    text = files.read_text("docs/meeting-form.md", optional=True)
    if text is None:
        return MeetingForm("", [], 0)

    lines = _markdown_lines(text)
    client = ""
    attendees = []
    last_number = 0
    stage_meetings = {}
    still_open = []
    stage_four_result = None
    current_stopped = None
    section = subsection = ""
    for _, line in _current_lines(lines):
        heading = HEADING.fullmatch(line)
        if heading and len(heading[1]) <= 2:
            section, subsection = heading[2], ""
        elif heading and len(heading[1]) == 3:
            subsection = heading[2]

        cells = _table_cells(line)
        if len(cells) < 2:
            continue
        if cells[0] in ("Client (organisation, department)", "العميل (الجهة، القسم)") and not client:
            client = cells[1]
        section_words = arabic_words(section)
        arabic_meetings = section_words == ARABIC_MEETINGS
        number_label = arabic_words(cells[0]) if arabic_meetings else cells[0]
        if ((section == "Meetings held" or arabic_meetings) and len(cells) >= 4
                and re.fullmatch(r"[0-9]+", number_label)):
            number = int(number_label)
            if number > last_number:
                last_number = number
                people = re.split(r"[;؛]", cells[3]) if arabic_meetings else cells[3].split(";")
                attendees = [person.strip() for person in people if person.strip()]
            for stage in _meeting_stages(cells[2], arabic=arabic_meetings):
                if number > stage_meetings.get(stage, 0):
                    stage_meetings[stage] = number
                    if stage == 4:
                        stage_four_result = cells[4] if len(cells) >= 5 else ""
        if ((section == "Still open" or section_words == ARABIC_OPEN) and cells[1]
                and cells[:2] not in (["#", "Question"], ["#", "السؤال"])
                and not TABLE_SEPARATOR.fullmatch(cells[1])):
            still_open.append(cells[1])
        if "10. The decision" in (section, subsection) and cells[1].casefold() not in UNMARKED:
            if cells[0].casefold().startswith("stop"):
                current_stopped = True
            elif cells[0] == "Approved" or cells[0].startswith("Changes first"):
                if current_stopped is None:
                    current_stopped = False
        if ARABIC_DECISION in (section_words, arabic_words(subsection)):
            selection = arabic_words(cells[0])
            if arabic_words(cells[1]) not in ARABIC_UNMARKED:
                if re.match(r"^توقف\b", selection):
                    current_stopped = True
                elif current_stopped is None and (selection == "معتمد" or selection.startswith("تعديلات اولا")):
                    current_stopped = False

    result = stage_four_result or ""
    stopped = bool(STOP_NOTE.match(result) or ARABIC_STOP_NOTE.match(arabic_words(result)))
    if current_stopped is not None:
        stopped = current_stopped
    return MeetingForm(client, attendees, last_number, _project_title(lines[0], "Client meeting form", ARABIC_FORM_TITLE),
                       True, max(stage_meetings, default=0), stage_meetings, tuple(still_open), stopped)
