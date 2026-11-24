"""Read checked TrueType files and address frozen copies by their digest."""

from base64 import b64decode
from functools import lru_cache
from hashlib import sha256
from io import BytesIO
import os
from pathlib import Path
import re
from stat import S_ISREG
from struct import error as StructError, iter_unpack, unpack_from

from .storage import Refusal


FONT_DIR = Path(__file__).resolve().parents[2] / "assets" / "fonts"
FONT_LIMIT = 5 * 1024 * 1024
STUDIO_FAMILIES = {"heading": "Bricolage Grotesque", "text": "Instrument Sans"}
PROJECT_FAMILIES = {"heading": "Weekflow Meeting Heading", "text": "Weekflow Meeting Text"}
FONT_ROLES = {"heading": ("display", "title"), "text": ("body", "bold")}
ARABIC_FAMILY = "Noto Naskh Arabic"
ARABIC_ROLES = ("arabic-regular", "arabic-bold")
WEIGHTS = ("Regular", "Bold")
FROZEN_FONT_DIR = Path("docs/weekly/pages/fonts")
FROZEN_FONT_TARGET = re.compile(r"docs/weekly/pages/fonts/[0-9a-f]{64}\.ttf")
FONT_DIGEST = re.compile(r"[0-9a-f]{64}")
EMBEDDED_FACE = re.compile(
    rb'(@font-face \{font-family:"([^"\r\n]+)";font-weight:(400|700);src:url\("data:font/ttf;base64,)'
    rb'([A-Za-z0-9+/=]*)("\) format\("truetype"\);})'
)
FACE_ROLES = {(family.encode("ascii"), weight): role
              for families in (STUDIO_FAMILIES, PROJECT_FAMILIES)
              for usage, family in families.items()
              for weight, role in zip((b"400", b"700"), FONT_ROLES[usage])}
FACE_ROLES.update({(b"Meeting Arabic", weight): role
                   for weight, role in zip((b"400", b"700"), ARABIC_ROLES)})
FALLBACK_COMMENT = re.compile(
    rb"<!-- Studio font fallback ((?:(?:display|title|body|bold|arabic-regular|arabic-bold) )+)-->\n\Z"
)


class OversizedFile(ValueError):
    """A bounded read found more bytes than the file format allows."""


def frozen_font_path(digest):
    return FROZEN_FONT_DIR / f"{digest}.ttf"


def font_filename(family, weight):
    return f'{family.replace(" ", "")}-{weight}.ttf'


def read_regular(files, relative, limit=None):
    """Read a regular project file without accepting redirected path components."""
    path = files.path(relative)
    current = path
    while current != files.root:
        if current.is_symlink():
            raise ValueError("A design file path uses a link.")
        current = current.parent
    try:
        if not S_ISREG(path.stat().st_mode):
            raise ValueError("A design file must be a regular file.")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_NONBLOCK", 0)
        with os.fdopen(os.open(path, flags), "rb") as handle:
            status = os.fstat(handle.fileno())
            if not S_ISREG(status.st_mode):
                raise ValueError("A design file is unusable.")
            if limit is not None and status.st_size > limit:
                raise OversizedFile("A design file is over the size limit.")
            data = handle.read() if limit is None else handle.read(limit + 1)
    except FileNotFoundError:
        return None
    if limit is not None and len(data) > limit:
        raise OversizedFile("A design file is over the size limit.")
    return data


