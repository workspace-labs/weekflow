"""Check that unsupported picture encodings are refused before saving."""

import unittest
from struct import pack
from zlib import compress

from test_recorded_meeting import RecordedMeetingFixture, REPORTLAB
from test_screen_inputs import jpeg, png_chunk
from test_screen_meetings import png


def jpeg_segment(marker, payload):
    return b"\xff" + bytes((marker,)) + pack(">H", len(payload) + 2) + payload


def exif_orientation(orientation, byte_order):
    header = b"II" if byte_order == "<" else b"MM"
    return (header + pack(f"{byte_order}HIH", 42, 8, 1)
            + pack(f"{byte_order}HHIHHI", 0x0112, 3, 1, orientation, 0, 0))


def progressive_jpeg():
    # A single brighter grayscale pixel with separate initial DC and AC scans.
    frame = jpeg(tables=False).partition(b"\xff\xda")[0][2:].replace(b"\xff\xc0", b"\xff\xc2", 1)
    quantization = jpeg_segment(0xDB, b"\x00" + b"\x01" * 64)
    single_code = b"\x01" + bytes(15)
    huffman = jpeg_segment(0xC4, b"\x00" + single_code + b"\x04" + b"\x10" + single_code + b"\x00")
    dc_scan = jpeg_segment(0xDA, b"\x01\x01\x00\x00\x00\x00") + b"\x7f"
    ac_scan = jpeg_segment(0xDA, b"\x01\x01\x00\x01\x3f\x00") + b"\x7f"
    return b"\xff\xd8" + quantization + huffman + frame + dc_scan + ac_scan + b"\xff\xd9"


class PictureFormatTests(RecordedMeetingFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.start()
        self.command("screen", "--id", "menu", "--name", "Menu", "--state", "finished")
        self.input_picture = self.scratch / "picture"

    def picture_args(self, code="menu"):
        return ("--id", code, "--file", str(self.input_picture),
                "--kind", "screenshot", "--taken-on", "2026-02-25")

    def test_unsupported_jpeg_profiles_and_precision_are_refused_before_saving(self):
        original = jpeg()
        for marker in (0xC1, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            with self.subTest(marker=hex(marker)):
                self.input_picture.write_bytes(original.replace(b"\xff\xc0", bytes((255, marker)), 1))
                self.assertIn("8-bit", self.refuse("screen-picture", *self.picture_args()))
        for label, supported in (("baseline", original), ("progressive", progressive_jpeg())):
            with self.subTest(precision=12, frame=label):
                index = supported.index(b"\xff\xc0" if label == "baseline" else b"\xff\xc2") + 4
                self.input_picture.write_bytes(supported[:index] + b"\x0c" + supported[index + 1:])
                self.assertIn("8-bit", self.refuse("screen-picture", *self.picture_args()))

    def test_rotated_or_mirrored_jpeg_and_png_are_refused_before_saving(self):
        original_jpeg = jpeg()
        original_png = png((17, 25, 43))
        for orientation, byte_order in ((2, "<"), (6, ">"), (8, "<")):
            exif = exif_orientation(orientation, byte_order)
            inputs = {
                "JPEG": original_jpeg[:2] + jpeg_segment(0xE1, b"Exif\x00\x00" + exif) + original_jpeg[2:],
                "PNG": original_png[:33] + png_chunk(b"eXIf", exif) + original_png[33:],
            }
            for kind, picture in inputs.items():
                with self.subTest(orientation=orientation, kind=kind):
                    self.input_picture.write_bytes(picture)
                    self.assertIn("upright copy", self.refuse("screen-picture", *self.picture_args()))

    def test_orientation_in_xmp_and_legacy_png_exif_is_refused(self):
        normal_png = png((17, 25, 43))
        normal_jpeg = jpeg()
        xmp = b'<rdf:Description tiff:Orientation="6" />'
        tiff = exif_orientation(6, "<")
        raw_exif = b"\nexif\n30\n" + (b"Exif\x00\x00" + tiff).hex().encode("ascii")
        for label, data in (
            ("compressed PNG XMP", normal_png[:33] + png_chunk(
                b"iTXt", b"XML:com.adobe.xmp\x00\x01\x00\x00\x00" + compress(xmp),
            ) + normal_png[33:]),
            ("legacy PNG EXIF", normal_png[:33] + png_chunk(
                b"tEXt", b"Raw profile type exif\x00" + raw_exif,
            ) + normal_png[33:]),
            ("JPEG XMP", normal_jpeg[:2] + jpeg_segment(
                0xE1, b"http://ns.adobe.com/xap/1.0/\x00" + xmp,
            ) + normal_jpeg[2:]),
        ):
            with self.subTest(metadata=label):
                self.input_picture.write_bytes(data)
                self.assertIn("upright copy", self.refuse("screen-picture", *self.picture_args()))

    def test_normal_orientation_is_accepted_and_stripped_for_jpeg_and_png(self):
        original_jpeg = jpeg()
        original_png = png((17, 25, 43))
        exif = exif_orientation(1, ">")
        pictures = (
            (original_jpeg, original_jpeg[:2] + jpeg_segment(0xE1, b"Exif\x00\x00" + exif) + original_jpeg[2:]),
            (original_png, original_png[:33] + png_chunk(b"eXIf", exif) + original_png[33:]),
        )
        for expected, marked in pictures:
            self.input_picture.write_bytes(marked)
            self.command("screen-picture", *self.picture_args())
            weekly = self.project_file.parent
            [screen] = self.read_json(weekly / "screens.json")
            self.assertEqual((weekly / screen["picture"]).read_bytes(), expected)
            self.assertEqual(self.input_picture.read_bytes(), marked)

    @unittest.skipUnless(REPORTLAB, "ReportLab is required to draw the PDF")
    def test_baseline_progressive_and_png_draw_in_the_recorded_pdf(self):
        self.write_json(self.draft, dict(self.read_json(self.draft), app_ran=True))
        for code, picture in (("menu", jpeg()), ("orders", progressive_jpeg()), ("shelf", png((2, 46, 90)))):
            self.command("screen", "--id", code, "--name", code.title(), "--state", "finished")
            self.input_picture.write_bytes(picture)
            self.command("screen-picture", *self.picture_args(code))
            self.command("screen-check", "--id", code)
        self.prepare()
        self.record_manual()
        pdf = self.client_copy()
        self.assertEqual(pdf.count(b"/DCTDecode"), 2)
        self.assertEqual(pdf.count(b"/Subtype /Image"), 3)
        self.command("lock")
