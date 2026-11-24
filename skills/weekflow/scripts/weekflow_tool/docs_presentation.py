"""Give both copies the same words for a docs meeting."""

from .docs_content import DECISION_MARKER
from .meeting_language import translate
from .page import DOCS_LATER


STAGES = ("The goal", "The people and today's work", "The needs and the new way", "The scope decision")
DOCS_TABLE_HEADINGS = ("Question", "Your answer", "Left to decide")
DECIDE_NEXT_WEEK = "Decide next week"
NOT_DECIDED = "Not decided"
NO_SENTENCES = "No document sentences are listed."
SCOPE_NOTE = "This record does not approve the scope."
DELIVERY_NOTE = "Delivery date is set when the scope is approved"
SETTLED_HEADING = "Settled outside the meeting"


def stage_steps(content, language="en"):
    current = content["stage"]
    held = content["stage_meetings"]
    for number, title in enumerate(STAGES, 1):
        meeting = held.get(str(number))
        if number == current:
            status = translate(language, "We are here")
        elif number < current and meeting:
            status = translate(language, "Held in meeting {meeting}", meeting=meeting)
        else:
            status = ""
        yield translate(language, title), status, number == current


def sentence_parts(text, replace_marker, literal=str):
    start = 0
    for marker in DECISION_MARKER.finditer(text):
        yield literal(text[start:marker.start()])
        yield replace_marker(marker[1])
        start = marker.end()
    yield literal(text[start:])


def docs_answer_label(answer, language="en"):
    if answer == DOCS_LATER:
        return translate(language, DECIDE_NEXT_WEEK)
    return answer or translate(language, NOT_DECIDED)


def inline_answer(answer, language="en"):
    if answer in (None, DOCS_LATER):
        return translate(language, NOT_DECIDED.lower())
    return answer
