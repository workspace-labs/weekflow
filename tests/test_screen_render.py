"""The page and PDF present the same saved screen facts."""

import importlib.util
from base64 import b64encode
from pathlib import Path
from struct import pack
import sys
import unittest
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/weekflow/scripts"))
from weekflow_tool.client_pdf import render_pdf
from weekflow_tool.page import MeetingView
from weekflow_tool.page_html import render_html
from pdftotext_file import pdftotext_bytes, poppler_pdftotext


REPORTLAB = importlib.util.find_spec("reportlab") is not None
PDFTOTEXT = poppler_pdftotext()


def png(rgb, width=12, height=20):
    def chunk(kind, data):
        return pack(">I", len(data)) + kind + data + pack(">I", zlib.crc32(kind + data))

    scanline = b"\x00" + bytes(rgb) * width
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", pack(">2I5B", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(scanline * height))
            + chunk(b"IEND", b""))


def picture(rgb=None, *, kind="screenshot", taken_on=None, new=False, removed=None):
    return {"data": None if removed else png(rgb), "kind": kind, "taken_on": taken_on,
            "new": new, "removed": removed}


def screen_view(app_ran=True):
    return MeetingView(
        project={"project": "Corner Bakery", "client": "", "attendees": ["the owner"],
                 "scope_approved_on": "2026-02-01", "planned_end": "2026-03-26"},
        week={"number": 4, "meeting_date": "2026-03-12", "held": False,
              "mode": "build", "end_before": "2026-03-26"},
        content={"headline": "The menu is ready.", "finished": [], "next_week": [],
                 "needs": [], "app_ran": app_ran},
        changes=[], evidence=[],
        screen_map=[
            {"id": "menu", "name": "Bread & rolls", "state": "finished",
             "previous": picture((40, 50, 60), taken_on="2026-03-04"),
             "current": picture((90, 80, 70), taken_on="2026-03-11", new=True)},
            {"id": "orders", "name": "Order details", "state": "being built",
             "previous": picture(kind="screenshot", taken_on="2026-03-04",
                                 removed="Removed on 10 March 2026 because Personal details"),
             "current": picture((10, 40, 70), taken_on="2026-03-01")},
            {"id": "kitchen", "name": "Kitchen", "state": "not built",
             "previous": None, "current": picture((10, 20, 30), kind="design")},
            {"id": "pickup", "name": "Pickup", "state": "not built",
             "previous": None, "current": None},
        ],
    )


class ScreenRenderTests(unittest.TestCase):
    def test_html_includes_counts_dates_pairs_and_native_expand_control(self):
        view = screen_view()
        html = render_html(view)
        see_it = html.split('id="panel-2"', 1)[1].split('id="panel-3"', 1)[0]
        for text in ("Finished", "We are here", "Not built yet", "Bread &amp; rolls",
                     "4 March 2026", "11 March 2026", "1 March 2026", "Earlier", "Current",
                     "New", "Design", "No design is available.", "Open screen", "Close screen",
                     "Removed on 10 March 2026 because Personal details"):
            with self.subTest(text=text):
                self.assertIn(text, see_it)
        self.assertLess(see_it.index("Bread &amp; rolls"), see_it.index("Order details"))
        self.assertIn('datetime="2026-03-04"', see_it)
        self.assertIn('datetime="2026-03-11"', see_it)
        self.assertIn('class="screen-pictures screen-pair"', see_it)
        self.assertEqual(see_it.count("<details "), 4)
        self.assertEqual(see_it.count("<summary"), 4)
        for screen in view.screen_map:
            for item in [screen["current"], screen["previous"]]:
                if item and item["data"]:
                    base64 = b64encode(item["data"]).decode("ascii")
                    self.assertEqual(html.count(f"data:image/png;base64,{base64}"), 1)
        self.assertIn("img-src data:", html)
        self.assertNotIn('href="#screen-', html)

    def test_failed_app_has_no_new_badge(self):
        html = render_html(screen_view(app_ran=False))
        self.assertIn("The app could not be run for this meeting.", html)
        self.assertIn("11 March 2026", html)
        self.assertNotIn(">New<", html)

    @unittest.skipUnless(REPORTLAB and PDFTOTEXT, "PDF text check needs reportlab and pdftotext")
    def test_pdf_contains_same_screen_facts_and_does_not_label_old_pictures_new(self):
        for ran in (True, False):
            with self.subTest(app_ran=ran):
                report = render_pdf(screen_view(app_ran=ran))
                self.assertGreaterEqual(report.count(b"/Subtype /Image"), 4)
                text = " ".join(pdftotext_bytes(PDFTOTEXT, report, timeout=10).decode("utf-8").split())
                for value in ("Bread & rolls", "Finished", "We are here", "Not built yet", "Earlier",
                              "Current", "4 March 2026", "11 March 2026", "1 March 2026", "Design",
                              "Removed on 10 March 2026 because Personal details",
                              "No design is available."):
                    self.assertIn(value, text)
                self.assertEqual("11 March 2026 · New" in text, ran)
                self.assertEqual("The app could not be run for this meeting." in text, not ran)
