"""Draw the client copy from the checked meeting view."""

from base64 import b32encode
from dataclasses import replace
from datetime import date
from functools import partial
from html import escape
from io import BytesIO

from .carryover_text import carryover_sections, missed_meeting_notices
from .meeting_design import PDF_LAYOUTS
from .meeting_design_fonts import ARABIC_FAMILY, ARABIC_ROLES, WEIGHTS, font_filename
from .meeting_language import translate
from .pdf_text import FONT_FILES, FONT_ROLES
from .storage import Refusal
from .text_fields import one_line


DASH = "—"
MARGIN = 40
FALLBACK_PREFIX = "WeekflowFallback"
ARABIC_FONTS = dict(zip(("WeekflowNaskhRegular", "WeekflowNaskhBold"), ARABIC_ROLES))


class PdfRendererUnavailable(Refusal):
    """The optional PDF renderer could not be loaded."""


def register_fonts(design):
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont, TTFError

    names = {}
    registered = set(pdfmetrics.getRegisteredFontNames())
    roles = {**FONT_ROLES, **ARABIC_FONTS}
    for studio_name, role in roles.items():
        if role not in design.font_data:
            continue
        fallback = role in design.missing_roles
        if fallback:
            name = FALLBACK_PREFIX + design.font_digests[role]
        else:
            name = studio_name if design.is_studio else f"Weekflow{design.font_digests[role]}"
        names[role] = name
        if name in registered:
            continue
        try:
            font = TTFont(name, BytesIO(design.font_data[role]))
            if fallback or not design.is_studio:
                # ReportLab also shares dynamic fonts by their internal face name.
                digest = bytes.fromhex(design.font_digests[role])
                font.face.name = b"WF" + b32encode(digest).rstrip(b"=")
            pdfmetrics.registerFont(font)
        except (OSError, TTFError):
            if not design.is_studio:
                label = f"for the {role}"
            elif studio_name in FONT_FILES:
                label = FONT_FILES[studio_name]
            else:
                label = font_filename(ARABIC_FAMILY, WEIGHTS[ARABIC_ROLES.index(role)])
            raise Refusal(f"Restore the saved meeting PDF font {label}.") from None
        registered.add(name)
    return names


def pdf_styles(design, fonts, *, language="en"):
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.styles import ParagraphStyle

    colors = design.colors
    body = ParagraphStyle("Body", fontName=fonts["body"], fontSize=11, leading=14,
                          textColor=colors["text"], spaceAfter=3, splitLongWords=True)
    cell = ParagraphStyle("Cell", parent=body, fontSize=9, leading=12, spaceAfter=0)
    styles = {
        "body": body,
        "quiet": ParagraphStyle("Quiet", parent=body, textColor=colors["quiet"]),
        "project": ParagraphStyle("Project", parent=body, fontName=fonts["display"], fontSize=15,
                                  leading=19, textColor=design.main_text, keepWithNext=True),
        "title": ParagraphStyle("Title", parent=body, fontName=fonts["title"], fontSize=32,
                                leading=35, spaceBefore=8, spaceAfter=8),
        "section": ParagraphStyle("Section", parent=body, fontName=fonts["title"], fontSize=16,
                                  leading=19, spaceBefore=9, keepWithNext=True),
        "label": ParagraphStyle("Label", parent=body, fontName=fonts["bold"], keepWithNext=True),
        "reason": ParagraphStyle("Reason", parent=body, keepWithNext=True),
        "notice": ParagraphStyle("Notice", parent=body, fontName=fonts["bold"], backColor=colors["card"],
                                 borderPadding=7, spaceBefore=7, spaceAfter=7),
        "cell": cell,
        "decision_note": ParagraphStyle("DecisionNote", parent=cell, fontSize=8, leading=10),
        "number": ParagraphStyle("Number", parent=cell, alignment=TA_RIGHT),
        "head": ParagraphStyle("Head", parent=cell, fontName=fonts["bold"], textColor=colors["on-main"],
                               fontSize=8.5),
        "head_number": ParagraphStyle("HeadNumber", parent=cell, fontName=fonts["bold"],
                                      textColor=colors["on-main"], fontSize=8.5, alignment=TA_RIGHT),
        "total": ParagraphStyle("Total", parent=cell, fontName=fonts["bold"]),
        "total_number": ParagraphStyle("TotalNumber", parent=cell, fontName=fonts["bold"],
                                       alignment=TA_RIGHT),
    }

    if language == "ar":
        bold_styles = {"title", "section", "label", "notice", "head", "head_number",
                       "total", "total_number"}
        for key, style in styles.items():
            bold = key in bold_styles
            style.fontName = fonts["arabic-bold" if bold else "arabic-regular"]
            style.latinFont = fonts["bold" if bold else "body"]
            style.alignment = TA_RIGHT
            style.leading += 2
            if key == "notice":
                style.spaceBefore += 7
                style.spaceAfter += 7
    return styles


