"""Check that the page and PDF show the same carry-over text."""

import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/weekflow/scripts"))
from weekflow_tool.client_pdf import render_pdf
from weekflow_tool.page import MeetingView
from weekflow_tool.page_html import render_html


REPORTLAB = importlib.util.find_spec("reportlab") is not None
PDFTOTEXT = shutil.which("pdftotext")


def carryover_view():
    return MeetingView(
        project={"project": "Corner Bakery", "client": "", "attendees": ["the owner"],
                 "scope_approved_on": "2026-02-01", "planned_end": "2026-03-26"},
        week={"number": 4, "meeting_date": "2026-03-12", "held": False,
              "mode": "build", "end_before": "2026-03-26"},
        content={
            "headline": "The bread menu is ready.", "finished": [], "next_week": [], "needs": [],
            "meeting_promises": [
                {"id": "P-001", "made_week": 2, "checked_week": 4,
                 "what": "Show the pickup form", "status": "done"},
                {"id": "P-002", "made_week": 2, "checked_week": 4,
                 "what": "Add the allergy menu", "status": "not finished", "note": "Needs review."},
            ],
            "missed_meetings": ["2026-03-05"],
            "corrections": [
                {"id": "X-001", "kind": "correction", "week": 2, "date": "2026-03-06",
                 "what": "Use <b>rolls</b> & bread", "reason": "Use the printed menu", "by": "the owner"},
                {"id": "X-002", "kind": "removal", "week": 1, "date": "2026-03-07",
                 "what": "An attendee entry", "reason": "Privacy request", "by": "the owner"},
            ],
        },
        changes=[], evidence=[],
    )


class CarryoverRenderTests(unittest.TestCase):
    def test_carryover_appears_once_on_see_it_and_escapes_text(self):
        html = render_html(carryover_view())
        step = html.split('id="panel-2"', 1)[1].split('id="panel-3"', 1)[0]
        for text in ("What we promised last week", "Show the pickup form", "Done", "Add the allergy menu",
                     "Not finished", "Needs review.", "No meeting was held on 5 March.",
                     "Correction for week 2 on 6 March.", "Use &lt;b&gt;rolls&lt;/b&gt; &amp; bread",
                     "Use the printed menu", "Removal for week 1 on 7 March.", "Privacy request"):
            with self.subTest(text=text):
                self.assertIn(text, step)
                self.assertEqual(html.count(text), 1)
        self.assertNotIn("<b>rolls</b>", html)

    @unittest.skipUnless(REPORTLAB and PDFTOTEXT, "PDF text check needs reportlab and pdftotext")
    def test_pdf_shows_carryover_once_and_keeps_literal_markup_text(self):
        result = subprocess.run([PDFTOTEXT, "-", "-"], input=render_pdf(carryover_view()),
                                capture_output=True, check=True, timeout=10)
        pdf = " ".join(result.stdout.decode("utf-8").split())
        for text in ("What we promised last week", "Show the pickup form", "Done", "Add the allergy menu",
                     "Not finished", "Needs review.", "No meeting was held on 5 March.",
                     "Correction for week 2 on 6 March.", "Use <b>rolls</b> & bread",
                     "Use the printed menu", "Removal for week 1 on 7 March.", "Privacy request"):
            with self.subTest(text=text):
                self.assertEqual(pdf.count(text), 1)
