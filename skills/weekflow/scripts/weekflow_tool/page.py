"""Meeting facts shared by the interactive page and client PDF."""

from dataclasses import dataclass, field
from datetime import date, timedelta
from hashlib import sha256
import json

from .meeting_language import ARABIC_MONTHS, arabic_days, translate
from .meeting_design import MeetingDesign, studio_design
from .storage import Refusal
from .text_fields import one_line


HEADINGS = ("Where we are", "See it", "Your decisions", "Next week", "What we agreed")
MONTHS = ("January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December")
NO_FINISHED = "No finished work is listed."
NO_DECISIONS = "No decisions are waiting."
NO_NEXT_WEEK = "No items are planned for next week."
NO_NEEDS = "Nothing is needed from the client."
MEETING_UNRECORDED = "Prepared for the meeting. No decisions are recorded."
ANSWERS = (("yes", "Yes, now"), ("later", "After launch"), ("no", "No"))
TABLE_HEADINGS = ("Decision", "Raised by", "Answer", "Days", "Delivery date")
PICTURE_REMOVAL_ANSWERS = "picture_removal_answers"
DOCS_LATER = "later"
DESIGN = "design"
DESIGN_NOTICES = "design_notices"


@dataclass(frozen=True)
class MeetingView:
    project: dict
    week: dict
    content: dict
    changes: list
    evidence: list
    legacy_carryover_dates: bool = False
    screen_map: list = field(default_factory=list)
    design: MeetingDesign = field(default_factory=studio_design)
    legacy_build_fonts: bool = False
    restored_page: str = None
    build_deciders: dict = field(default_factory=dict)

    @property
    def is_docs(self):
        return self.week["mode"] == "docs"

    @property
    def language(self):
        return self.project.get("language", "en")

    @property
    def meeting(self):
        return date.fromisoformat(self.week["meeting_date"])

    @property
    def end_before(self):
        return date.fromisoformat(self.week["end_before"])

    @property
    def end_after(self):
        return date.fromisoformat(self.week.get("end_after", self.week["end_before"]))

    @property
    def attendees(self):
        if self.week["held"]:
            return self.week["attendees"]
        return self.project["attendees"]

    @property
    def date_label(self):
        if self.week["end_before"] == self.project["planned_end"]:
            return translate(self.language, "Planned delivery date")
        return translate(self.language, "Delivery date so far")

    def date_text(self, value):
        return format_date(value, self.meeting.year, self.language)

    @property
    def fingerprint(self):
        return self._fingerprint(self.content)

    def _fingerprint(self, content):
        # An effective Studio snapshot keeps the original page and PDF receipts valid.
        keep_design = not self.design.is_studio or self.language == "ar"
        content = {key: value for key, value in content.items()
                   if key != DESIGN_NOTICES and (key != DESIGN or keep_design)}
        if DESIGN in content:
            content[DESIGN] = {key: value for key, value in content[DESIGN].items() if key != "pdf"}
        draft_fields = ("number", "meeting_date", "mode")
        project = self.project
        if self.is_docs:
            # Entering build adds scope and delivery dates to the live setup.
            project = {key: value for key, value in project.items()
                       if key not in {"mode", "scope_approved_on", "planned_end"}}
        else:
            draft_fields += ("end_before",)
        facts = {key: self.week[key] for key in draft_fields}
        inputs = (project, facts, content, self.changes, self.evidence)
        return sha256(json.dumps(inputs, sort_keys=True).encode("ascii")).hexdigest()

    def _fingerprint_without_answer_history(self):
        content = dict(self.content)
        content.pop(PICTURE_REMOVAL_ANSWERS, None)
        return self._fingerprint(content)

    @property
    def answer_fingerprints(self):
        history = self.content.get(PICTURE_REMOVAL_ANSWERS)
        if history and history["applies_to"] == self._fingerprint_without_answer_history():
            return (self.fingerprint, *history["previous"])
        return (self.fingerprint,)

    def answers_after_picture_removal(self, replacement):
        # Old downloads apply only to the exact facts produced by this removal.
        return {"applies_to": replacement._fingerprint_without_answer_history(),
                "previous": list(self.answer_fingerprints)}

    def running_decisions(self):
        selected = {entry["id"]: entry["answer"] for entry in self.week.get("answers", [])}
        running = self.end_before
        for change in self.changes:
            answer = selected.get(change["id"])
            days = charged_days(change, answer)
            running = move_date(running, days)
            yield change, answer, days, running

    def running_docs_decisions(self, answers=None):
        if answers is None:
            answers = {entry["id"]: entry["answer"] for entry in self.week.get("answers", [])}
        decisions = self.content["decisions"]
        remaining = len(decisions)
        for decision in decisions:
            answer = answers.get(decision["id"])
            if answer is not None and answer != DOCS_LATER:
                remaining -= 1
            yield decision, answer, remaining

    @property
    def decisions_left(self):
        remaining = 0
        for _, _, remaining in self.running_docs_decisions():
            pass
        return remaining


def charged_days(change, answer):
    return change["days_added"] if answer == "yes" else 0


def move_date(start, days):
    try:
        return start + timedelta(days=days)
    except OverflowError:
        raise Refusal("The agreed days move the delivery date beyond the calendar.") from None


def day_count(days, language="en"):
    if language == "ar":
        return arabic_days(days)
    return f"{days} day" if days == 1 else f"{days} days"


def meeting_label(number, language="en"):
    return translate(language, "Meeting {number}", number=number)


def format_date(value, meeting_year, language="en"):
    months = ARABIC_MONTHS if language == "ar" else MONTHS
    day = f"{value.day} {months[value.month - 1]}"
    return day if value.year == meeting_year and language != "ar" else f"{day} {value.year}"


def calendar_line(approval, end, meeting):
    if approval >= end or not approval <= meeting <= end:
        return None
    span = (end - approval).days
    offset = (meeting - approval).days
    weeks = (span + 6) // 7
    return min(offset // 7 + 1, weeks), weeks, offset


def project_details(project, language="en"):
    if project["client"]:
        yield translate(language, "Client: {name}", name=one_line(project["client"]))
    if project["attendees"]:
        separator = "، " if language == "ar" else ", "
        names = separator.join(one_line(person) for person in project["attendees"])
        yield translate(language, "Attendees: {names}", names=names)
