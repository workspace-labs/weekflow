"""Give both copies the same words for carried-over meeting facts."""

from datetime import date

from .meeting_language import translate


def carryover_date(view, value):
    if view.legacy_carryover_dates and view.language == "en":
        return value
    return view.date_text(date.fromisoformat(value))


def missed_meeting_notices(view):
    for meeting_date in view.content.get("missed_meetings", ()):
        yield translate(view.language, "No meeting was held on {date}.", date=carryover_date(view, meeting_date))


def carryover_sections(view):
    content = view.content
    promises = content.get("meeting_promises")
    if promises:
        rows = []
        for promise in promises:
            details = [translate(view.language, promise["status"].capitalize())]
            if "note" in promise:
                details.append(promise["note"])
            rows.append((promise["what"], details))
        yield translate(view.language, "What we promised last week"), rows

    corrections = content.get("corrections")
    if corrections:
        rows = []
        for correction in corrections:
            kind = correction["kind"].capitalize()
            correction_date = carryover_date(view, correction["date"])
            notice = translate(view.language, f"{kind} for week {{week}} on {{date}}.",
                               week=correction["week"], date=correction_date)
            reason = translate(view.language, "Reason given by {name} · {reason}",
                               name=correction["by"], reason=correction["reason"])
            rows.append((correction["what"], (notice, reason)))
        yield translate(view.language, "Corrections and removals"), rows
