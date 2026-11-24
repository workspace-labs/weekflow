"""Find exact Arabic names and possible spellings in their original text."""

import re
from unicodedata import category, name as unicode_name, normalize

from .text_fields import ARABIC_LETTERS


# Conjunction, preposition and article. ل + ال may contract to لل.
PREFIX = r"[وف]?(?:[بلك]?(?:ال)?|لل)"
VOWEL_MARKS = dict.fromkeys(map(ord, (
    "ـ\u0618\u0619\u061a\u064b\u064c\u064d\u064e\u064f\u0650\u0651\u0652"
    "\u0656\u0657\u0659\u065a\u065b\u065c\u065d\u065e\u0670"
    "\u08e3\u08e4\u08e5\u08e6\u08e7\u08e8\u08e9\u08f0\u08f1\u08f2"
    "\u08f4\u08f5\u08f6\u08fe"
)))


def arabic_name_matcher(name):
    if any(char != "ـ" and char.isalpha() and unicode_name(char, "").startswith("ARABIC ")
           for char in name):
        return ArabicNameMatcher(name)


def is_mark(char):
    return category(char).startswith("M")


def is_format(char):
    return category(char) == "Cf"


def exact_spelling(value):
    # Canonical composition keeps a decomposed hamza distinct from a bare alef.
    return normalize("NFC", value.translate(VOWEL_MARKS))


def comparison_spans(value):
    """Project normalized characters back to their original text spans."""
    offsets = [index for index, char in enumerate(value) if not is_format(char)]
    visible = "".join(value[index] for index in offsets)
    parts, spans = [], []
    start = cluster_start = 0
    for end in range(1, len(visible) + 1):
        if end < len(visible) and is_mark(visible[end]):
            continue
        part = exact_spelling(normalize("NFKC", visible[cluster_start:end]))
        source_end = offsets[end - 1] + 1
        if part:
            parts.append(part)
            spans.extend([(offsets[start], source_end)] * len(part))
            start = end
        elif parts and (parts[-1][-1].isalnum() or parts[-1][-1] == "_" or is_mark(parts[-1][-1])):
            # Hang tatweel on its word, including when it trails the last letter.
            spans[-1] = (spans[-1][0], source_end)
            start = end
        cluster_start = end
    return "".join(parts), spans


class ArabicNameMatcher:
    def __init__(self, name):
        self.exact = exact_spelling(name)
        comparable, _ = comparison_spans(name)
        comparable = re.escape(comparable.translate(ARABIC_LETTERS))
        self.pattern = re.compile(rf"(?<!\w){PREFIX}{comparable}(?!\w)")

    def matches(self, value):
        spelling, spans = comparison_spans(value)
        for match in self.pattern.finditer(spelling.translate(ARABIC_LETTERS)):
            start, end = match.span()
            # Marks that distinguish the spelling are part of the word boundary.
            if (start and is_mark(spelling[start - 1])) or (end < len(spelling) and is_mark(spelling[end])):
                continue
            left, right = spans[start][0], spans[end - 1][1]
            # A compatibility character can expand into more than one word.
            if (start and spans[start - 1][1] > left) or (end < len(spans) and spans[end][0] < right):
                continue
            while left and is_format(value[left - 1]):
                left -= 1
            while right < len(value) and is_format(value[right]):
                right += 1
            yield left, right, exact_spelling(value[left:right]) == self.exact
