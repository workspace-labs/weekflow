# Adapted from checkflow, originally from workflow-project's script.py, under the MIT terms in LICENSE.
"""Arabic text, ready to draw: letters joined, and the line put in the order it sits on the page.

reportlab draws a string left to right, one glyph per character, and joins nothing. So this file does
the two jobs a text engine would do, with nothing but the Unicode tables Python ships with:

  1. joining: every Arabic letter is swapped for its start, middle, end or alone shape (and lam + alef
     for their one combined shape), taken from Unicode's own "presentation forms" (a letter standing alone stays the plain letter);
  2. ordering: Arabic runs right to left, while a number or a run of Latin words inside it keeps its
     own left-to-right order.

It knows nothing about fonts, pages or reportlab.
"""

import re
import unicodedata
from itertools import chain

_SHAPES = ("isolated", "final", "initial", "medial")
_FORMS = {}        # one letter, or lam + alef  ->  {"isolated": ch, "final": ch, ...}
for _code in chain(range(0xFB50, 0xFE00), range(0xFE70, 0xFEFD)):
    _parts = unicodedata.decomposition(chr(_code)).split()
    if not _parts or _parts[0][1:-1] not in _SHAPES:
        continue
    _letters = "".join(chr(int(p, 16)) for p in _parts[1:])
    if len(_letters) != 1 and _letters not in ("لا", "لأ", "لإ", "لآ"):
        continue
    _FORMS.setdefault(_letters, {})[_parts[0][1:-1]] = chr(_code)
_FORMS["ـ"] = dict.fromkeys(_SHAPES, "ـ")
_FORMS["\u200d"] = dict.fromkeys(_SHAPES, "\u200d")  # A joiner behaves like an invisible tatweel.
_NON_DRAWING = {"\u200c", "\u200d"}
REQUIRED_GLYPHS = frozenset(
    glyph for letter, shapes in _FORMS.items() if "ء" <= letter[0] <= "ي"
    for glyph in (*shapes.values(), *letter)
) | frozenset("0123456789ءًٌٍَُِّْ،؛؟")

_BRACKETS = {"(": ")", "[": "]", "{": "}", "<": ">", "«": "»"}
_MIRRORED = {**_BRACKETS, **{end: start for start, end in _BRACKETS.items()}}
_BETWEEN_DIGITS = ".,:/-٫٬"
_FILE_OR_FLAG = re.compile(r"(?:\.{1,2}/|--?|\.)[a-zA-Z](?:[a-zA-Z0-9_./-]*[a-zA-Z0-9_])?")
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


DIRECTION_MARKS = str.maketrans("", "", "\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e"
                                "\u2066\u2067\u2068\u2069")


def display(text):
    """Use Western digits and remove bidi controls before manual layout."""
    return unicodedata.normalize("NFC", text).translate(_DIGITS).translate(DIRECTION_MARKS)


def is_latin(character):
    return "LATIN" in unicodedata.name(character, "")


def is_mark(ch):
    """True for a vowel mark or shadda, positioned independently of its letter."""
    return unicodedata.combining(ch) != 0


class _Unit:
    """One letter as drawn (already in its joined shape), the marks on it, and where it came from."""

    def __init__(self, text, index):
        self.text = text
        self.marks = []            # [(mark, its place in the original text)]
        self.index = index
        self.kind = ""             # "R" Arabic, "L" Latin, "N" number, "" not yet decided


