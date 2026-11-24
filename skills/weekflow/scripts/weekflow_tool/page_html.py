"""Write the offline, interactive meeting page from the checked facts."""

from datetime import date
from base64 import b64encode
from functools import partial
from hashlib import sha256
from pathlib import Path

from .html_controls import (
    carryover, carryover_cards, date_text, item_list, next_week, radio, safe, step_panel,
    tab, tab_state_css,
)
from .meeting_language import translate
from .page import (
    ANSWERS, HEADINGS, NO_DECISIONS, NO_FINISHED, TABLE_HEADINGS,
    calendar_line, day_count, meeting_label, project_details,
)
from .page_design import font_faces, project_design_css
from .screen_html import render_screen_map


STYLES = Path(__file__).parent
# One above the CSS counter range. Keep larger values as this overflow marker
# in the preview while rendering the exact saved number on the decision card.
DAY_OVERFLOW = 2_147_483_648


def answer_state_css(changes, *, layout_a=False):
    lines = ["body {", "  --through-0: 0;"]
    for number in range(1, len(changes) + 1):
        lines.append(f"  --days-{number}: 0;")
        lines.append(f"  --through-{number}: calc(var(--through-{number - 1}) + var(--days-{number}));")
    lines.extend((f"  --added: var(--through-{len(changes)});", "}"))
    for number, change in enumerate(changes, start=1):
        control = f"decision-{number}"
        row = f"#running-{number}"
        yes = f"body:has(#{control}-yes:checked)"
        lines.append(f"{yes} {{ --days-{number}: {min(change['days_added'], DAY_OVERFLOW)}; }}")
        lines.append(f"body:has(#{control} input:checked) {row} .answer-pending {{ display: none; }}")
        for answer, _ in ANSWERS:
            active = f"body:has(#{control}-{answer}:checked)"
            lines.append(f"{active} {row} .answer-{answer} {{ display: inline; }}")
        if change["days_added"] > 0:
            lines.append(f"{yes} {row} .date-moved {{ display: inline; }}")
            if layout_a:
                lines.append(f"{yes} {{ --show-date-move: block; --hide-for-date-move: none; "
                             "--track-plan-fill: var(--color-background); --track-planned-text: var(--color-text); "
                             "--track-plan-align: center; }")
    return lines


def week_line(approval, end, meeting, date_label, language="en"):
    current = calendar_line(approval, end, meeting)
    if current is None:
        return ""
    number, weeks, offset = current
    span = (end - approval).days
    position = 100 * offset / span
    interval = min(100, 700 / span)
    label = partial(translate, language)
    progress = label("Week {number} of {weeks}", number=number, weeks=weeks)
    return (
        f'<div class="week-line" style="--week-position: {position:.8f}%; --week-interval: {interval:.8f}%">'
        f'<p class="week-here"><strong>{label("We are here")}</strong><br>{progress}</p>'
        '<div class="week-track" aria-hidden="true"><span></span></div>'
        '<div class="week-dates">'
        f'<span>{label("Scope approved")} <strong>{date_text(approval.isoformat(), meeting.year, language)}</strong></span>'
        f'<span>{date_label} <strong>{date_text(end.isoformat(), meeting.year, language)}</strong></span>'
        '</div></div>'
    )


def where_we_are(view):
    content = view.content
    approval = date.fromisoformat(view.project["scope_approved_on"])
    label = partial(translate, view.language)
    return (
        f'<h1>{safe(content["headline"])}</h1>',
        week_line(approval, view.end_before, view.meeting, view.date_label, view.language),
        '<dl class="counts">'
        f'<div><dt>{label("Finished items")}</dt><dd>{len(content["finished"])}</dd></div>'
        f'<div><dt>{label("Decisions")}</dt><dd>{len(view.changes)}</dd></div>'
        f'<div><dt>{label("Things we need")}</dt><dd>{len(content["needs"])}</dd></div></dl>',
        *(f'<p class="quiet">{safe(detail)}</p>' for detail in project_details(view.project, view.language)),
    )


def see_it(view, *, layout_a=False):
    parts = [render_screen_map(view)]
    parts.extend(carryover(view))
    finished = [safe(item["text"]) for item in view.content["finished"]]
    parts.append(item_list(finished, translate(view.language, NO_FINISHED),
                           mark="finished" if layout_a else ""))
    parts.extend(carryover_cards(view))
    return "".join(parts)


