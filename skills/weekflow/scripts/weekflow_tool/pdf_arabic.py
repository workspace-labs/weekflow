# Arabic line flow adapted from checkflow under the MIT terms in LICENSE.
"""Wrap logical text, then shape and draw each line with local Arabic and Latin faces."""

from itertools import groupby
from unicodedata import bidirectional

from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import Flowable

from .arabic import display, is_latin, is_mark, visual
from .storage import Refusal


def drawable_runs(value, style, field):
    arabic = style.fontName
    latin = style.latinFont
    glyphs = {name: pdfmetrics.getFont(name).face.charToGlyph for name in (arabic, latin)}
    for character, _ in visual(value):
        code = ord(character)
        if is_latin(character):
            choices = (latin,)
        elif bidirectional(character) in ("R", "AL") or is_mark(character):
            choices = (arabic,)
        else:
            choices = (arabic, latin)
        for face in choices:
            if glyphs[face].get(code):
                yield face, character
                break
        else:
            if any(face.startswith("WeekflowFallback") for face in choices):
                yield latin, f"[U+{code:04X}]"
            else:
                raise Refusal(f"The PDF font cannot draw U+{code:04X} in {field}.")


def line_width(runs, size):
    return sum(pdfmetrics.stringWidth(text, font, size) for font, text in runs
               if len(text) > 1 or not is_mark(text))


def draw_line(canvas, x, y, runs, size):
    marks = []
    for font, group in groupby(runs, key=lambda item: item[0]):
        canvas.setFont(font, size)
        chunk = ""
        for _, character in group:
            if len(character) == 1 and is_mark(character):
                marks.append(character)
                continue
            if marks:
                if chunk:
                    canvas.drawString(x, y, chunk)
                    x += pdfmetrics.stringWidth(chunk, font, size)
                width = pdfmetrics.stringWidth(character, font, size)
                canvas.drawString(x + max(0, (width - 0.2 * size) / 2), y, "".join(marks))
                chunk = ""
                marks.clear()
            chunk += character
        if chunk:
            canvas.drawString(x, y, chunk)
            x += pdfmetrics.stringWidth(chunk, font, size)
        if marks:
            canvas.drawString(x, y, "".join(marks))
            marks.clear()


class ArabicParagraph(Flowable):
    """A paragraph with right-to-left lines and ReportLab's usual spacing inputs."""

    def __init__(self, value, style, field):
        super().__init__()
        self.value = display(value)
        self.style = style
        self.field = field

    def measure(self, value):
        runs = list(drawable_runs(value, self.style, self.field))
        return line_width(runs, self.style.fontSize)

    def minWidth(self):
        return max((self.measure(word) for word in self.value.split()), default=0)

    def _split_word(self, word, width):
        fragment = ""
        for character in word:
            if fragment and not is_mark(character) and self.measure(fragment + character) > width:
                yield fragment
                fragment = ""
            fragment += character
        if fragment:
            yield fragment

    def _wrap_line(self, source, width):
        line = ""
        for word in source.split():
            candidate = f"{line} {word}" if line else word
            if self.measure(candidate) <= width:
                line = candidate
                continue
            if line:
                yield line
            *fragments, line = self._split_word(word, width)
            yield from fragments
        yield line

    def wrap(self, width, height):
        self.width = width
        self.lines = [line for source in self.value.split("\n") for line in self._wrap_line(source, width)]
        self.height = len(self.lines) * self.style.leading
        return self.width, self.height

    def split(self, width, height):
        self.wrap(width, height)
        count = min(int(height / self.style.leading), len(self.lines) - 2)
        if count < 2:
            return []
        first, rest = self.lines[:count], self.lines[count:]
        opening = type(self)("\n".join(first), self.style, self.field)
        closing = type(self)("\n".join(rest), self.style, self.field)
        opening.spaceBefore = self.getSpaceBefore()
        closing.spaceAfter = self.getSpaceAfter()
        return [opening, closing]

    def draw(self):
        style, canvas = self.style, self.canv
        if style.backColor:
            padding = style.borderPadding
            canvas.setFillColor(style.backColor)
            canvas.rect(0, -padding, self.width, self.height + 2 * padding, stroke=0, fill=1)
        canvas.setFillColor(style.textColor)
        for index, line in enumerate(self.lines):
            runs = list(drawable_runs(line, style, self.field))
            x = 0
            if style.alignment == TA_RIGHT:
                x = self.width - line_width(runs, style.fontSize)
            elif style.alignment == TA_CENTER:
                x = (self.width - line_width(runs, style.fontSize)) / 2
            if style.backColor and style.alignment == TA_RIGHT:
                x -= style.borderPadding
            y = self.height - style.fontSize - index * style.leading
            draw_line(canvas, x, y, runs, style.fontSize)
