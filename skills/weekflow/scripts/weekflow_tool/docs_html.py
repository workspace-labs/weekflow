"""Render the five docs panels and their native decision controls."""

from functools import partial
from html import escape
from pathlib import Path

from .docs_presentation import (
    DECIDE_NEXT_WEEK, DELIVERY_NOTE, DOCS_TABLE_HEADINGS, NOT_DECIDED, NO_SENTENCES, SCOPE_NOTE,
    SETTLED_HEADING, inline_answer, sentence_parts, stage_steps,
)
from .html_controls import carryover, carryover_cards, next_week, radio, safe
from .meeting_language import translate
from .page import DOCS_LATER, NO_DECISIONS, project_details
from .page_design import font_faces


def styles(decisions, design, language="en"):
    yield from font_faces(design, docs=True, language=language)
    stylesheet = Path(__file__).with_name("docs_page.css").read_text(encoding="utf-8")
    if design.is_studio:
        # Keep existing docs HTML valid for frozen meetings and saved answers.
        stylesheet = stylesheet.replace("var(--color-answer-tint)", design.answer_tint.lower())
        stylesheet = stylesheet.replace("var(--color-answer-text)", "var(--color-main)")
    yield stylesheet
    yield "body {"
    yield f"  --left-0: {len(decisions)};"
    for number in range(1, len(decisions) + 1):
        yield f"  --decided-{number}: 0;"
        yield f"  --left-{number}: calc(var(--left-{number - 1}) - var(--decided-{number}));"
    yield f"  --docs-left: var(--left-{len(decisions)});"
    yield "}"
    resolved = []
    for number, decision in enumerate(decisions, 1):
        control = f"docs-decision-{number}"
        resolved.append(f':has(#{control} input:checked:not([value="{DOCS_LATER}"]))')
        yield f"body{resolved[-1]} {{ --decided-{number}: 1; }}"
        for index, _ in enumerate(decision["options"], 1):
            active = f"body:has(#{control}-{index}:checked)"
            target = f".docs-answer-{number}"
            yield f"{active} {target} .docs-unset {{ display: none; }}"
            yield f"{active} {target} .docs-pick-{index} {{ display: inline; }}"
        defer = f"body:has(#{control}-later:checked) .docs-row-{number}"
        yield f"{defer} .docs-unset {{ display: none; }}"
        yield f"{defer} .docs-pick-later {{ display: inline; }}"
    complete = "body" + "".join(resolved)
    yield f"{complete} .docs-header .docs-count {{ display: none; }}"
    yield f"{complete} .docs-header .docs-complete {{ display: inline; }}"
    if design.page_layout == "a":
        yield Path(__file__).with_name("docs_page_a.css").read_text(encoding="utf-8")
        yield f"{complete} .docs-header .docs-count-label {{ display: none; }}"


def header_status(language="en", *, layout_a=False):
    label = partial(translate, language)
    if layout_a:
        return (
            '<output class="docs-header docs-header-a" aria-live="polite" aria-atomic="true">'
            f'<span class="quiet docs-count-label">{label("Left to decide")}</span> '
            '<strong><span class="docs-count"></span>'
            f'<span class="docs-complete">{label("All decided")}</span></strong></output>'
        )
    return (
        '<output class="docs-header" aria-live="polite" aria-atomic="true">'
        f'<span class="quiet">{label("Left to decide")}</span>'
        '<strong><span class="docs-count"></span>'
        f'<span class="docs-complete">{label("All decided")}</span></strong>'
        f'<span class="quiet">{label(DELIVERY_NOTE)}</span></output>'
    )


def overview(view):
    content = view.content
    label = partial(translate, view.language)
    layout_a = view.design.page_layout == "a"
    stage_mark = '<span class="docs-stage-mark" aria-hidden="true"></span>' if layout_a else ""
    stages = []
    for title, status, current in stage_steps(content, view.language):
        current_attr = ' aria-current="step"' if current else ""
        status_tag = f'<span class="quiet">{safe(status)}</span>' if status else ""
        stages.append(f'<li{current_attr}>{stage_mark}<strong>{safe(title)}</strong>{status_tag}</li>')
    stage_line = f'<ol class="docs-stages" aria-label="{label("Meeting stages")}">' + "".join(stages) + "</ol>"
    headline = f'<h1>{safe(content["headline"])}</h1>'
    details = [safe(detail) for detail in project_details(view.project, view.language)]
    counts = (
        '<dl class="counts">'
        f'<div><dt>{label("Sections")}</dt><dd>{len(content["document"])}</dd></div>'
        f'<div><dt>{label("Decisions")}</dt><dd>{len(content["decisions"])}</dd></div>'
        f'<div><dt>{label("Things we need")}</dt><dd>{len(content["needs"])}</dd></div></dl>'
    )
    if layout_a:
        stage_panel = (
            '<div class="docs-stage-panel">'
            f'<p class="docs-stage-label">{label("Meeting stages")}</p>'
            f'{stage_line}<p class="quiet">{label(DELIVERY_NOTE)}</p></div>'
        )
        details_line = f'<p class="quiet meeting-people">{" · ".join(details)}</p>' if details else ""
        return "\n".join((headline, details_line, stage_panel, counts))
    return "\n".join((headline, stage_line, counts, *(f'<p class="quiet">{detail}</p>' for detail in details)))


