"""Place delivery dates by elapsed days and keep their labels clear of each other."""

from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import Flowable

from .meeting_design import PDF_LAYOUT_C
from .page import day_count
from .pdf_layout_c import line_width


DOT_INSET = 7
LABEL_GAP = 8
MARKER_CLEARANCE = 12
MIN_MOVE_SHARE = .25
BREAK_HALF_WIDTH = 8


def date_track_positions(days, label_widths, width, *, rtl=False, original=False):
    """Return dot and label positions in input order, and the optional break position."""
    start, end = min(days), max(days)
    span = width - 2 * DOT_INSET
    dots = [DOT_INSET + span * (day - start) / (end - start or 1) for day in days]
    order = sorted(range(len(days)), key=days.__getitem__)
    break_at = None if original else adjust_marker_positions(dots, days, order, span)
    halves = [label_width / 2 for label_width in label_widths]
    centers = list(dots)
    left = 0
    for index in order:
        centers[index] = max(centers[index], left + halves[index])
        left = centers[index] + halves[index] + LABEL_GAP
    right = width
    for index in reversed(order):
        centers[index] = min(centers[index], right - halves[index])
        right = centers[index] - halves[index] - LABEL_GAP
    if rtl:
        dots = [width - x for x in dots]
        centers = [width - x for x in centers]
        if break_at is not None:
            break_at = width - break_at
    return tuple(dots), tuple(centers), break_at


def adjust_marker_positions(dots, days, order, span):
    if len(dots) == 2:
        if dots[0] == dots[1]:
            dots[1] += MARKER_CLEARANCE
        return None

    first, middle, last = order
    start, end = dots[first], dots[last]
    minimum_move = MIN_MOVE_SHARE * span
    squeezed = abs(days[2] - days[1]) < MIN_MOVE_SHARE * (days[last] - days[first])
    if squeezed:
        # Today is outside the moved dates. Give the move more room by
        # shortening the grey segment next to today, whichever side it sits on.
        dots[middle] = end - minimum_move if first == 0 else start + minimum_move

    dots[middle] = min(max(dots[middle], start + MARKER_CLEARANCE), end - MARKER_CLEARANCE)
    return (dots[0] + dots[middle]) / 2 if squeezed else None


