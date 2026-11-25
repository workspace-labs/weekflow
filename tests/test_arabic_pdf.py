"""Arabic PDF shaping and layout checks."""

from dataclasses import replace
from io import BytesIO
import re
import sys
from unicodedata import normalize
import unittest
from unittest.mock import patch

from test_recorded_meeting import PDFTOTEXT, REPORTLAB
from test_screen_render import screen_view
from test_weekflow import TOOL
from pdftotext_file import pdftotext_bytes


sys.path.insert(0, str(TOOL.parent))


class ShapingTests(unittest.TestCase):
    def text(self, value):
        from weekflow_tool.arabic import display, visual

        return "".join(char for char, _ in visual(display(value)))

    def test_joined_letters_and_lam_alef(self):
        self.assertEqual(self.text("سلام"), "مﻼﺳ")
        self.assertEqual(self.text("لا"), "ﻻ")
        self.assertEqual(self.text("لَا"), "َﻻ")
        self.assertEqual(self.text("نُصّ"), "ّﺺُﻧ")

    def test_mixed_number_tool_and_brackets_keep_reading_order(self):
        shaped = self.text("في Bunnev 12.5 (2027-03-12)")
        self.assertIn("(2027-03-12)", shaped)
        self.assertIn("Bunnev 12.5", shaped)
        self.assertTrue(shaped.startswith("Bunnev 12.5 (2027-03-12)"))
        self.assertEqual(self.text("١٢"), "12")

    def test_direction_marks_do_not_become_drawn_glyphs(self):
        self.assertEqual(self.text("س\u200fلام"), self.text("سلام"))


@unittest.skipUnless(REPORTLAB, "ReportLab is required for Arabic PDF layout")
class ArabicParagraphTests(unittest.TestCase):
    def setUp(self):
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        fonts = TOOL.parents[3] / "docs/fonts"
        for name, file in (("ArabicTest", "NotoNaskhArabic-Regular.ttf"),
                           ("LatinTest", "InstrumentSans-Regular.ttf")):
            pdfmetrics.registerFont(TTFont(name, str(fonts / file)))

    def paragraph(self, value):
        from reportlab.lib.enums import TA_RIGHT
        from reportlab.lib.styles import ParagraphStyle
        from weekflow_tool.pdf_arabic import ArabicParagraph

        return ArabicParagraph(value, ParagraphStyle("ArabicTest", fontName="ArabicTest",
                               fontSize=12, leading=18, alignment=TA_RIGHT,
                               latinFont="LatinTest"), "headline")

    def test_wraps_the_logical_text_and_can_split_across_pages(self):
        paragraph = self.paragraph("سلام في Bunnev 12.5. " * 30)
        width, height = paragraph.wrap(125, 1000)
        self.assertGreater(height, 100)
        self.assertTrue(all(paragraph.measure(line) <= width for line in paragraph.lines))
        self.assertEqual(" ".join(paragraph.lines), " ".join(paragraph.value.split()))
        opening, closing = paragraph.split(width, 100)
        self.assertLessEqual(opening.wrap(width, 100)[1], 100)
        self.assertIn("سلام", closing.value)

    def test_draws_latin_in_the_latin_font_and_right_aligns(self):
        from reportlab.pdfgen.canvas import Canvas

        paragraph = self.paragraph("سلام في Bunnev 12.5")
        paragraph.wrap(200, 300)
        canvas = Canvas(BytesIO())
        with patch.object(canvas, "setFont", wraps=canvas.setFont) as font, \
                patch.object(canvas, "drawString", wraps=canvas.drawString) as draw:
            paragraph.drawOn(canvas, 0, 0)
        self.assertIn("LatinTest", [call.args[0] for call in font.call_args_list])
        self.assertTrue("".join(call.args[2] for call in draw.call_args_list).startswith("Bunnev 12.5"))
        self.assertAlmostEqual(draw.call_args_list[0].args[0],
                               200 - paragraph.measure(paragraph.value))