def answer_spans(decision, pending, *, allow_defer, language="en"):
    choices = [f'<span class="docs-unset">{pending}</span>']
    choices.extend(f'<span class="docs-pick docs-pick-{number}">{safe(option)}</span>'
                   for number, option in enumerate(decision["options"], 1))
    if allow_defer:
        choices.append(f'<span class="docs-pick docs-pick-later">{translate(language, DECIDE_NEXT_WEEK)}</span>')
    return "".join(choices)


def document(view):
    decisions = {row["id"]: (number, row)
                 for number, row in enumerate(view.content["decisions"], 1)}

    def inline(decision_id):
        number, decision = decisions[decision_id]
        choices = answer_spans(decision, inline_answer(None, view.language), allow_defer=False, language=view.language)
        return f'<span class="docs-inline docs-answer-{number}">{choices}</span>'

    def sentence(text):
        return "<p>" + "".join(sentence_parts(text, inline, escape)) + "</p>"

    sections = [
        f'<section class="card docs-section"><h3>{safe(section["title"])}</h3>'
        + "".join(sentence(line["text"]) for line in section["sentences"]) + "</section>"
        for section in view.content["document"]
    ]
    if not sections:
        sections.append(f'<p class="empty">{translate(view.language, NO_SENTENCES)}</p>')
    return "".join((*carryover(view), *sections, *carryover_cards(view)))


def decision_cards(decisions, language="en", *, layout_a=False):
    label = partial(translate, language)
    if not decisions:
        return f'<p class="empty">{label(NO_DECISIONS)}</p>'
    cards = []
    if layout_a:
        instruction = label("Try an answer to see how many decisions are left.")
        cards.append(f'<p class="decision-instruction">{instruction}</p>')
    resolved = label("Resolves this decision") if layout_a else None
    deferred = label("Keeps this decision open") if layout_a else None
    for number, decision in enumerate(decisions, 1):
        group = f"docs-decision-{number}"
        title = safe(decision["question"])
        cards.extend((
            '<article class="card decision">',
            *([f'<bdi class="decision-id">{safe(decision["id"])}</bdi>'] if layout_a else []),
            f'<h3>{title}</h3>',
            f'<p>{safe(decision["why"])}</p>',
            *(f'<p class="quiet">{safe(row["who"])} · {safe(row["what"])}</p>'
              for row in decision.get("said", ())),
            f'<fieldset class="answers" id="{group}" data-change-id="{safe(decision["id"])}" '
            f'aria-label="{title}">',
            *(radio(group, f"{group}-{index}", option, option, detail=resolved)
              for index, option in enumerate(decision["options"], 1)),
            radio(group, f"{group}-later", DOCS_LATER, label(DECIDE_NEXT_WEEK), detail=deferred),
            '</fieldset></article>',
        ))
    return "\n".join(cards)


def running_table(decisions, language="en"):
    label = partial(translate, language)
    lines = [
        f'<p class="quiet">{label(SCOPE_NOTE)}</p>',
        f'<table class="docs-table" aria-label="{label("Meeting decisions")}">',
        '<thead><tr>',
        *(f'<th scope="col">{label(title)}</th>' for title in DOCS_TABLE_HEADINGS),
        '</tr></thead><tbody>',
    ]
    for number, decision in enumerate(decisions, 1):
        choices = answer_spans(decision, label(NOT_DECIDED), allow_defer=True, language=language)
        lines.append(
            f'<tr class="docs-row-{number}"><th scope="row">{safe(decision["question"])}</th>'
            f'<td class="docs-answer-{number}">{choices}</td>'
            f'<td><span class="docs-count" style="--docs-left: var(--left-{number})"></span></td></tr>'
        )
    lines.extend((
        f'</tbody><tfoot><tr><th scope="row" colspan="2">{label("Total left to decide")}</th>',
        '<td><span class="docs-count"></span></td></tr></tfoot></table>',
    ))
    return "\n".join(lines)


def panels(view, save):
    decisions = view.content["decisions"]
    settled = view.content.get("settled", ())
    layout_a = view.design.page_layout == "a"
    cards = decision_cards(decisions, view.language, layout_a=layout_a)
    if settled:
        items = "".join(f"<li>{safe(question)}</li>" for question in settled)
        heading = translate(view.language, SETTLED_HEADING)
        cards = f'<section class="card"><h3>{heading}</h3><ul>{items}</ul></section>' + cards
    return (overview(view), document(view), cards,
            next_week(view.content, view.meeting.year, view.language, layout_a=layout_a),
            running_table(decisions, view.language) + save)