class DateTrack(Flowable):
    original = False

    def __init__(self, layout):
        super().__init__()
        self.layout = layout
        view = layout.view
        moved = (view.end_after - view.end_before).days
        self.dates = [view.meeting, view.end_before]
        captions = [layout.label("today"), layout.label("on time")]
        if moved:
            days = day_count(abs(moved), layout.language)
            captions[1] = layout.label("planned")
            sign = "+" if moved > 0 else "-"
            captions.append(layout.label("now, {days}", days=sign + days))
            self.dates.append(view.end_after)
        self.days = [value.toordinal() for value in self.dates]
        self.moved = bool(moved)
        date_style = layout.with_style("date", alignment=TA_CENTER)
        final_style = layout.with_style("date", alignment=TA_CENTER, textColor=layout.design.main_text)
        caption_style = layout.with_style("meta", alignment=TA_CENTER)
        self.labels = [
            (layout.text(view.date_text(value), final_style if index == len(self.dates) - 1 else date_style,
                         "a delivery track date"), layout.text(caption, caption_style))
            for index, (value, caption) in enumerate(zip(self.dates, captions))
        ]

    def wrap(self, width, height):
        self.width = width
        largest = (width - LABEL_GAP * (len(self.labels) - 1)) / len(self.labels)
        self.label_widths = [min(largest, max(line_width(date), line_width(caption)) + 1)
                             for date, caption in self.labels]
        self.dots, self.centers, self.break_at = date_track_positions(
            self.days, self.label_widths, width, rtl=self.layout.rtl, original=self.original,
        )
        self.date_heights = [date.wrap(label_width, height)[1]
                             for (date, _), label_width in zip(self.labels, self.label_widths)]
        self.caption_heights = [caption.wrap(label_width, height)[1]
                                for (_, caption), label_width in zip(self.labels, self.label_widths)]
        self.track_y = max(self.caption_heights) + 16
        self.height = self.track_y + 13 + max(self.date_heights)
        return width, self.height

    def draw(self):
        canvas = self.canv
        y = self.track_y
        self.draw_axis(canvas, self.layout.design.colors, y)

        for (date, caption), width, center, caption_height in zip(
                self.labels, self.label_widths, self.centers, self.caption_heights):
            left = center - width / 2
            date.drawOn(canvas, left, y + 13)
            caption.drawOn(canvas, left, y - 16 - caption_height)

    def draw_axis(self, canvas, colors, y):
        canvas.saveState()
        canvas.setLineCap(1)
        canvas.setLineWidth(2.7)
        canvas.setStrokeColor(colors["lines"])
        if self.break_at is None:
            canvas.line(DOT_INSET, y, self.width - DOT_INSET, y)
        else:
            canvas.line(DOT_INSET, y, self.break_at - BREAK_HALF_WIDTH, y)
            canvas.line(self.break_at + BREAK_HALF_WIDTH, y, self.width - DOT_INSET, y)
            canvas.setStrokeColor(colors["quiet"])
            canvas.setLineWidth(1.1)
            slant = -2 if self.layout.rtl else 2
            canvas.lines([(x - slant, y - 3.5, x + slant, y + 3.5)
                          for x in (self.break_at - 3, self.break_at + 3)])
            canvas.setLineWidth(2.7)
        if self.moved:
            canvas.setStrokeColor(colors["main"])
            canvas.line(self.dots[1], y, self.dots[2], y)

        for index, dot in enumerate(self.dots):
            ink = colors["quiet"] if index == 0 else colors["main"]
            canvas.setStrokeColor(ink)
            canvas.setLineWidth(1.9 if index == 0 else 2.3)
            canvas.setFillColor(ink if index == len(self.dots) - 1 else colors["background"])
            canvas.circle(dot, y, 3.5 if index == 0 else 4.5, stroke=1, fill=1)
        canvas.restoreState()


class OriginalDateTrack(DateTrack):
    """Rebuild the first Layout C PDFs with the exact earlier drawing commands."""

    original = True

    def draw_axis(self, canvas, colors, y):
        canvas.saveState()
        canvas.setLineCap(1)
        canvas.setLineWidth(2.7)
        canvas.setStrokeColor(colors["lines"])
        canvas.line(DOT_INSET, y, self.width - DOT_INSET, y)
        if self.moved:
            canvas.setStrokeColor(colors["main"])
            canvas.line(self.dots[1], y, self.dots[2], y)

        positions = tuple(-dot for dot in self.dots) if self.layout.rtl else self.dots
        order = sorted(range(len(positions)), key=positions.__getitem__)
        offsets = [0] * len(order)
        for previous, current in zip(order, order[1:]):
            if positions[current] - positions[previous] < MARKER_CLEARANCE:
                offsets[previous] = -MARKER_CLEARANCE / 2
                offsets[current] = MARKER_CLEARANCE / 2
        marks = zip(self.dots, self.centers, offsets, self.label_widths)
        for index, (dot, center, offset, label_width) in enumerate(marks):
            last = index == len(self.dots) - 1
            ink = colors["quiet"] if index == 0 else colors["main"]
            canvas.setStrokeColor(ink)
            if abs(center - dot) > label_width / 2 or offset:
                canvas.setLineWidth(.55)
                canvas.line(dot, y + offset, center, y + 10)
            canvas.setLineWidth(1.9 if index == 0 else 2.3)
            canvas.setFillColor(ink if last else colors["background"])
            canvas.circle(dot, y + offset, 3.5 if index == 0 else 4.5, stroke=1, fill=1)
        canvas.restoreState()


def delivery_panel(layout):
    title = layout.label("Delivery date")
    track = OriginalDateTrack if layout.design.pdf_layout == PDF_LAYOUT_C else DateTrack
    return layout.panel([layout.text(title if layout.rtl else title.upper(), "panel_label"), track(layout)])