def decision_cards(changes, meeting_year, language="en"):
    label = partial(translate, language)
    if not changes:
        return f'<p class="empty">{label(NO_DECISIONS)}</p>'
    instruction = label("Try an answer to see how the delivery date changes.")
    lines = [f'<p class="quiet">{instruction}</p>']
    for number, change in enumerate(changes, start=1):
        group = f"decision-{number}"
        title = safe(change["what"])
        raised = label("Raised by {name} on {date}.",
                       name=safe(change["asked_by"]), date=date_text(change["date"], meeting_year, language))
        lines.extend((
            '<article class="card decision">',
            f'<h3>{title}</h3>',
            f'<p>{safe(change["reason"])}</p>',
            f'<p class="quiet">{raised}</p>',
            f'<p class="impact">{day_count(change["days_added"], language)}</p>',
            f'<fieldset class="answers" id="{group}" data-change-id="{change["id"]}" aria-label="{title}">',
            *(radio(group, f"{group}-{key}", key, label(title)) for key, title in ANSWERS),
            '</fieldset></article>',
        ))
    return "\n".join(lines)


def table_cells(cells, value_ids=("", "", "", ""), *, language="en"):
    row_header, *values = cells
    result = [f'<th scope="row" role="rowheader">{row_header}</th>']
    for label, value, identifier in zip(TABLE_HEADINGS[1:], values, value_ids):
        labelled = f' aria-labelledby="{identifier}"' if identifier else ""
        result.append(f'<td role="cell"{labelled}>'
                      f'<span class="cell-label" aria-hidden="true">{translate(language, label)}</span>{value}</td>')
    return "".join(result)


def running_table(view):
    language = view.language
    label = partial(translate, language)
    dash = "—"
    meeting_year = view.meeting.year
    start = table_cells((view.date_label, dash, dash, dash,
                         date_text(view.end_before.isoformat(), meeting_year, language)), language=language)
    lines = [
        f'<table class="running-table" role="table"><caption>{label("Running Date")}</caption>',
        '<thead role="rowgroup"><tr role="row">',
        *(f'<th scope="col" role="columnheader">{label(title)}</th>' for title in TABLE_HEADINGS),
        '</tr></thead><tbody role="rowgroup">',
        f'<tr class="starting-row" role="row">{start}</tr>',
    ]
    answers = f'<span class="answer-pending">{label("Not decided")}</span>' + "".join(
        f'<span class="answer-value answer-{key}">{label(title)}</span>' for key, title in ANSWERS
    )
    for number, change in enumerate(view.changes, start=1):
        days_value, date_value = f"running-{number}-days", f"running-{number}-date"
        cells = table_cells((
            f'{safe(change["what"])} <strong class="date-moved">{label("Date moved")}</strong>',
            safe(change["asked_by"]),
            f'<span class="table-answer">{answers}</span>',
            f'<span class="live-total" id="{days_value}" style="--added: var(--days-{number})"></span>',
            f'<span class="live-date" id="{date_value}"></span>',
        ), ("", "", days_value, date_value), language=language)
        lines.append(f'<tr id="running-{number}" role="row" '
                     f'style="--added: var(--through-{number})">{cells}</tr>')
    for number, need in enumerate(view.content["needs"], start=1):
        due = label("Needed from the client")
        if "by" in need:
            due = label("Due {date}", date=date_text(need["by"], meeting_year, language))
        date_value = f"need-{number}-date"
        cells = table_cells((safe(need["text"]), dash, due, dash,
                             f'<span class="live-date" id="{date_value}"></span>'),
                            ("", "", "", date_value), language=language)
        lines.append(f'<tr role="row">{cells}</tr>')
    final = table_cells((
        label("New delivery date"), dash, dash, '<span class="live-total" id="total-days"></span>',
        '<span class="live-date" id="total-date"></span>',
    ), ("", "", "total-days", "total-date"), language=language)
    lines.extend((
        '</tbody><tfoot role="rowgroup">',
        f'<tr id="running-total" role="row">{final}</tr>',
        '</tfoot></table>',
    ))
    return "\n".join(lines)


def live_date_styles(rtl):
    calendar = (STYLES / "page_date_math.css").read_text(encoding="utf-8")
    if rtl:
        return calendar + (STYLES / "page_dates_ar.css").read_text(encoding="utf-8")
    return (STYLES / "page_dates.css").read_text(encoding="utf-8") + calendar

