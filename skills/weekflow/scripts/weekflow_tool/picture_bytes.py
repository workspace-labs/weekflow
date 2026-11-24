"""Read size-bounded image files and remove metadata before saving them."""

import os
import re
import stat
from struct import error as StructError, unpack_from
import zlib

from .storage import Refusal


SCREEN_ID_PATTERN = r"[a-z0-9]+(?:-[a-z0-9]+)*"
PICTURE_NAME_PATTERN = (
    rf"(?P<id>{SCREEN_ID_PATTERN})-w[1-9][0-9]*-"
    r"(?P<capture>design|[0-9]{4}-[0-9]{2}-[0-9]{2})-"
    r"(?P<digest>[a-f0-9]{64})-[1-9][0-9]*\.(?P<ext>png|jpg)"
)
MAX_BYTES = 1_000_000
MAX_SIDE = 6000
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
PNG_DEPTHS = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}
PNG_REQUIRED = {b"IHDR", b"PLTE", b"tRNS", b"IDAT", b"IEND"}
ADAM7 = ((0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4),
         (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2))
JPEG_FRAME = set(range(0xC0, 0xD0)) - {0xC4}
JPEG_BASELINE = 0xC0
JPEG_PROGRESSIVE = 0xC2
JPEG_MARKER = re.compile(b"\xff+([^\xff])")
EXIF_HEADER = b"Exif\x00\x00"
XMP_HEADER = b"http://ns.adobe.com/xap/1.0/\x00"
XMP_ORIENTATION = re.compile(rb'''tiff:Orientation\s*(?:=\s*["']\s*|>\s*)([0-9]+)''')
UPRIGHT_PICTURE = "Use an upright copy of the picture with normal orientation."


