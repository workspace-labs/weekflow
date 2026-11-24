"""Draw the docs meeting's agendas and answers in the client PDF."""

from .carryover_text import carryover_sections, missed_meeting_notices
from .client_pdf import badge_colors, badge_width, direction, need_due, paragraph
from .docs_presentation import (
    DECIDE_NEXT_WEEK, DELIVERY_NOTE, DOCS_TABLE_HEADINGS, NO_SENTENCES, SCOPE_NOTE,
    SETTLED_HEADING, docs_answer_label, inline_answer, sentence_parts, stage_steps,
)
from .meeting_language import translate
from .page import (
    DOCS_LATER, HEADINGS, MEETING_UNRECORDED, NO_DECISIONS, NO_NEEDS, NO_NEXT_WEEK, meeting_label,
)


def decision_badge(answer, width, style, design, language="en", *, radius=6):
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Table

    label = docs_answer_label(answer, language)
    role = "quiet" if answer in (None, DOCS_LATER) else "main"
    ink, tint = badge_colors(design, role)
    badge = ParagraphStyle("DocsBadge", parent=style, fontSize=9, textColor=ink)
    title = paragraph(label, badge, "the answer")
    fit = min(width - 16, badge_width(label, badge, design))
    return Table([[title]], colWidths=[fit], hAlign=direction(language), cornerRadii=[radius] * 4, style=[
        ("BACKGROUND", (0, 0), (-1, -1), tint),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ])