@unittest.skipUnless(REPORTLAB and PDFTOTEXT, "ReportLab and pdftotext are required for PDF text")
class ArabicMeetingPdfTests(unittest.TestCase):
    def arabic_view(self, mode):
        from weekflow_tool.meeting_design import studio_design
        from weekflow_tool.page import MeetingView

        project = {"project": "مخبز الحي", "client": "", "attendees": ["المالك", "Dana"],
                   "scope_approved_on": "2027-02-07", "planned_end": "2027-03-31",
                   "language": "ar"}
        week = {"number": 2, "meeting_date": "2027-03-12", "held": True, "mode": mode,
                "end_before": "2027-03-31", "end_after": "2027-04-03", "attendees": ["Dana"],
                "answers": []}
        content = {"headline": "مراجعة طلبات الاستلام",
                   "finished": [{"text": "تمت مراجعة قائمة الخبز عبر Bunnev 12.5."}],
                   "next_week": [{"text": "نجرب استلام الطلب."}],
                   "needs": [{"text": "قائمة الخبز.", "by": "2027-03-19"}],
                   "missed_meetings": ["2027-03-05"]}
        if mode == "docs":
            week["answers"] = [{"id": "D-001", "answer": "المدير", "decided_by": "Dana"}]
            content.update(stage=3, stage_meetings={"1": 1}, document=[{
                "title": "طريقة العمل", "sentences": [{"text": "يُراجع الطلب قبل اعتماده."}]}],
                decisions=[{"id": "D-001", "question": "من يؤكد موعد الاستلام؟",
                            "why": "يفضّل العميل جهة واحدة.", "options": ["المدير", "المالك"]}])
            changes, screens = [], []
        else:
            week["answers"] = [{"id": "C-001", "answer": "yes"}]
            changes = [{"id": "C-001", "what": "إضافة موعد استلام", "reason": "الاستلام مساءً.",
                        "asked_by": "العميل", "date": "2027-03-09", "days_added": 3}]
            screen = screen_view().screen_map[0]
            screens = [dict(screen, name="قائمة الخبز")]
        return MeetingView(project, week, content, changes, [], design=studio_design("ar"),
                           screen_map=screens)

    def test_arabic_pdfs_have_localized_labels_and_keep_latin_names_and_tools(self):
        from weekflow_tool.client_pdf import render_pdf
        from weekflow_tool.meeting_language import ARABIC

        for mode in ("docs", "build"):
            with self.subTest(mode=mode):
                pdf = render_pdf(self.arabic_view(mode))
                drawn = " ".join(pdftotext_bytes(PDFTOTEXT, pdf, "-layout", timeout=10).decode().split())
                candidates = [key for key in ARABIC if "{" not in key]
                candidates += ["Paper signature", "Delivery date before the meeting", "Page 1"]
                for english in candidates:
                    self.assertIsNone(re.search(rf"(?<![A-Za-z]){re.escape(english)}(?![A-Za-z])",
                                                drawn, flags=re.IGNORECASE), english)
                self.assertIn("Dana", drawn)
                if mode == "build":
                    self.assertIn("Bunnev 12.5", drawn)
                    self.assertGreaterEqual(pdf.count(b"/Subtype /Image"), 2)

    def test_layout_c_explains_the_signature_only_when_the_date_moves(self):
        from weekflow_tool.client_pdf import render_pdf
        from weekflow_tool.meeting_design import PDF_LAYOUT_C_REVISED, with_pdf_paper

        view = self.arabic_view("build")
        design, _ = with_pdf_paper(view.design, "design", layout=PDF_LAYOUT_C_REVISED)
        for moved in (False, True):
            with self.subTest(moved=moved):
                week = view.week if moved else dict(view.week, end_after=view.week["end_before"], answers=[])
                pdf = render_pdf(replace(view, week=week, design=design))
                drawn = " ".join(normalize("NFKC", pdftotext_bytes(PDFTOTEXT, pdf, "-layout", timeout=10).decode()).split())
                self.assertIn("توقيع العميل", drawn)
                self.assertEqual("مطلوب لأن موعد التسليم تغيّر" in drawn, moved)


if __name__ == "__main__":
    unittest.main()