def _units(text):
    """The text as joined letters, still in reading order."""
    units, i = [], 0
    while i < len(text):
        ch = text[i]
        if is_mark(ch) and units and units[-1].text in _FORMS:
            units[-1].marks.append((ch, i))
        else:
            unit = _Unit(ch, i)
            if ch == "ل":
                end = i + 1
                while end < len(text) and is_mark(text[end]):
                    end += 1
                if ch + text[end:end + 1] in ("لا", "لأ", "لإ", "لآ"):
                    unit.text += text[end]
                    unit.marks = [(text[k], k) for k in range(i + 1, end)]
                    i = end
            units.append(unit)
        i += 1

    def forms(k):
        return _FORMS.get(units[k].text, {}) if 0 <= k < len(units) else {}

    shapes = []
    for k in range(len(units)):
        mine = forms(k)
        if not mine:
            shapes.append(None)
            continue
        before = "initial" in forms(k - 1) and "final" in mine     # the letter before reaches forward
        after = "initial" in mine and "final" in forms(k + 1)      # this one reaches the next
        shapes.append("medial" if before and after else "final" if before else "initial" if after else "isolated")
    for unit, shape in zip(units, shapes):
        if shape:
            if shape == "isolated" and len(unit.text) == 1:
                continue        # an alone letter is the plain letter: every Arabic font has it
            unit.text = _FORMS[unit.text].get(shape) or (unit.text if len(unit.text) == 1 else _FORMS[unit.text]["isolated"])
    return units


def _resolve_brackets(units):
    """Give matching brackets one direction, including next to an inline Latin run."""
    stack = []
    strong = "R"
    for index, unit in enumerate(units):
        if unit.text in _BRACKETS:
            stack.append((unit.text, index, strong))
        elif stack and unit.text == _BRACKETS[stack[-1][0]]:
            _, start, preceding = stack.pop()
            inside = {element.kind for element in units[start + 1:index]}
            kind = "L" if preceding == "L" and "L" in inside and "R" not in inside else "R"
            units[start].kind = unit.kind = kind
        if unit.kind in ("R", "L"):
            strong = unit.kind


def _decide(units, source):
    """Marks every unit Arabic (R), Latin (L) or number (N); what lies between takes its neighbours' side."""
    for k, unit in enumerate(units):
        kind = unicodedata.bidirectional(source[unit.index])
        if kind in ("R", "AL"):
            unit.kind = "R"
        elif kind == "L":
            unit.kind = "L"
        elif kind in ("EN", "AN"):
            unit.kind = "N"
    for k, unit in enumerate(units):
        if k and k + 1 < len(units) and not unit.kind and unit.text in _BETWEEN_DIGITS:
            if units[k - 1].kind == units[k + 1].kind == "N":
                unit.kind = "N"
        if (k + 1 < len(units) and unit.text in "+−-" and units[k + 1].kind == "N"
                and (k == 0 or units[k - 1].text.isspace() or units[k - 1].text in _BRACKETS)):
            unit.kind = "N"
    file_or_flag = {index for match in _FILE_OR_FLAG.finditer(source)
                    for index in range(*match.span())}
    for unit in units:
        if unit.index in file_or_flag:
            unit.kind = "L"
    strong = "R"
    for unit in units:                          # a number after a Latin word belongs to it ("Part 2")
        if unit.kind in ("R", "L"):
            strong = unit.kind
        elif unit.kind == "N" and strong == "L":
            unit.kind = "L"
    _resolve_brackets(units)
    k = 0
    while k < len(units):                       # spaces and punctuation: Latin only between two Latin sides
        if units[k].kind:
            k += 1
            continue
        end = k
        while end < len(units) and not units[end].kind:
            end += 1
        left = units[k - 1].kind if k else "R"
        right = units[end].kind if end < len(units) else "R"
        for unit in units[k:end]:
            unit.kind = "L" if left == right == "L" else "R"
        k = end


def visual(text):
    """The text as it is drawn, left to right, in a right-to-left line.

    Returns [(character, its place in the original text)]. A mark comes just before the letter it
    sits on, so whoever draws it knows which letter that is.
    """
    units = _units(text)
    _decide(units, text)
    out, k = [], len(units)
    while k > 0:
        end = k
        k -= 1
        if units[k].kind == "R":
            unit = units[k]
            out += unit.marks
            out.append((_MIRRORED.get(unit.text, unit.text), unit.index))
            continue
        while k > 0 and units[k - 1].kind != "R":
            k -= 1
        for unit in units[k:end]:               # Latin words and numbers keep their own order
            out.append((unit.text, unit.index))
            out += unit.marks
    return [(character, index) for character, index in out if character not in _NON_DRAWING]