def paragraph(value, style, field):
    if hasattr(style, "latinFont"):
        from .pdf_arabic import ArabicParagraph

        return ArabicParagraph(one_line(value), style, field)

    from reportlab.pdfbase.pdfmetrics import getFont
    from reportlab.platypus import Paragraph

    value = one_line(value)
    glyphs = getFont(style.fontName).face.charToGlyph
    if style.fontName.startswith(FALLBACK_PREFIX):
        value = "".join(character if glyphs.get(ord(character)) else f"[U+{ord(character):04X}]"
                        for character in value)
    else:
        for character in value:
            if not glyphs.get(ord(character)):
                raise Refusal(f"The PDF font cannot draw U+{ord(character):04X} in {field}.")
    return Paragraph(escape(value, quote=False), style)


def badge_colors(design, role):
    from reportlab.lib.colors import HexColor, linearlyInterpolatedColor

    ink = design.badge_ink(role)
    tint = linearlyInterpolatedColor(HexColor(design.colors["background"]), HexColor(ink),
                                     0, 1, 0.10)
    return ink, tint


def badge_width(label, style, design):
    from reportlab.pdfbase.pdfmetrics import stringWidth

    if hasattr(style, "latinFont"):
        title = paragraph(label, style, "the answer")
        return title.measure(title.value) + 12.01
    width = stringWidth(label, style.fontName, style.fontSize) + 12
    # Keep a one-line label from wrapping when custom metrics land on a float boundary.
    return width if design.is_studio else width + 0.01


def answer_badge(answer, label, style, design, bold, *, on_paper=False, radius=6):
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Table

    role = {None: "quiet", "yes": "main", "later": "quiet", "no": "error"}[answer]
    ink, tint = badge_colors(design, role)
    if on_paper:
        tint = design.colors["background"]
    rtl = hasattr(style, "latinFont")
    badge_style = ParagraphStyle("Badge", parent=style, fontName=bold, fontSize=8,
                                 leading=12 if rtl else 10, textColor=ink)
    title = paragraph(label, badge_style, "the answer")
    width = badge_width(label, badge_style, design)
    return Table([[title]], colWidths=[width], hAlign="RIGHT" if rtl else "LEFT",
                 cornerRadii=[radius] * 4,
                 style=[("BACKGROUND", (0, 0), (-1, -1), tint),
                        ("TOPPADDING", (0, 0), (-1, -1), 3),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3)])


def direction(language):
    return "RIGHT" if language == "ar" else "LEFT"


def need_due(view, need):
    language = view.language
    if "by" in need:
        return translate(language, "Due {date}", date=view.date_text(date.fromisoformat(need["by"])))
    return translate(language, "Needed from the client")


