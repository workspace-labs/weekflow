"""ReportLab blocks for the Layout C page and its single-column continuation."""

from bisect import bisect_right

from reportlab.platypus import Flowable


def stack_positions(flowables, width, height):
    positions = []
    used = after = 0
    for flowable in flowables:
        if positions:
            used += max(after, flowable.getSpaceBefore())
        used += flowable.wrap(width, height)[1]
        positions.append(used)
        after = flowable.getSpaceAfter()
    return positions


def draw_stack(canvas, flowables, positions, x, top):
    for flowable, offset in zip(flowables, positions):
        flowable.drawOn(canvas, x, top - offset)


class Panel(Flowable):
    def __init__(self, layout, content, kind, *, padding=10):
        super().__init__()
        self.layout = layout
        self.content = content
        self.kind = kind
        self.inset = 18 if kind == "track" else 14
        self.padding = 14 if kind == "track" else padding
        self.spaceBefore = 10 if kind == "needs" else 0
        self.spaceAfter = 8 if kind == "decision" else 0

    def wrap(self, width, height):
        self.width = width
        self.positions = stack_positions(self.content, width - 2 * self.inset, height)
        self.height = self.positions[-1] + 2 * self.padding
        return self.width, self.height

    def split(self, width, height):
        if self.height <= self.layout.frame_height:
            return []
        if self.kind == "needs":
            count = bisect_right(self.positions, height - 2 * self.padding)
            if count >= 2:
                return [Panel(self.layout, part, self.kind, padding=self.padding)
                        for part in (self.content[:count], self.content[count:])]
        # An unusually long group can flow as text instead of becoming an unprintable box.
        first, *rest = self.content
        if first.wrap(width, height)[1] <= height:
            return self.content
        parts = first.split(width, height)
        return [*parts, *rest] if parts else []

    def draw(self):
        canvas = self.canv
        design = self.layout.design
        colors = design.colors
        radius = min(design.radius * .375, self.height / 2, self.width / 2)
        canvas.saveState()
        if self.kind == "needs":
            canvas.setStrokeColor(colors["main"])
            canvas.setLineWidth(1)
            canvas.setDash(3, 2)
            canvas.roundRect(0, 0, self.width, self.height, radius, stroke=1, fill=0)
        elif self.kind == "decision":
            # Round the outer corners while the reading edge stays straight.
            edge = self.width - 4 if self.layout.rtl else 0
            square = self.width - radius if self.layout.rtl else 0
            canvas.setFillColor(design.answer_tint)
            canvas.roundRect(0, 0, self.width, self.height, radius, stroke=0, fill=1)
            canvas.rect(square, 0, radius, self.height, stroke=0, fill=1)
            canvas.setFillColor(colors["main"])
            canvas.rect(edge, 0, 4, self.height, stroke=0, fill=1)
        else:
            canvas.setFillColor(colors["card"])
            canvas.roundRect(0, 0, self.width, self.height, radius, stroke=0, fill=1)
        canvas.restoreState()
        draw_stack(canvas, self.content, self.positions, self.inset, self.height - self.padding)


class Columns(Flowable):
    gap = 22
    spaceBefore = 17

    def __init__(self, layout, left, right):
        super().__init__()
        self.layout = layout
        self.left, self.right = left, right

    def wrap(self, width, height):
        self.width = width
        usable = width - self.gap
        self.left_width = usable * .5238
        self.right_width = usable - self.left_width
        self.left_positions = stack_positions(self.left, self.left_width, height)
        self.right_positions = stack_positions(self.right, self.right_width, height)
        self.height = max(self.left_positions[-1], self.right_positions[-1])
        return self.width, self.height

    def split(self, width, height):
        opening = self.left[:2]
        opening_height = stack_positions(opening, width, height)[-1]
        if opening_height <= height:
            return [*self.left, *self.right]
        # Keep the section heading with the start of the list. A single very long
        # opening item can begin here if it can split in the space left.
        heading, first = opening
        remaining = height - heading.wrap(width, height)[1] - first.getSpaceBefore()
        if remaining > 0 and first.split(width, remaining):
            return [*self.left, *self.right]
        return []

    def draw(self):
        if self.layout.rtl:
            left_x, right_x = self.right_width + self.gap, 0
        else:
            left_x, right_x = 0, self.left_width + self.gap
        draw_stack(self.canv, self.left, self.left_positions, left_x, self.height)
        draw_stack(self.canv, self.right, self.right_positions, right_x, self.height)


class ChecklistRow(Flowable):
    inset = 19
    padding = 4

    def __init__(self, layout, text, finished, *, first=True):
        super().__init__()
        self.layout = layout
        self.text = text
        self.finished = finished
        self.first = first

    def wrap(self, width, height):
        self.width = width
        self.height = self.text.wrap(width - self.inset, height)[1] + 2 * self.padding
        return self.width, self.height

    def split(self, width, height):
        parts = self.text.split(width - self.inset, height - 2 * self.padding)
        return [type(self)(self.layout, part, self.finished, first=self.first and index == 0)
                for index, part in enumerate(parts)]

    def draw(self):
        canvas = self.canv
        design = self.layout.design
        colors = design.colors
        rtl = self.layout.rtl
        canvas.saveState()
        canvas.setStrokeColor(colors["lines"])
        canvas.setLineWidth(.5)
        canvas.line(0, 0, self.width, 0)
        if self.first:
            x = self.width - 12 if rtl else 0
            y = self.height - self.padding - 12
            canvas.setLineWidth(1.35)
            canvas.setStrokeColor(colors["main"])
            canvas.setFillColor(colors["main"])
            canvas.roundRect(x + .7, y, 11, 11, min(design.radius * .2, 4),
                             stroke=1, fill=int(self.finished))
            if self.finished:
                canvas.setStrokeColor(colors["on-main"])
                canvas.lines([(x + 3, y + 5.6, x + 5.2, y + 3.6),
                              (x + 5.2, y + 3.6, x + 9.3, y + 8.2)])
        canvas.restoreState()
        self.text.drawOn(canvas, 0 if rtl else self.inset, self.padding)