def read_regular_picture(path):
    if not stat.S_ISREG(path.lstat().st_mode):
        raise Refusal("Give a regular file for the picture.")
    flags = os.O_RDONLY
    for name in ("O_BINARY", "O_NONBLOCK", "O_NOFOLLOW"):
        flags |= getattr(os, name, 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise Refusal("Give a regular file for the picture.")
        if info.st_size > MAX_BYTES:
            raise Refusal("The picture must be 1 MB or smaller.")
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise Refusal("The picture must be 1 MB or smaller.")
    return data


def check_dimensions(width, height):
    if not (width and height):
        raise ValueError
    if max(width, height) > MAX_SIDE:
        raise Refusal("The picture must be at most 6000 pixels on either side.")


def check_exif_orientation(data):
    tiff = data.removeprefix(EXIF_HEADER)
    endian = {b"II": "<", b"MM": ">"}.get(tiff[:2])
    if not endian or len(tiff) < 8:
        return
    magic, directory = unpack_from(endian + "HI", tiff, 2)
    if magic != 42 or not 8 <= directory <= len(tiff) - 2:
        return
    count, = unpack_from(endian + "H", tiff, directory)
    start = directory + 2
    end = min(start + 12 * count, len(tiff) - 11)
    # The first TIFF directory describes the main picture. Later ones can describe thumbnails.
    for offset in range(start, end, 12):
        tag, kind, values, orientation = unpack_from(endian + "HHIH", tiff, offset)
        if tag == 0x0112 and (kind, values, orientation) != (3, 1, 1):
            raise Refusal(UPRIGHT_PICTURE)


def check_xmp_orientation(data):
    if any(value.lstrip(b"0") != b"1" for value in XMP_ORIENTATION.findall(data)):
        raise Refusal(UPRIGHT_PICTURE)


def png_orientation_text(tag, data):
    if tag == b"tEXt":
        return data
    if tag == b"zTXt" and data.startswith(b"\x00"):
        return inflate_orientation_text(data[1:])
    if tag == b"iTXt" and data[:2] in (b"\x00\x00", b"\x01\x00"):
        fields = data[2:].split(b"\x00", 2)
        if len(fields) == 3:
            return inflate_orientation_text(fields[2]) if data[0] else fields[2]
    return b""


def inflate_orientation_text(data):
    text = zlib.decompressobj().decompress(data, MAX_BYTES + 1)
    if len(text) > MAX_BYTES:
        raise Refusal(UPRIGHT_PICTURE)
    return text


def check_png_orientation(tag, data):
    if tag == b"eXIf":
        check_exif_orientation(data)
    elif tag in (b"tEXt", b"zTXt", b"iTXt"):
        keyword, separator, remainder = data.partition(b"\x00")
        if separator and keyword == b"XML:com.adobe.xmp":
            check_xmp_orientation(png_orientation_text(tag, remainder))
        elif separator and keyword == b"Raw profile type exif":
            text = png_orientation_text(tag, remainder)
            profile = text.split(b"\n", 3)
            if len(profile) == 4:
                try:
                    exif = bytes.fromhex(profile[3].decode("ascii"))
                except ValueError:
                    return
                check_exif_orientation(exif)


def row_lengths(width, height, depth, interlace):
    passes = ADAM7 if interlace else ((0, 0, 1, 1),)
    for left, top, x_step, y_step in passes:
        columns = len(range(left, width, x_step))
        if columns:
            for _ in range(top, height, y_step):
                yield 1 + (columns * depth + 7) // 8


def check_png_pixels(compressed, rows):
    inflater = zlib.decompressobj()
    position = boundary = 0
    for data in compressed:
        while data:
            pixels = inflater.decompress(data, 65536)
            end = position + len(pixels)
            while boundary < end:
                length = next(rows, None)
                if length is None or pixels[boundary - position] > 4:
                    raise ValueError
                boundary += length
            position = end
            data = inflater.unconsumed_tail
    if not inflater.eof or inflater.unused_data or position != boundary or next(rows, None) is not None:
        raise ValueError


def png_chunks(data):
    position = len(PNG_SIGNATURE)
    while position < len(data):
        start = position
        length, tag = unpack_from(">I4s", data, start)
        position += 12 + length
        if position > len(data) or not re.fullmatch(rb"[A-Za-z]{4}", tag):
            raise ValueError
        payload = data[start + 8:position - 4]
        if zlib.crc32(tag + payload) != unpack_from(">I", data, position - 4)[0]:
            raise ValueError
        yield tag, payload, data[start:position]
        if tag == b"IEND" and position != len(data):
            raise ValueError


def clean_png(data):
    chunks = iter(png_chunks(data))
    tag, header, raw = next(chunks)
    if tag != b"IHDR" or len(header) != 13:
        raise ValueError
    width, height, depth, color, compression, filtering, interlace = unpack_from(">IIBBBBB", header)
    check_dimensions(width, height)
    if depth not in PNG_DEPTHS.get(color, ()) or compression or filtering or interlace not in (0, 1):
        raise ValueError

    cleaned = [PNG_SIGNATURE, raw]
    seen = {tag}
    compressed = []
    data_finished = False
    palette_size = 0
    for tag, payload, raw in chunks:
        check_png_orientation(tag, payload)
        if tag not in PNG_REQUIRED and tag[0:1].isupper():
            raise ValueError
        if (tag in PNG_REQUIRED and tag in seen and tag != b"IDAT"
                or tag in {b"PLTE", b"tRNS"} and compressed
                or tag == b"IDAT" and data_finished):
            raise ValueError
        if tag == b"IDAT":
            compressed.append(payload)
        elif compressed:
            data_finished = True
        if tag == b"PLTE" and (color in (0, 4) or not 0 < len(payload) <= 768 or len(payload) % 3):
            raise ValueError
        if tag == b"PLTE":
            palette_size = len(payload) // 3
            if b"tRNS" in seen or color == 3 and palette_size > 2 ** depth:
                raise ValueError
        if tag == b"tRNS" and not (
            color == 0 and len(payload) == 2 or color == 2 and len(payload) == 6
            or color == 3 and 0 < len(payload) <= palette_size
        ):
            raise ValueError
        if tag == b"IEND" and payload:
            raise ValueError
        seen.add(tag)
        if tag in PNG_REQUIRED:
            cleaned.append(raw)
    if not compressed or b"IEND" not in seen or color == 3 and b"PLTE" not in seen:
        raise ValueError
    check_png_pixels(compressed, row_lengths(width, height, depth * PNG_CHANNELS[color], interlace))
    return b"".join(cleaned)


def scan_end(data, start):
    for match in JPEG_MARKER.finditer(data, start):
        marker = match[1][0]
        if marker and not 0xD0 <= marker <= 0xD7:
            if match.start() == start:
                raise ValueError
            return match.start()
    raise ValueError


def jpeg_table_ids(payload, *, huffman):
    if not payload:
        raise ValueError
    position = 0
    ids = set()
    while position < len(payload):
        table = payload[position]
        mode, identifier = table >> 4, table & 15
        if mode > 1 or identifier > 3:
            raise ValueError
        if huffman:
            counts = payload[position + 1:position + 17]
            symbols = sum(counts)
            if len(counts) != 16 or not 1 <= symbols <= 256:
                raise ValueError
            available = 1
            for count in counts:
                available = 2 * available - count
                if available <= 0:  # JPEG reserves the all-ones code.
                    raise ValueError
            position += 17 + symbols
        else:
            position += 1 + 64 * (mode + 1)
        if position > len(payload):
            raise ValueError
        ids.add(table if huffman else identifier)
    return ids


def check_jpeg_scan(frame, payload, components, quantization, huffman):
    if not frame or not payload or not payload[0] or len(payload) != 4 + 2 * payload[0]:
        raise ValueError
    selected = dict(zip(payload[1:-3:2], payload[2:-3:2]))
    if (len(selected) != payload[0] or not selected.keys() <= components.keys()
            or any(components[key] not in quantization for key in selected)):
        raise ValueError
    start, end, approximation = payload[-3:]
    high, low = approximation >> 4, approximation & 15
    if frame == JPEG_BASELINE and (start, end, approximation) != (0, 63, 0):
        raise ValueError
    if frame == JPEG_PROGRESSIVE and (not start <= end <= 63 or (start == 0 and end != 0)
                                      or (start != 0 and len(selected) != 1)
                                      or low > 13 or high > 13 or (high and high != low + 1)):
        raise ValueError
    for tables in selected.values():
        if (tables >> 4) > 3 or (tables & 15) > 3:
            raise ValueError
        if start == 0 and high == 0 and tables >> 4 not in huffman:
            raise ValueError
        if end and (16 | (tables & 15)) not in huffman:
            raise ValueError


def clean_jpeg(data):
    cleaned = [data[:2]]
    position = 2
    frame = None
    components = {}
    quantization, huffman = set(), set()
    scan = False
    while position < len(data):
        marker = JPEG_MARKER.match(data, position)
        if marker is None:
            raise ValueError
        start, position = position, marker.end()
        code = marker[1][0]
        if code == 0xD9 and frame and scan:
            return b"".join(cleaned) + b"\xff\xd9"
        if code == 0 or 0xD0 <= code <= 0xD9:
            raise ValueError
        length = unpack_from(">H", data, position)[0]
        if length < 2 or position + length > len(data):
            raise ValueError
        payload = data[position + 2:position + length]
        position += length
        if code in JPEG_FRAME:
            if code not in (JPEG_BASELINE, JPEG_PROGRESSIVE) or not payload or payload[0] != 8:
                raise Refusal("Use an 8-bit baseline or progressive Huffman JPEG picture.")
            height, width, component_count = unpack_from(">HHB", payload, 1)
            check_dimensions(width, height)
            if frame or component_count not in (1, 3, 4) or len(payload) != 6 + 3 * component_count:
                raise ValueError
            components = dict(zip(payload[6::3], payload[8::3]))
            if len(components) != component_count or any(
                not (1 <= sampling >> 4 <= 4 and 1 <= sampling & 15 <= 4) for sampling in payload[7::3]
            ):
                raise ValueError
            frame = code
        if code == 0xDB:
            quantization.update(jpeg_table_ids(payload, huffman=False))
        if code == 0xC4:
            huffman.update(jpeg_table_ids(payload, huffman=True))
        if code == 0xDA:
            check_jpeg_scan(frame, payload, components, quantization, huffman)
            position = scan_end(data, position)
            scan = True
        if code == 0xE1 and payload.startswith(EXIF_HEADER):
            check_exif_orientation(payload)
        if code == 0xE1 and payload.startswith(XMP_HEADER):
            check_xmp_orientation(payload[len(XMP_HEADER):])
        if code == 0xEE and len(payload) == 12 and payload.startswith(b"Adobe"):
            # Preserve the color transform used by Adobe CMYK and YCCK encoders.
            cleaned.append(b"\xff\xee\x00\x0eAdobe\x00d\x00\x00\x00\x00" + payload[-1:])
        elif not 0xE0 <= code <= 0xEF and code != 0xFE:
            cleaned.append(data[start:position])
    raise ValueError


def clean_picture(path):
    try:
        data = read_regular_picture(path)
    except OSError:
        raise Refusal("Read the picture as a regular file.") from None
    try:
        if data.startswith(PNG_SIGNATURE):
            return "png", clean_png(data)
        if data.startswith(b"\xff\xd8"):
            return "jpg", clean_jpeg(data)
    except (ValueError, StopIteration, StructError, zlib.error):
        pass
    raise Refusal("Give a valid PNG or JPEG picture.")
