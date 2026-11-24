"""Screen map captions shared by the page and the PDF."""

from collections import Counter
from datetime import date

from .meeting_language import translate
from .page import format_date


STATE_LABELS = {
    "finished": "Finished",
    "being built": "We are here",
    "not built": "Not built yet",
}
COUNT_LABELS = {
    "finished": "Finished",
    "being built": "Being built",
    "not built": "Not built",
}
APP_NOT_RUN = "The app could not be run for this meeting. Screenshots show their real dates."


def app_notice(view):
    return translate(getattr(view, "language", "en"), APP_NOT_RUN) if view.content.get("app_ran") is False else ""


def state_label(state, language="en"):
    return translate(language, STATE_LABELS[state])


def screen_counts(view):
    counts = Counter(row["state"] for row in view.screen_map)
    language = getattr(view, "language", "en")
    return [(counts[state], translate(language, label)) for state, label in COUNT_LABELS.items()]


def empty_screen_text(row, language="en"):
    if row["state"] == "not built":
        return translate(language, "No design is available.")
    return translate(language, "No screenshot is available.")


def picture_slots(row):
    if row["previous"] is None:
        return [] if row["current"] is None else [("", row["current"])]
    current = [("Current", row["current"])] if row["current"] is not None else []
    return [("Earlier", row["previous"]), *current]


def picture_caption(row, picture, language="en"):
    """Return the text before the date and the formatted date, if any."""
    if picture["removed"]:
        return picture["removed"], None
    if picture.get("unavailable"):
        return translate(language, "The picture is no longer available."), None
    if picture["kind"] == "design":
        if row["state"] == "not built":
            return translate(language, "Design"), None
        return translate(language, "Design · Not built yet"), None
    taken = date.fromisoformat(picture["taken_on"])
    return translate(language, "Taken on"), format_date(taken, None, language)


def new_picture(view, picture, position):
    return (position != "Earlier" and view.content.get("app_ran") is True
            and picture["kind"] == "screenshot" and not picture["removed"] and picture["new"])