def decisions_table(view, styles, width, *, badge_radius=6):
    from reportlab.platypus import LongTable

    language = view.language

    def cell(value, style="cell", field="the decisions table"):
        return paragraph(value, styles[style], field)

    columns = (width * 0.46, width * 0.34, width * 0.20)
    rows = [[cell(translate(language, title).upper(), "head_number" if index == 2 else "head")
             for index, title in enumerate(DOCS_TABLE_HEADINGS)]]
    deciders = {entry["id"]: entry.get("decided_by") for entry in view.week.get("answers", [])}
    for decision, answer, remaining in view.running_docs_decisions():
        decider = deciders.get(decision["id"])
        badge = decision_badge(answer, columns[1], styles["cell"], view.design, language, radius=badge_radius)
        answer_cell = badge
        if decider and answer not in (None, DOCS_LATER):
            byline = translate(language, "Decided by {name}", name=decider)
            answer_cell = [badge, cell(byline, field=f'the decider for {decision["id"]}')]
        rows.append([
            cell(decision["question"], field=f'the question for {decision["id"]}'),
            answer_cell,
            cell(str(remaining), "number"),
        ])
    total_label = cell(translate(language, "Total left to decide"), "total")
    total_number = cell(str(view.decisions_left), "total_number")
    if language == "ar":
        rows = [row[::-1] for row in rows]
        rows.append([total_number, total_label, ""])
        columns = columns[::-1]
        span_start, span_end = 1, 2
    else:
        rows.append([total_label, "", total_number])
        span_start, span_end = 0, 1
    total = len(rows) - 1
    colors = view.design.colors
    grid = [
        ("BACKGROUND", (0, 0), (-1, 0), colors["main"]),
        ("ROWBACKGROUNDS", (0, 1), (-1, total), (colors["card"], colors["background"])),
        ("BACKGROUND", (0, total), (-1, total), colors["card"]),
        ("GRID", (0, 1), (-1, total), 1, colors["lines"]),
        ("LINEBELOW", (0, total), (-1, total), 1.3, colors["main"]),
        ("SPAN", (span_start, total), (span_end, total)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    if language == "ar":
        grid.append(("ALIGN", (0, 0), (-1, -1), "RIGHT"))
    return LongTable(rows, colWidths=columns, repeatRows=1, splitByRow=1, splitInRow=0,
                     hAlign=direction(language), style=grid)


def story_for_docs(view, styles, width):
    from reportlab.lib.enums import TA_LEFT, TA_RIGHT
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Table

    language = view.language
    rtl = language == "ar"

    def label(value, **values):
        return translate(language, value, **values)

    def text(value, style="body", field="a meeting label"):
        return paragraph(value, styles[style], field)

    def status(value, style="quiet"):
        alignment = TA_LEFT if rtl else TA_RIGHT
        header_style = ParagraphStyle("DocsHeader", parent=styles[style], alignment=alignment)
        return paragraph(value, header_style, "the meeting status")

    def inline(decision_id):
        return inline_answer(answers.get(decision_id), language)

    content = view.content
    rows = list(view.running_docs_decisions())
    answers = {decision["id"]: answer for decision, answer, _ in rows}
    left = view.decisions_left
    meeting = meeting_label(view.week["number"], language)
    header = [[
        [text(view.project["project"], "project", "the project name"),
         text(f"{meeting} · {view.date_text(view.meeting)}", "quiet")],
        [status(label(DOCS_TABLE_HEADINGS[-1])),
         status(str(left) if left else label("All decided"), "label"),
         status(label(DELIVERY_NOTE))],
    ]]
    header_widths = (width * .52, width * .48)
    stage_widths = (width * .49, width * .51)
    stage_cells = []
    for title, stage_status, current in stage_steps(content, language):
        stage_label = title + (f" · {stage_status}" if stage_status else "")
        stage_cells.append(text(stage_label, "label" if current else "body"))
    stages = [stage_cells[:2], stage_cells[2:]]
    if rtl:
        header[0].reverse()
        header_widths = header_widths[::-1]
        for row in stages:
            row.reverse()
        stage_widths = stage_widths[::-1]
    story = [
        Table(header, colWidths=header_widths, style=[
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]),
        text(label(HEADINGS[0]), "section"),
        text(content["headline"], "title", "the headline"),
        Table(stages, colWidths=stage_widths, style=[
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (0, -1), 0),
            ("RIGHTPADDING", (-1, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ]),
    ]
    if view.project["client"]:
        story.append(text(label("Client · {name}", name=view.project["client"]), "quiet"))
    if view.attendees:
        attendees = ("، " if rtl else ", ").join(view.attendees)
        story.append(text(label("Attendees · {names}", names=attendees), "quiet"))
    if not view.week["held"]:
        story.append(text(label(MEETING_UNRECORDED), "notice"))

    story.append(text(label(HEADINGS[1]), "section"))
    story.extend(text(notice, "quiet") for notice in missed_meeting_notices(view))
    if not content["document"]:
        story.append(text(label(NO_SENTENCES), "quiet"))
    for section in content["document"]:
        story.append(text(section["title"], "label", "a document section"))
        for sentence in section["sentences"]:
            visible = "".join(sentence_parts(sentence["text"], inline))
            story.append(text(visible, field="a document sentence"))
    for heading, carryovers in carryover_sections(view):
        story.append(text(heading, "label"))
        for title, details in carryovers:
            story.append(text(title, "label", heading))
            story.extend(text(detail, "quiet", heading) for detail in details)

    story.append(text(label(HEADINGS[2]), "section"))
    settled = content.get("settled", ())
    if settled:
        story.append(text(label(SETTLED_HEADING), "label"))
        story.extend(text(question, field="a settled question") for question in settled)
    if not rows:
        story.append(text(label(NO_DECISIONS), "quiet"))
    for decision, _, _ in rows:
        decision_id = decision["id"]
        story.append(text(decision["question"], "label", f"the question for {decision_id}"))
        story.append(text(decision["why"], field=f"why for {decision_id}"))
        for account in decision.get("said", ()):
            story.append(text(f'{account["who"]} · {account["what"]}', "quiet",
                              f"what was said for {decision_id}"))
        options = " · ".join((*decision["options"], label(DECIDE_NEXT_WEEK)))
        story.append(text(options, "quiet", f"options for {decision_id}"))

    story.append(text(label(HEADINGS[3]), "section"))
    if not content["next_week"]:
        story.append(text(label(NO_NEXT_WEEK), "quiet"))
    for item in content["next_week"]:
        story.append(text(item["text"], field="a next week item"))
    story.append(text(label("What we need from the client"), "label"))
    if not content["needs"]:
        story.append(text(label(NO_NEEDS), "quiet"))
    for need in content["needs"]:
        due = f" · {need_due(view, need)}" if "by" in need else ""
        story.append(text(need["text"] + due, field="a need"))
    story.extend([
        text(label(HEADINGS[4]), "section"),
        text(label(SCOPE_NOTE), "quiet"),
        decisions_table(view, styles, width),
    ])
    return story
