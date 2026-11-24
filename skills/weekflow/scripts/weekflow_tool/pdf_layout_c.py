"""Compose the shared frame and components of a Layout C client PDF."""

from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import Flowable, Spacer, Table

from .carryover_text import carryover_sections, missed_meeting_notices
from .client_pdf import need_due, paragraph
from .meeting_design import PDF_LAYOUT_C_REVISED
from .meeting_design_colors import contrast
from .meeting_language import translate
from .page import MEETING_UNRECORDED, NO_NEEDS, format_date
from .pdf_layout_blocks import ChecklistRow, Columns, Panel


MARGIN_C = 42


def line_width(flowable):
    if hasattr(flowable.style, "latinFont"):
        return flowable.measure(flowable.value)
    style = flowable.style
    return stringWidth(flowable.getPlainText(), style.fontName, style.fontSize)


class MeetingPdfLayout:
    def __init__(self, view, styles, width, frame_height):
        self.view = view
        self.design = view.design
        self.language = view.language
        self.rtl = self.language == "ar"
        self.width = width
        self.frame_height = frame_height
        self.badge_radius = self.design.radius * .3
        self.styles = dict(styles)
        self.reading_alignment = TA_RIGHT if self.rtl else TA_LEFT
        self.opposite_alignment = TA_LEFT if self.rtl else TA_RIGHT
        extra = 2 if self.rtl else 0
        colors = self.design.colors
        self.styles.update(
            project=self.with_style("title", fontSize=11.5, leading=15 + extra,
                                    spaceBefore=0, spaceAfter=0, textColor=colors["text"]),
            footer_project=self.with_style("project", textColor=colors["quiet"], fontSize=8, leading=9),
            title=self.with_style("title", fontSize=25, leading=28 + extra,
                                  spaceBefore=13, spaceAfter=4),
            section=self.with_style("section", fontSize=10.5 if not self.rtl else 12,
                                    leading=13 + extra, spaceBefore=13, spaceAfter=8,
                                    textColor=self.design.main_text),
            small=self.with_style("quiet", fontSize=9, leading=12 + extra),
            panel_label=self.with_style("quiet", fontSize=8, leading=11 + extra, spaceAfter=5),
            date=self.with_style("title", fontSize=11.5, leading=14 + extra,
                                 spaceBefore=0, spaceAfter=0),
            decision=self.with_style("label", fontSize=12, leading=15 + extra),
            meta=self.with_style("quiet", fontSize=8.5, leading=11 + extra),
        )
        for name in ("body", "decision", "meta"):
            ink = self.styles[name].textColor
            if contrast(ink, self.design.answer_tint) < 4.5:
                ink = self.design.answer_text
            self.styles[f"card_{name}"] = self.with_style(name, textColor=ink)

    def label(self, value, **values):
        return translate(self.language, value, **values)

    def with_style(self, style, **overrides):
        return ParagraphStyle(f"LayoutC_{style}", parent=self.styles[style], **overrides)

    def text(self, value, style="body", field="a meeting label"):
        return paragraph(value, self.styles[style] if isinstance(style, str) else style, field)

    def card_text(self, value, style="body", field="a meeting label"):
        return self.text(value, f"card_{style}", field)

    def section(self, value):
        label = self.label(value)
        return self.text(label if self.rtl else label.upper(), "section")

    @property
    def meeting(self):
        return self.label("Weekly meeting {number}", number=self.view.week["number"])

    def top_line(self):
        project = self.text(self.view.project["project"], "project", "the project name")
        meeting_style = self.with_style("project", textColor=self.design.main_text)
        meeting = self.text(f"· {self.meeting}", meeting_style, "the meeting number")
        date_style = self.with_style("small", alignment=self.opposite_alignment)
        date = self.text(format_date(self.view.meeting, None, self.language), date_style, "the meeting date")
        meeting_width = min(line_width(meeting) + 5, self.width * .36)
        date_width = min(line_width(date) + 1, self.width * .36)
        project_width = min(line_width(project) + 3, self.width - date_width - meeting_width - 12)
        cells = [project, meeting, "", date]
        widths = [project_width, meeting_width, self.width - project_width - meeting_width - date_width,
                  date_width]
        if self.rtl:
            cells.reverse()
            widths.reverse()
        row = Table([cells], colWidths=widths, style=[
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ])
        if row.wrap(self.width, self.frame_height)[1] <= self.frame_height:
            return [row]
        # The heading can span pages when an exceptionally long name cannot fit in a cell.
        return [project, meeting, date]

    def header(self):
        story = [*self.top_line(), self.text(self.view.content["headline"], "title", "the headline")]
        people = []
        if self.view.project["client"]:
            people.append(self.label("Client: {name}", name=self.view.project["client"]))
        if self.view.attendees:
            separator = "، " if self.rtl else ", "
            people.append(self.label("Attendees: {names}", names=separator.join(self.view.attendees)))
        if people:
            story.append(self.text(" · ".join(people), "small", "the client and attendees"))
        story.append(Spacer(1, 17))
        return story

    def notices(self):
        story = []
        if not self.view.week["held"]:
            story.append(self.text(self.label(MEETING_UNRECORDED), "notice"))
        for notice in missed_meeting_notices(self.view):
            story.append(self.text(notice, "quiet"))
        return story

    def carryovers(self):
        story = []
        for heading, rows in carryover_sections(self.view):
            story.append(self.text(heading, "label"))
            for title, details in rows:
                story.append(self.text(title, "label", heading))
                story.extend(self.text(detail, "quiet", heading) for detail in details)
        return story

    def checklist(self, items, empty, *, finished=False):
        rows = [ChecklistRow(self, self.text(text, field="a checklist item"), finished) for text in items]
        return rows or [self.text(self.label(empty), "quiet")]

    def panel(self, flowables):
        return Panel(self, flowables, "track")

    def card(self, flowables, *, padding=10):
        return Panel(self, flowables, "decision", padding=padding)

    def needs(self):
        title = self.label("What we need from the client")
        rows = []
        for index, need in enumerate(self.view.content["needs"], 1):
            due = f" · {need_due(self.view, need)}" if "by" in need else ""
            rows.append(self.text(need["text"] + due, field=f"need {index}"))
        return Panel(self, [self.text(title, "label"), *(rows or [self.text(self.label(NO_NEEDS), "quiet")])],
                     "needs")

    def columns(self, left, right):
        return Columns(self, left, right)

    def footer(self, canvas, doc):
        width, height = doc.pagesize
        colors = self.design.colors
        canvas.setFillColor(colors["background"])
        canvas.rect(0, 0, width, height, stroke=0, fill=1)
        canvas.setStrokeColor(colors["lines"])
        canvas.line(MARGIN_C, 33, width - MARGIN_C, 33)
        number_label = self.label("Page {number}", number=doc.page)
        number_style = self.with_style("small", alignment=self.opposite_alignment, fontSize=8, leading=10)
        page = self.text(number_label, number_style, "the PDF page number")
        page_width = line_width(page) + 1
        page.wrap(page_width, 24)
        page.drawOn(canvas, MARGIN_C if self.rtl else width - MARGIN_C - page_width, 17)
        label = f"{self.view.project['project']} · {self.meeting}"
        footer = self.text(label, "footer_project", "the PDF footer")
        project_width = self.width - page_width - 12
        if line_width(footer) > project_width:
            # Keep unusually long project names in the frame, over at most two lines.
            shorter = self.with_style("footer_project", fontSize=7, leading=8)
            footer = self.text(label, shorter, "the PDF footer")
            while footer.wrap(project_width, 24)[1] > 16:
                project, _, _ = label.rpartition(" · ")
                shortened = project[:len(project) // 2].rstrip(" .")
                label = f"{shortened}... · {self.meeting}"
                footer = self.text(label, shorter, "the PDF footer")
        _, footer_height = footer.wrap(project_width, 24)
        footer.drawOn(canvas, width - MARGIN_C - project_width if self.rtl else MARGIN_C,
                      27 - footer_height)


class SignatureLines(Flowable):
    def __init__(self, layout, paper_required):
        super().__init__()
        self.layout = layout
        self.signature_width_fraction = .38
        signature = layout.label("Client signature")
        if paper_required and layout.design.pdf_layout == PDF_LAYOUT_C_REVISED:
            signature = layout.label("Client signature · needed because the delivery date moved")
            self.signature_width_fraction = .48
        elif paper_required:
            signature += " · " + layout.label("Paper signature")
        self.labels = [layout.text(signature, "small"), layout.text(layout.label("Date"), "small")]

    def wrap(self, width, height):
        self.width = width
        self.field_widths = (width * self.signature_width_fraction, width * .22)
        self.label_heights = [label.wrap(field_width, height)[1]
                              for label, field_width in zip(self.labels, self.field_widths)]
        self.height = 23 + max(self.label_heights)
        return self.width, self.height

    def draw(self):
        canvas = self.canv
        canvas.setStrokeColor(self.layout.design.colors["text"])
        canvas.setLineWidth(.65)
        offset = 0
        for label, height, width in zip(self.labels, self.label_heights, self.field_widths):
            x = self.width - offset - width if self.layout.rtl else offset
            line = self.height - 18
            canvas.line(x, line, x + width, line)
            label.drawOn(canvas, x, line - 4 - height)
            offset += width + 28
