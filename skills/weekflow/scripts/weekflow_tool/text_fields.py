"""Keep single-line meeting fields on one line."""

import re
import unicodedata

from .storage import Refusal


ARABIC_LETTERS = str.maketrans("أإآٱىؤئةیک", "اااايويهيك")
WESTERN_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
LATIN_NAME_PART = re.compile(r"[^\W_]+(?:[.'’+&-][^\W_]+)*[+#]*")
NAME_PARTICLES = {"al", "bin", "da", "de", "del", "der", "ibn", "la", "van", "von"}


def one_line(value):
    return " ".join(value.split())


def required_text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise Refusal(f"Fill in {label} in the meeting content file.")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise Refusal(f"Use valid text for {label} in the meeting content file.") from None
    return one_line(value)


def without_direction_marks(value):
    return "".join(char for char in value if unicodedata.category(char) != "Cf")


def arabic_words(value):
    """Normalize spelling for structural comparisons only, never for display."""
    text = without_direction_marks(unicodedata.normalize("NFKC", value))
    return "".join(char for char in text if char != "ـ" and not unicodedata.combining(char)).translate(
        ARABIC_LETTERS).translate(WESTERN_DIGITS)


def _latin_comparison(value):
    return one_line(without_direction_marks(unicodedata.normalize("NFKC", value)))


def _is_latin(char):
    return bool(char and "LATIN" in unicodedata.name(char, ""))


def read_latin_names(values):
    if not isinstance(values, list):
        raise Refusal("Write latin_names as a list of exact tool or personal names in Latin letters.")
    names = []
    for value in values:
        name = required_text(value, "a tool or personal name in latin_names")
        comparable = _latin_comparison(name)
        words = comparable.split()
        letters = [char for char in comparable if char.isalpha()]
        if (not all(LATIN_NAME_PART.fullmatch(word) for word in words)
                or not letters or not all(_is_latin(char) for char in letters)
                or len(words) > 1 and not all(word[0].isupper() or word in NAME_PARTICLES for word in words)):
            raise Refusal(f"Use an exact tool or personal name in latin_names, not a sentence: {name!r}.")
        if name not in names:
            names.append(name)
    return names


def validate_arabic_text(value, field, allowed_latin=()):
    """Reject foreign wording while leaving declared names and the input intact."""
    comparable = _latin_comparison(value)
    unrecognized = list(comparable)
    for name in {_latin_comparison(name) for name in allowed_latin if name}:
        if not any(_is_latin(char) for char in name):
            continue
        for match in re.finditer(rf"(?<!\w){re.escape(name)}(?!\w)", comparable):
            before = comparable[:match.start()].rstrip()[-1:]
            after = comparable[match.end():].lstrip()[:1]
            # A declaration must account for the whole Latin phrase. Reading
            # neighbors from the original prevents adjacent one-word entries
            # from assembling an English sentence.
            if not (_is_latin(before) or _is_latin(after)):
                unrecognized[match.start():match.end()] = " " * len(name)
    if any(char.isalpha() and "ARABIC" not in unicodedata.name(char, "") for char in unrecognized):
        raise Refusal(f"Write {field} in Arabic. Use Latin letters only for a tool or a personal name.")
    return value
