"""Check PDF design details that are easy to miss in a page comparison."""

from hashlib import sha256
from io import BytesIO
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_recorded_meeting import REPORTLAB
from test_weekflow import TOOL


sys.path.insert(0, str(TOOL.parent))


@unittest.skipUnless(REPORTLAB, "reportlab is required for PDF design rendering")
class PdfDesignTests(unittest.TestCase):
    def test_only_the_screen_frame_changes_with_card_radius(self):
        from reportlab.pdfgen.canvas import Canvas
        from weekflow_tool.client_pdf import answer_badge, pdf_styles, register_fonts
        from weekflow_tool.docs_pdf import decision_badge
        from weekflow_tool.meeting_design import studio_design
        from weekflow_tool.screen_pdf import screen_map_story

        studio = studio_design()
        fonts = register_fonts(studio)
        styles = pdf_styles(studio, fonts)
        for radius, points in ((0, 0), (32, 19)):
            with self.subTest(radius=radius):
                design = SimpleNamespace(is_studio=False, colors=studio.colors, radius=radius,
                                         badge_ink=studio.badge_ink)
                build = answer_badge("yes", "Yes, now", styles["cell"], design, fonts["bold"])
                docs = decision_badge("the client", 120, styles["cell"], design)
                self.assertEqual(build._cornerRadii, [6] * 4)
                self.assertEqual(docs._cornerRadii, [6] * 4)
                view = SimpleNamespace(
                    design=design, content={}, screen_map=[
                        {"state": "not built", "name": "Order menu", "current": None, "previous": None},
                    ],
                )
                card = screen_map_story(view, styles)[-2]
                canvas = Canvas(BytesIO())
                card.wrap(300, 300)
                with patch.object(canvas, "roundRect", wraps=canvas.roundRect) as draw:
                    card.drawOn(canvas, 0, 0)
                draw.assert_called_once_with(0, 0, 300, card.height, points, stroke=1, fill=1)

    def test_custom_badges_keep_short_answers_on_one_line(self):
        from weekflow_tool.client_pdf import answer_badge, pdf_styles, register_fonts
        from weekflow_tool.docs_pdf import decision_badge
        from weekflow_tool.meeting_design import studio_design

        studio = studio_design()
        fonts = register_fonts(studio)
        style = pdf_styles(studio, fonts)["cell"]
        design = SimpleNamespace(is_studio=False, colors=studio.colors, badge_ink=studio.badge_ink)
        badges = (answer_badge("no", "Bee", style, design, fonts["bold"]),
                  decision_badge("Meet", 120, style, design))
        for badge in badges:
            badge.wrap(200, 200)
            paragraph = badge._cellvalues[0][0][0]
            self.assertEqual(len(paragraph.blPara.lines), 1)

    def test_reportlab_never_reuses_a_different_font_with_the_same_internal_name(self):
        from reportlab.pdfbase import pdfmetrics
        from weekflow_tool.client_pdf import register_fonts
        from weekflow_tool.meeting_design import studio_design

        studio = studio_design()
        second = dict(studio.font_data, body=studio.font_data["body"] + b"\0" * 4)

        def custom(data):
            digests = {role: sha256(font).hexdigest() for role, font in data.items()}
            return SimpleNamespace(is_studio=False, font_data=data, font_digests=digests, missing_roles=())

        first_names = register_fonts(custom(studio.font_data))
        second_names = register_fonts(custom(second))
        first_font = pdfmetrics.getFont(first_names["body"])
        second_font = pdfmetrics.getFont(second_names["body"])
        self.assertIsNot(first_font, second_font)
        self.assertNotEqual(first_font.face.name, second_font.face.name)
        self.assertEqual(first_names["bold"], second_names["bold"])


if __name__ == "__main__":
    unittest.main()