def running_table(view, styles, width, *, layout=None):
    from reportlab.platypus import HRFlowable, LongTable, Spacer

    from .page import ANSWERS, TABLE_HEADINGS, day_count

    language = view.language
    align = direction(language)

    def cell(value, field="the Running Date table", style="cell"):
        return paragraph(value, styles[style], field)

    answer_labels = dict(ANSWERS)
    colors = view.design.colors
    badge_radius = layout.badge_radius if layout is not None else 6
    rows = [
        [cell(translate(language, "Running Date"), style="label"), "", "", "", ""],
        [cell(translate(language, label).upper(), style="head_number" if index == 3 else "head")
         for index, label in enumerate(TABLE_HEADINGS)],
    ]
    rows.append([cell(view.date_label), cell(DASH), cell(DASH), cell(DASH, style="number"),
                 cell(view.date_text(view.end_before))])
    for change, answer, days, end in view.running_decisions():
        change_id = change["id"]
        title = cell(change["what"], f"the decision {change_id}")
        byline = []
        decider = view.build_deciders.get(change_id)
        if answer is not None and decider:
            label = translate(language, "Decided by {name} on {date}",
                              name=decider, date=view.date_text(view.meeting))
            byline.append(cell(label, f"the decider for {change_id}", style="decision_note"))
        if days:
            byline.append(cell(translate(language, "Date moved"), style="total"))
        rows.append([
            [title, *byline] if byline else title,
            cell(change["asked_by"], f"who raised {change_id}"),
            answer_badge(answer, translate(language, answer_labels.get(answer, "Not decided")),
                         styles["cell"], view.design, styles["label"].fontName, radius=badge_radius),
            cell(day_count(days, language), style="number"),
            cell(view.date_text(end)),
        ])
    for number, need in enumerate(view.content["needs"], 1):
        rows.append([
            cell(need["text"], f"need {number}"), cell(DASH), cell(need_due(view, need)),
            cell(DASH, style="number"), cell(view.date_text(view.end_after)),
        ])
    days_added = (view.end_after - view.end_before).days
    rows.append([
        cell(translate(language, "New delivery date"), style="total"), cell(DASH), cell(DASH),
        cell(day_count(days_added, language), style="total_number"),
        cell(view.date_text(view.end_after), style="total"),
    ])
    total_row = len(rows) - 1
    grid = [
        ("SPAN", (0, 0), (-1, 0)),
        ("BACKGROUND", (0, 1), (-1, 1), colors["main"]),
        ("ROWBACKGROUNDS", (0, 2), (-1, total_row - 1), (colors["background"], colors["card"])),
        ("BACKGROUND", (0, total_row), (-1, total_row), colors["card"]),
        ("GRID", (0, 2), (-1, total_row), 1, colors["lines"]),
        ("LINEBELOW", (0, total_row), (-1, total_row), 1.3, colors["main"]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        (f"{align}PADDING", (0, 0), (-1, 0), 0),
    ]
    if days_added or layout is not None:
        if layout is not None:
            from .pdf_layout_c import SignatureLines

            signature = SignatureLines(layout, bool(days_added))
        else:
            signature = [
                Spacer(1, 18),
                HRFlowable(width=200, hAlign=align, thickness=1, color=colors["quiet"]),
                cell("التوقيع على الورق" if language == "ar" else "Paper signature", style="quiet"),
            ]
        rows.append([signature, "", "", "", ""])
        # Keep the signature beside the date it approves, outside the grid.
        grid.extend([
            ("SPAN", (0, -1), (-1, -1)),
            ("NOSPLIT", (0, total_row), (-1, -1)),
            (f"{align}PADDING", (0, -1), (-1, -1), 0),
            ("BOTTOMPADDING", (0, -1), (-1, -1), 0),
        ])
        if layout is not None:
            grid.append(("LEFTPADDING", (0, -1), (-1, -1), 0))
            grid.append(("RIGHTPADDING", (0, -1), (-1, -1), 0))
    columns = (0.30, 0.17, 0.18, 0.12, 0.23)
    if language == "ar":
        for row in rows[1:total_row + 1]:
            row.reverse()
        columns = columns[::-1]
        grid.append(("ALIGN", (0, 0), (-1, -1), "RIGHT"))
    return LongTable(
        rows, colWidths=[width * fraction for fraction in columns],
        repeatRows=2, splitByRow=1, splitInRow=0, hAlign=align, style=grid,
    )


def story_for(view, styles, width):
    from .page import (
        HEADINGS, MEETING_UNRECORDED, NO_DECISIONS, NO_FINISHED, NO_NEEDS, NO_NEXT_WEEK,
        day_count, meeting_label,
    )
    from .screen_pdf import screen_map_story

    language = view.language

    def label(value, **values):
        return translate(language, value, **values)

    def text(value, style="body", field="a meeting label"):
        return paragraph(value, styles[style], field)

    def items(key, empty):
        rows = view.content[key]
        if not rows:
            return [text(label(empty), "quiet")]
        return [text(item["text"], field=f"item {number} in {key}")
                for number, item in enumerate(rows, 1)]

    project = view.project
    meeting = meeting_label(view.week["number"], language)
    story = [text(project["project"], "project", "the project name"),
             text(f"{meeting} · {view.date_text(view.meeting)}", "quiet"),
             text(view.content["headline"], "title", "the headline")]
    if project["client"]:
        story.append(text(label("Client: {name}", name=project["client"]), field="the client name"))
    if view.attendees:
        attendees = ("، " if language == "ar" else ", ").join(view.attendees)
        story.append(text(label("Attendees: {names}", names=attendees), field="the attendees"))
    if not view.week["held"]:
        story.append(text(label(MEETING_UNRECORDED), "notice"))

    story.append(text(label(HEADINGS[1]), "section"))
    story.extend(screen_map_story(view, styles))
    story.extend(text(notice, "quiet") for notice in missed_meeting_notices(view))
    story.extend(items("finished", NO_FINISHED))
    for heading, rows in carryover_sections(view):
        story.append(text(heading, "label"))
        for title, details in rows:
            story.append(text(title, "label", heading))
            story.extend(text(detail, "quiet", heading) for detail in details)
    story.append(text(label(HEADINGS[2]), "section"))
    if not view.changes:
        story.append(text(label(NO_DECISIONS), "quiet"))
    for change in view.changes:
        change_id = change["id"]
        raised = view.date_text(date.fromisoformat(change["date"]))
        identifier = f'{change_id} · ' if language == "en" else ""
        byline = label("Raised by {name} on {date}. · {days}", name=change["asked_by"],
                       date=raised, days=day_count(change["days_added"], language))
        story.extend([
            text(identifier + change["what"], "label", f"the decision {change_id}"),
            text(change["reason"], "reason", field=f"the reason for {change_id}"),
            text(byline, "quiet", f"who raised {change_id}"),
        ])
    story.extend([text(label(HEADINGS[3]), "section"), *items("next_week", NO_NEXT_WEEK),
                  text(label("What we need from the client"), "label")])
    if not view.content["needs"]:
        story.append(text(label(NO_NEEDS), "quiet"))
    for number, need in enumerate(view.content["needs"], 1):
        due = f" · {need_due(view, need)}" if "by" in need else ""
        story.append(text(need["text"] + due, field=f"need {number}"))

    story.extend([
        text(label(HEADINGS[4]), "section"),
        text(label("Delivery date before the meeting: {date}", date=view.date_text(view.end_before))),
        text(label("Delivery date after the meeting: {date}", date=view.date_text(view.end_after))),
        running_table(view, styles, width),
    ])
    return story


def draw_page_frame(canvas, doc, *, design, fonts, language, footer_style):
    width, height = doc.pagesize
    colors = design.colors
    canvas.setFillColor(colors["background"])
    canvas.rect(0, 0, width, height, stroke=0, fill=1)
    canvas.setStrokeColor(colors["lines"])
    canvas.line(MARGIN, 33, width - MARGIN, 33)
    canvas.setFillColor(colors["quiet"])
    if language == "ar":
        from .pdf_arabic import draw_line, drawable_runs, line_width

        title = list(drawable_runs(translate(language, "Weekly meeting"), footer_style, "the PDF footer"))
        number = list(drawable_runs(translate(language, "Page {number}", number=doc.page),
                                    footer_style, "the PDF footer"))
        draw_line(canvas, width - MARGIN - line_width(title, 8), 21, title, 8)
        draw_line(canvas, MARGIN, 21, number, 8)
    else:
        canvas.setFont(fonts["body"], 8)
        canvas.drawString(MARGIN, 21, "Weekly meeting")
        canvas.drawRightString(width - MARGIN, 21, f"Page {doc.page}")


def render_pdf(view):
    # Keep these imports off the command path for everything except the PDF.
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate
        from reportlab.platypus.doctemplate import LayoutError
    except ImportError:
        raise PdfRendererUnavailable("The reportlab package is required for the client PDF.") from None

    design = view.design.for_pdf()
    view = replace(view, design=design)
    fonts = register_fonts(design)
    language = view.language
    styles = pdf_styles(design, fonts, language=language)
    output = BytesIO()
    margin = MARGIN
    layout = None
    if design.pdf_layout in PDF_LAYOUTS:
        from .pdf_layout_c import MARGIN_C, MeetingPdfLayout

        margin = MARGIN_C
        layout = MeetingPdfLayout(view, styles, A4[0] - 2 * margin, A4[1] - 2 * margin)
    width = A4[0] - 2 * margin
    height = A4[1] - 2 * margin
    doc = BaseDocTemplate(output, pagesize=A4, title=translate(language, "Weekly meeting"), invariant=1)
    frame = Frame(margin, margin, width, height, leftPadding=0, rightPadding=0,
                  topPadding=0, bottomPadding=0)
    draw_frame = partial(draw_page_frame, design=design, fonts=fonts, language=language,
                         footer_style=styles["body"])
    doc.addPageTemplates(PageTemplate("Meeting", [frame], onPage=layout.footer if layout else draw_frame))
    if layout and view.is_docs:
        from .docs_pdf_c import story_for_docs_c

        story = story_for_docs_c(view, layout)
    elif layout:
        from .build_pdf_c import story_for_build_c

        story = story_for_build_c(view, layout)
    elif view.is_docs:
        from .docs_pdf import story_for_docs

        story = story_for_docs(view, styles, width)
    else:
        story = story_for(view, styles, width)
    try:
        doc.build(story)
    except LayoutError:
        if view.is_docs:
            raise Refusal("A row in the decisions table is too tall to print on one page. "
                          "Shorten the question or answer.") from None
        raise Refusal("A row in the Running Date table is too tall to print on one page. "
                      "Shorten the decision or need.") from None
    return output.getvalue()
