"""Build-mode panels and delivery previews for the Layout A meeting page."""

from functools import partial

from .html_controls import date_text, radio, safe
from .meeting_language import translate
from .page import ANSWERS, NO_DECISIONS, day_count, project_details


def delivery_track(view):
    language, year = view.language, view.meeting.year
    label = partial(translate, language)
    offset = (view.end_before - view.meeting).days
    today_first = ' data-today-first' if offset >= 0 else ''
    # The CSS counter supplies the Arabic text, so <bdi> cannot detect its direction.
    direction = ' dir="rtl"' if language == "ar" else ''
    now = label("now, {days}", days=f'<bdi{direction}>+<span class="live-total"></span></bdi>')
    return (
        f'<div class="delivery-track" role="group" aria-label="{label("Delivery date")}" '
        f'style="--plan-from-meeting: {offset}"{today_first}>'
        f'<p class="track-title">{label("Delivery date")}</p><div class="track-axis">'
        '<span class="track-break" aria-hidden="true"></span>'
        '<span class="track-move" aria-hidden="true"></span>'
        '<span class="track-dot dot-today" aria-hidden="true"></span>'
        '<span class="track-dot dot-plan" aria-hidden="true"></span>'
        '<span class="track-dot dot-now" aria-hidden="true"></span>'
        f'<span class="track-label label-today"><strong>{date_text(view.meeting.isoformat(), year, language)}</strong>'
        f'<small>{label("today")}</small></span>'
        f'<span class="track-label label-plan"><strong>{date_text(view.end_before.isoformat(), year, language)}</strong>'
        f'<small class="track-planned">{label("planned")}</small>'
        f'<small class="track-on-time">{label("on time")}</small></span>'
        '<span class="track-label label-now"><strong class="live-date"></strong>'
        f'<small>{now}</small></span></div></div>'
    )


def where_we_are(view):
    label = partial(translate, view.language)
    content = view.content
    details = " · ".join(safe(detail) for detail in project_details(view.project, view.language))
    people = f'<p class="quiet meeting-people">{details}</p>' if details else ""
    counts = tuple((label(title), count) for title, count in (
        ("Finished items", len(content["finished"])), ("Decisions", len(view.changes)),
        ("Things we need", len(content["needs"])),
    ))
    return (f'<h1>{safe(content["headline"])}</h1>{people}{delivery_track(view)}<dl class="counts">'
            + "".join(f'<div><dt>{title}</dt><dd>{count}</dd></div>' for title, count in counts)
            + '</dl>')


def decision_cards(view, day_overflow):
    label = partial(translate, view.language)
    if not view.changes:
        return f'<p class="empty">{label(NO_DECISIONS)}</p>{delivery_track(view)}'
    instruction = label("Try an answer to see how the delivery date changes.")
    year = view.meeting.year
    lines = [f'<p class="decision-instruction">{instruction}</p>']
    for number, change in enumerate(view.changes, 1):
        group = f"decision-{number}"
        title = safe(change["what"])
        raised = label("Raised by {name} on {date}.", name=safe(change["asked_by"]),
                       date=date_text(change["date"], year, view.language))
        days = change["days_added"]
        options = []
        for answer, answer_title in ANSWERS:
            effect = days if answer == "yes" else 0
            difference = f'<bdi>+{day_count(effect, view.language)}</bdi>' if effect else label("no change")
            preview = f'calc(var(--through-{len(view.changes)}) - var(--days-{number}) + {min(effect, day_overflow)})'
            detail = f'{difference} · <span class="live-date" style="--added: {preview}"></span>'
            options.append(radio(group, f"{group}-{answer}", answer, label(answer_title), detail=detail))
        lines.extend((
            '<article class="card decision">',
            f'<bdi class="decision-id">{safe(change["id"])}</bdi>',
            f'<h3>{title}</h3><p>{safe(change["reason"])}</p>',
            f'<p class="quiet">{raised} · {day_count(days, view.language)}</p>',
            f'<fieldset class="answers" id="{group}" data-change-id="{change["id"]}" aria-label="{title}">',
            *options, '</fieldset></article>', delivery_track(view),
        ))
    return "\n".join(lines)
