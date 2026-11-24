"""Compose a docs meeting in Layout C."""

from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import Flowable, Table

from .docs_pdf import decisions_table
from .docs_presentation import (
    DECIDE_NEXT_WEEK, DELIVERY_NOTE, NO_SENTENCES, SCOPE_NOTE, SETTLED_HEADING,
    inline_answer, sentence_parts, stage_steps,
)
from .page import HEADINGS, NO_DECISIONS, NO_NEXT_WEEK


class StageLine(Flowable):
    """Mark the four stage columns in their reading order."""

    def __init__(self, steps, design, rtl):
        super().__init__()
        self.steps = steps
        self.colors = design.colors
        self.rtl = rtl

    def wrap(self, width, height):
        self.width = width
        self.height = 14
        return width, self.height

    def draw(self):
        canvas = self.canv
        span = self.width / len(self.steps)
        positions = [(index + 0.5) * span for index in range(len(self.steps))]
        if self.rtl:
            positions = [self.width - position for position in positions]
        y = self.height / 2
        canvas.setStrokeColor(self.colors["lines"])
        canvas.setLineWidth(2.5)
        canvas.line(positions[0], y, positions[-1], y)
        canvas.setLineWidth(1.25)
        for x, (_, _, current) in zip(positions, self.steps):
            canvas.setStrokeColor(self.colors["main"] if current else self.colors["quiet"])
            canvas.setFillColor(self.colors["main"] if current else self.colors["card"])
            canvas.circle(x, y, 4, stroke=1, fill=1)


def stage_panel(view, layout):
    """Keep the stage text aligned with its marker as labels wrap."""
    label = layout.label
    left = view.decisions_left
    summary = f'{label("Left to decide")}: {left}' if left else label("All decided")
    summary_style = layout.with_style("date", textColor=layout.design.main_text,
                                      alignment=layout.opposite_alignment)
    heading = label("Meeting stages")
    title = layout.text(heading if layout.rtl else heading.upper(), "panel_label")
    top = [title, layout.text(summary, summary_style, "the decisions left")]
    steps = tuple(stage_steps(view.content, view.language))
    step_styles = {name: layout.with_style(name, alignment=TA_CENTER)
                   for name in ("label", "small", "meta")}
    cells = []
    for title, status, current in steps:
        name = "label" if current else "small"
        cell = [layout.text(title, step_styles[name], "a meeting stage")]
        if status:
            cell.append(layout.text(status, step_styles["meta"], "a meeting stage status"))
        cells.append(cell)
    if layout.rtl:
        top.reverse()
        cells.reverse()

    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]
    return layout.panel([
        Table([top], colWidths=["50%", "50%"], style=style),
        StageLine(steps, layout.design, layout.rtl),
        Table([cells], colWidths=["25%"] * len(steps), style=[
            *style, ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]),
        layout.text(label(DELIVERY_NOTE), "meta"),
    ])


def story_for_docs_c(view, layout):
    content = view.content
    language = view.language
    text = layout.text
    label = layout.label
    card_text = layout.card_text

    decisions = list(view.running_docs_decisions())
    answers = {decision["id"]: answer for decision, answer, _ in decisions}

    def inline(decision_id):
        return inline_answer(answers.get(decision_id), language)

    reading = [layout.section(HEADINGS[1])]
    if not content["document"]:
        reading.append(text(label(NO_SENTENCES), "quiet"))
    for section in content["document"]:
        reading.append(text(section["title"], "label", "a document section"))
        for sentence in section["sentences"]:
            visible = "".join(sentence_parts(sentence["text"], inline))
            reading.append(text(visible, field="a document sentence"))
    reading.extend(layout.carryovers())
    reading.append(layout.section(HEADINGS[3]))
    reading.extend(layout.checklist([item["text"] for item in content["next_week"]], NO_NEXT_WEEK))

    agenda = [layout.section(HEADINGS[2])]
    if not decisions:
        agenda.append(text(label(NO_DECISIONS), "quiet"))
    for decision, _, _ in decisions:
        decision_id = decision["id"]
        options = " · ".join((*decision["options"], label(DECIDE_NEXT_WEEK)))
        card = [
            card_text(decision["question"], "decision", f"the question for {decision_id}"),
            card_text(decision["why"], field=f"why for {decision_id}"),
        ]
        for account in decision.get("said", ()):
            account_text = f'{account["who"]} · {account["what"]}'
            card.append(card_text(account_text, "meta", f"what was said for {decision_id}"))
        card.append(card_text(options, "meta", f"options for {decision_id}"))
        agenda.append(layout.card(card, padding=8))
    settled = content.get("settled", ())
    if settled:
        agenda.append(text(label(SETTLED_HEADING), "label"))
        agenda.extend(text(question, field="a settled question") for question in settled)
    agenda.append(layout.needs())

    return [
        *layout.header(),
        stage_panel(view, layout),
        *layout.notices(),
        layout.columns(reading, agenda),
        layout.section(HEADINGS[4]),
        text(label(SCOPE_NOTE), layout.with_style("meta", keepWithNext=True), "the scope note"),
        decisions_table(view, layout.styles, layout.width, badge_radius=layout.badge_radius),
    ]
