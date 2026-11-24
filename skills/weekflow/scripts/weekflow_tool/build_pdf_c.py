"""Lay out the build meeting's client copy in Layout C."""

from datetime import date

from reportlab.platypus import Spacer, Table

from .client_pdf import answer_badge, running_table
from .page import ANSWERS, HEADINGS, NO_DECISIONS, NO_FINISHED, NO_NEXT_WEEK, day_count
from .pdf_date_track import delivery_panel
from .screen_pdf import screen_map_story


def decision_card(layout, change, answer, charged_days):
    change_id = change["id"]
    view = layout.view
    answer_label = layout.label(dict(ANSWERS).get(answer, "Not decided"))
    badge = answer_badge(answer, answer_label, layout.styles["cell"], layout.design,
                         layout.styles["label"].fontName, on_paper=True, radius=layout.badge_radius)
    days = day_count(change["days_added"], layout.language)
    if charged_days:
        days = f'{layout.label("Date moved")} · {days}'
    days = layout.card_text(days, "meta")
    status, widths = [badge, days], [badge.minWidth() + 6, None]
    if layout.rtl:
        status.reverse()
        widths.reverse()
    summary = Table([status], colWidths=widths, style=[
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ])
    raised = layout.label("Raised by {name} on {date}.", name=change["asked_by"],
                          date=view.date_text(date.fromisoformat(change["date"])))
    return layout.card([
        layout.card_text(change_id, "meta"),
        layout.card_text(change["what"], "decision", f"the decision {change_id}"),
        layout.card_text(change["reason"], field=f"the reason for {change_id}"),
        Spacer(1, 3), summary,
        layout.card_text(raised, "meta", f"who raised {change_id}"),
    ])


def story_for_build_c(view, layout):
    left = [
        layout.section(HEADINGS[1]),
        *layout.checklist((item["text"] for item in view.content["finished"]), NO_FINISHED, finished=True),
        *layout.carryovers(),
        layout.section(HEADINGS[3]),
        *layout.checklist((item["text"] for item in view.content["next_week"]), NO_NEXT_WEEK),
    ]
    cards = [decision_card(layout, change, answer, days) for change, answer, days, _ in view.running_decisions()]
    right = [layout.section(HEADINGS[2]),
             *(cards or [layout.text(layout.label(NO_DECISIONS), "quiet")]), layout.needs()]
    screen_map = screen_map_story(view, layout.styles)
    return [
        *layout.header(), delivery_panel(layout), *layout.notices(),
        *([Spacer(1, 12), *screen_map] if screen_map else []),
        layout.columns(left, right), layout.section(HEADINGS[4]),
        running_table(view, layout.styles, layout.width, layout=layout),
    ]