def embedded_fonts(page):
    for match in EMBEDDED_FACE.finditer(page):
        if (match[2], match[3]) not in FACE_ROLES:
            continue
        start, end = match.span(4)
        if 0 < end - start <= ((FONT_LIMIT + 2) // 3) * 4:
            try:
                data = b64decode(match[4], validate=True)
            except ValueError:
                continue
            if len(data) <= FONT_LIMIT:
                yield data


def replace_font_payloads(page, payloads):
    def substitute(match):
        role = FACE_ROLES.get((match[2], match[3]))
        if role not in payloads:
            return match[0]
        return match[1] + payloads[role] + match[5]

    return EMBEDDED_FACE.sub(substitute, page)


def with_font_fallback(markup, roles):
    if not roles:
        return markup
    return markup + "<!-- Studio font fallback " + " ".join(roles) + " -->\n"


def saved_font_fallback(page):
    match = FALLBACK_COMMENT.search(page)
    if match:
        return page[:match.start()], set(match[1].decode("ascii").split())
    return page, set()


def font_tables(data):
    signature, count = unpack_from(">4sH", data)
    if signature not in (b"\x00\x01\x00\x00", b"true"):
        raise ValueError("Expected a TrueType font.")
    directory_end = 12 + count * 16
    if directory_end > len(data):
        raise ValueError("Truncated TrueType directory.")
    tables = {}
    for name, _, offset, size in iter_unpack(">4sIII", data[12:directory_end]):
        if name in tables or offset < directory_end or offset + size > len(data):
            raise ValueError("Invalid TrueType table.")
        tables[name] = data[offset:offset + size]
    return tables


def checked_glyph_count(tables):
    glyph_count, = unpack_from(">H", tables[b"maxp"], 4)
    long_metrics, = unpack_from(">H", tables[b"hhea"], 34)
    loca_format, = unpack_from(">h", tables[b"head"], 50)
    if (not 0 < long_metrics <= glyph_count or loca_format not in (0, 1)
            or len(tables[b"hmtx"]) < (long_metrics + glyph_count) * 2
            or len(tables[b"name"]) < 6):
        raise ValueError("Invalid TrueType metrics.")
    loca_width = 2 if loca_format == 0 else 4
    loca = tables[b"loca"]
    end = (glyph_count + 1) * loca_width
    if len(loca) < end:
        raise ValueError("Truncated TrueType glyph locations.")
    last = 0
    for position, in iter_unpack(">H" if loca_format == 0 else ">I", loca[:end]):
        position *= 2 if loca_format == 0 else 1
        if not last <= position <= len(tables[b"glyf"]):
            raise ValueError("Invalid TrueType glyph location.")
        last = position
    return glyph_count


def unicode_subtable(cmap):
    version, count = unpack_from(">HH", cmap)
    entries_end = 4 + count * 8
    if version or entries_end > len(cmap):
        raise ValueError("Invalid TrueType character map.")
    selected = None
    for platform, encoding, offset in iter_unpack(">HHI", cmap[4:entries_end]):
        if (platform == 3 and encoding in (1, 10)) or (platform == 0 and encoding != 5):
            if not entries_end <= offset <= len(cmap) - 4:
                raise ValueError("Invalid TrueType character map offset.")
            selected = cmap[offset:]
    if selected is None:
        raise ValueError("Expected a Unicode character map.")
    return selected


def bmp_codepoints(cmap, glyph_count):
    length, _, segment_bytes = unpack_from(">HHH", cmap, 2)
    count = segment_bytes // 2
    ends, starts = 14, 16 + segment_bytes
    deltas, offsets = starts + segment_bytes, starts + segment_bytes * 2
    if not count or segment_bytes % 2 or not offsets + segment_bytes <= length <= len(cmap):
        raise ValueError("Invalid TrueType BMP character map.")
    last = -1
    for position in range(0, segment_bytes, 2):
        first, = unpack_from(">H", cmap, starts + position)
        end, = unpack_from(">H", cmap, ends + position)
        delta, = unpack_from(">h", cmap, deltas + position)
        offset, = unpack_from(">H", cmap, offsets + position)
        if not last < first <= end:
            raise ValueError("Overlapping TrueType character ranges.")
        last = end
        for codepoint in range(first, end + 1):
            glyph = codepoint
            if offset:
                address = offsets + position + offset + 2 * (codepoint - first)
                if not offsets + segment_bytes <= address <= length - 2 or address % 2:
                    raise ValueError("Invalid TrueType glyph offset.")
                glyph, = unpack_from(">H", cmap, address)
                if not glyph:
                    continue
            glyph = (glyph + delta) & 0xFFFF
            if glyph >= glyph_count:
                raise ValueError("Invalid TrueType glyph index.")
            if glyph:
                yield codepoint


def full_codepoints(cmap, glyph_count):
    length, _, count = unpack_from(">III", cmap, 4)
    limit = 16 + count * 12
    if not limit <= length <= len(cmap):
        raise ValueError("Invalid TrueType Unicode character map.")
    last = -1
    for first, end, glyph in iter_unpack(">III", cmap[16:limit]):
        if not last < first <= end <= 0x10FFFF or glyph + end - first >= glyph_count:
            raise ValueError("Invalid TrueType Unicode character range.")
        last = end
        yield from range(first + (glyph == 0), end + 1)


@lru_cache(maxsize=12)
def font_codepoints(data):
    """Check TrueType structure before the optional PDF engine reads the same file."""
    try:
        tables = font_tables(data)
        count = checked_glyph_count(tables)
        cmap = unicode_subtable(tables[b"cmap"])
        format_number, = unpack_from(">H", cmap)
        if format_number == 4:
            codepoints = frozenset(bmp_codepoints(cmap, count))
        elif format_number == 12:
            codepoints = frozenset(full_codepoints(cmap, count))
        else:
            raise ValueError("Expected a Unicode TrueType character map.")
    except (StructError, KeyError, IndexError, ValueError) as error:
        raise ValueError("The TrueType font is unusable.") from error
    if not codepoints:
        raise ValueError("The TrueType font draws no characters.")
    try:
        from reportlab.pdfbase.ttfonts import TTFont, TTFError
    except ImportError:
        return codepoints
    try:
        face = TTFont("WeekflowCheck", BytesIO(data), validate=1).face
    except (TTFError, StructError, IndexError, KeyError, ValueError, OverflowError) as error:
        raise ValueError("The PDF engine cannot use the TrueType font.") from error
    usable = codepoints.intersection(code for code, glyph in face.charToGlyph.items() if glyph)
    if not usable:
        raise ValueError("The PDF font draws no characters.")
    return usable


def read_frozen_font(files, digest):
    if not isinstance(digest, str) or not FONT_DIGEST.fullmatch(digest):
        raise ValueError("Invalid saved font digest.")
    data = read_regular(files, frozen_font_path(digest), FONT_LIMIT)
    if data is None or sha256(data).hexdigest() != digest:
        raise ValueError("The saved font is missing or changed.")
    font_codepoints(data)
    return data


def is_frozen_font(files, relative):
    relative = Path(relative)
    if not FROZEN_FONT_TARGET.fullmatch(relative.as_posix()):
        return False
    try:
        read_frozen_font(files, relative.stem)
    except (OSError, ValueError, Refusal):
        return False
    return True
