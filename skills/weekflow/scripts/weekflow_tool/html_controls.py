"""Shared offline meeting controls and text rendering."""

from datetime import date
from functools import partial
from html import escape

from .carryover_text import carryover_sections, missed_meeting_notices
from .meeting_language import translate
from .page import HEADINGS, NO_NEEDS, NO_NEXT_WEEK, format_date
from .text_fields import one_line


def safe(value):
    return escape(one_line(value), quote=True)


def date_text(value, meeting_year, language="en"):
    day = date.fromisoformat(value)
    return f'<time datetime="{day.isoformat()}">{format_date(day, meeting_year, language)}</time>'


def radio(group, identifier, value, label, *, detail=None):
    title = safe(label)
    if detail is not None:
        title = f'<strong class="answer-title">{title}</strong><small class="answer-impact">{detail}</small>'
    return (f'<label class="choice"><input type="radio" name="{group}" id="{identifier}" '
            f'value="{escape(value, quote=True)}"><span>{title}</span></label>')


def step_link(identifier, target, label, current=False):
    selected = ' aria-current="step"' if current else ""
    return (f'<a class="step-link" id="{identifier}" href="#panel-{target}" tabindex="0"{selected}>'
            f'{label}</a>')


def tab(index, label, *, layout_a=False):
    if layout_a:
        label = (f'<span class="step-marker" aria-hidden="true"><span>{index}</span></span>'
                 f'<span class="step-title">{label}</span>')
    link = step_link(f"step-{index}", index, label)
    current = step_link(f"current-step-{index}", index, label, current=True)
    return f'<div class="tab">{link}{current}</div>'


def tab_state_css(*, layout_a=False):
    for index in range(1, len(HEADINGS) + 1):
        active = f'.meeting-page:has(#panel-{index}:target)'
        if index == 1:
            active = f':is({active}, .meeting-page:not(:has(.panel:target)))'
        yield f'{active} #panel-{index} {{ display: {"flex" if layout_a else "block"}; }}'
        yield f'{active} #step-{index} {{ display: none; }}'
        yield f'{active} #current-step-{index} {{ display: {"inline-flex" if layout_a else "grid"}; }}'
        if layout_a and index > 1:
            done = f"{active} .tab:nth-child(-n+{index - 1})"
            yield f"{done} {{ --step-join: var(--color-main); }}"
            yield f"{done} .step-marker {{ background: var(--color-answer-tint); color: var(--color-answer-text); }}"
            yield f"{done} .step-marker span {{ display: none; }}"
            yield f'{done} .step-marker::after {{ content: "✓"; }}'


def item_list(items, empty, *, mark=""):
    if not items:
        return f'<p class="empty">{safe(empty)}</p>'
    classes = f"items checklist {mark}" if mark else "items"
    return f'<ul class="{classes}">' + "".join(f'<li class="card">{item}</li>' for item in items) + '</ul>'


def next_week(content, meeting_year, language="en", *, layout_a=False):
    label = partial(translate, language)
    upcoming = item_list([safe(item["text"]) for item in content["next_week"]], label(NO_NEXT_WEEK),
                         mark="upcoming" if layout_a else "")
    needs = []
    for item in content["needs"]:
        due = ""
        if "by" in item:
            due_text = label("Due {date}", date=date_text(item["by"], meeting_year, language))
            due = f'<span class="quiet">{due_text}</span>'
        needs.append(f'{safe(item["text"])}{due}')
    heading = label("What we need from the client")
    return f'{upcoming}<h3>{heading}</h3>{item_list(needs, label(NO_NEEDS))}'


def step_panel(index, body, language="en"):
    back_label, next_label, heading = (translate(language, text) for text in ("Back", "Next", HEADINGS[index - 1]))
    back = (step_link(f"back-{index}", index - 1, back_label) if index > 1
            else f'<button type="button" disabled>{back_label}</button>')
    forward = (step_link(f"next-{index}", index + 1, next_label) if index < len(HEADINGS)
               else f'<button type="button" disabled>{next_label}</button>')
    return (
        f'<section class="panel" id="panel-{index}" tabindex="-1" aria-labelledby="heading-{index}">'
        f'<h2 class="step-heading" id="heading-{index}">{heading}</h2>'
        f'{body}<div class="step-controls">{back}{forward}</div></section>'
    )

def carryover(view):
    yield from (f'<p class="quiet">{safe(notice)}</p>' for notice in missed_meeting_notices(view))


def carryover_cards(view):
    for heading, rows in carryover_sections(view):
        items = []
        for title, details in rows:
            detail_lines = "".join(f'<span class="quiet">{safe(detail)}</span>' for detail in details)
            items.append(f'<strong>{safe(title)}</strong>{detail_lines}')
        yield f'<h3>{safe(heading)}</h3>'
        yield item_list(items, "")