def render_html(view, *, legacy_build_fonts=None):
    if legacy_build_fonts is None:
        legacy_build_fonts = view.legacy_build_fonts
    language = view.language
    label = partial(translate, language)
    rtl = language == "ar"
    legacy_build_fonts = legacy_build_fonts and not rtl
    proof = view.fingerprint
    week = view.week
    content = view.content
    year = view.meeting.year
    layout_a = view.design.page_layout == "a"
    body_class = ' class="layout-a"' if layout_a else ""
    script = (STYLES / "save_answers.js").read_text(encoding="utf-8")
    script_hash = b64encode(sha256(script.encode("utf-8")).digest()).decode("ascii")
    save = (
        f'<button type="button" class="save-answers" id="save-answers" data-week="{week["number"]}" '
        f'data-fingerprint="{proof}" hidden>{label("Save answers")}</button>'
        f'<noscript><p class="quiet">{label("Tell the agent the answers.")}</p></noscript>'
    )
    if view.is_docs:
        from . import docs_html

        asset_policy = "font-src data:; "
        styles = (*tab_state_css(layout_a=layout_a), *docs_html.styles(content["decisions"], view.design, language))
        body = f"<body{body_class}>"
        status = docs_html.header_status(language, layout_a=layout_a)
        panels = docs_html.panels(view, save)
    else:
        show_screens = bool(view.screen_map) or content.get("app_ran") is False
        asset_policy = "" if legacy_build_fonts else "font-src data:; "
        if show_screens:
            asset_policy += "img-src data:; "
        screen_styles = [(STYLES / "screen_map.css").read_text(encoding="utf-8")] if show_screens else []
        styles = (
            *(() if legacy_build_fonts else font_faces(view.design, language=language)),
            live_date_styles(rtl),
            *screen_styles, *tab_state_css(layout_a=layout_a), *answer_state_css(view.changes, layout_a=layout_a),
        )
        # The Arabic calendar always prints the year.
        preview_year = 0 if rtl else year
        body = (f'<body{body_class} style="--start-day: {view.end_before.toordinal() - 1}; '
                f'--meeting-year: {preview_year}">')
        status = (
            '<output class="delivery" aria-live="polite" aria-atomic="true">'
            f'<span class="quiet">{label("We deliver on")}</span> '
            '<span class="delivery-date"><span class="live-date"></span></span> '
            '<span class="delivery-days"><span class="delivery-total"></span></span></output>'
        )
        if layout_a:
            from . import build_page_a

            opening = build_page_a.where_we_are(view)
            decisions = build_page_a.decision_cards(view, DAY_OVERFLOW)
        else:
            opening = "\n".join(where_we_are(view))
            decisions = decision_cards(view.changes, year, language)
        panels = (opening, see_it(view, layout_a=layout_a), decisions,
                  next_week(content, year, language, layout_a=layout_a), running_table(view) + save)
    document = '<html lang="ar" dir="rtl">' if rtl else '<html lang="en">'
    rtl_styles = ((STYLES / "page_rtl.css").read_text(encoding="utf-8"),) if rtl else ()
    extra_styles = []
    meeting_date = date_text(week["meeting_date"], year, language)
    project = safe(view.project["project"])
    if layout_a:
        extra_styles.append((STYLES / "page_a.css").read_text(encoding="utf-8"))
        if not view.is_docs:
            extra_styles.append((STYLES / "page_track_a.css").read_text(encoding="utf-8"))
        meeting = label("Weekly meeting {number}", number=week["number"])
        heading = (f'<div class="meeting-id"><strong class="project-name">{project}</strong> '
                   f'<strong class="meeting-number">· {meeting}</strong> '
                   f'<span class="quiet">{meeting_date}</span></div>')
    else:
        heading = (f'<div><p class="project-name">{project}</p>'
                   f'<p class="quiet">{meeting_label(week["number"], language)} · {meeting_date}</p></div>')
    lines = [
        '<!doctype html>', document, '<head>', '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
        f"script-src 'sha256-{script_hash}'; {asset_policy}"
        'style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">',
        f'<title>{label("Weekly meeting")}</title>', '<style>',
        (STYLES / "page.css").read_text(encoding="utf-8"),
        *styles,
        *project_design_css(view.design),
        *rtl_styles,
        *extra_styles,
        '</style></head>',
        body,
        f'<!-- Draft fingerprint: {proof} -->',
        '<header class="meeting-header"><div class="shell header-inner">',
        heading,
        status,
        '</div></header>',
        f'<main class="shell meeting-page"><nav class="meeting-tabs" aria-label="{label("Meeting steps")}">',
        *(tab(index, label(title), layout_a=layout_a) for index, title in enumerate(HEADINGS, start=1)),
        '</nav>',
        *(step_panel(index, panel, language) for index, panel in enumerate(panels, 1)),
        f'</main><script>{script}</script></body></html>',
    ]
    return "\n".join(lines) + "\n"
