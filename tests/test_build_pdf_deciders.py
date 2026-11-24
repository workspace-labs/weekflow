"""Read recorded build decisions back from the client PDF."""

import re
import unicodedata
import unittest

from test_recorded_meeting import PDFTOTEXT, REPORTLAB, RecordedMeetingFixture


LEGACY_BUILD_COPY = """
sys.path.insert(0, os.path.dirname(sys.argv[1]))
from dataclasses import replace
from weekflow_tool import records

confirmed_view = records.confirmed_view
records.confirmed_view = lambda *args, **kwargs: replace(confirmed_view(*args, **kwargs), build_deciders={})
records.require_build_deciders = lambda view: None
"""


@unittest.skipUnless(REPORTLAB and PDFTOTEXT, "ReportLab and pdftotext are required for PDF text")
class BuildPdfDeciderTests(RecordedMeetingFixture, unittest.TestCase):
    def record_as(self, decider, *, answers=("C-001=yes", "C-002=later", "C-003=no")):
        flags = [part for answer in answers for part in ("--answer", answer)]
        self.command("record", *flags, "--attendee", "the owner", "--decided-by", decider)

    def test_english_pdf_names_the_decider_and_meeting_date_for_each_answer(self):
        self.start()
        for title in ("Add collection hours", "Try larger signs", "Make a new counter", "Add a second till"):
            self.add_change(title)
        self.prepare()
        self.client_copy()
        self.assertNotIn("Decided by", self.extract_pdf(layout=True))

        self.record_as("Mira Holt")
        self.assertEqual([row["decided_by"] for row in self.read_json(self.changes)],
                         ["Mira Holt", "Mira Holt", "Mira Holt", ""])
        page_before = self.page.read_bytes()
        self.client_copy()
        drawn = " ".join(self.extract_pdf(layout=True).split())
        self.assertEqual(len(re.findall(r"Decided by Mira Holt on 26\s+February", drawn)), 3, drawn)
        self.assertEqual(self.page.read_bytes(), page_before)

    def test_arabic_pdf_uses_the_saved_decider_and_meeting_date(self):
        (self.project / "docs/prd.md").write_text(
            "# متطلبات المنتج (PRD): مخبز تجريبي\n> الإصدار 2 · معتمد 2026-02-08 من العميل\n",
            encoding="utf-8",
        )
        self.command("start", "--language", "ar", "--meeting-day", "الخميس",
                     "--planned-end", "2026-03-12", "--client", "العميل", "--attendee", "المالك")
        self.write_json(self.draft, {"headline": "قائمة الخبز جاهزة.", "finished": [
            {"text": "تجهيز القائمة", "source": "app/menu.py"}], "next_week": [], "needs": []})
        self.command("change", "--what", "إضافة وقت للاستلام", "--reason", "طلب العميل",
                     "--asked-by", "ندى", "--days", "2")
        self.prepare()
        self.command("record", "--answer", "C-001=yes", "--attendee", "المالك",
                     "--decided-by", "سامر")
        self.assertEqual(self.read_json(self.changes)[0]["decided_by"], "سامر")
        self.client_copy()
        drawn = unicodedata.normalize("NFKC", self.extract_pdf(layout=True))
        self.assertIn("ندى", drawn)
        self.assertIn("سامر", drawn)
        self.assertTrue(any("سامر" in line and "القرار" in line and "26" in line and "فبراير" in line
                            for line in drawn.splitlines()), drawn)

    def test_existing_locked_pdf_keeps_its_legacy_receipt_and_bytes(self):
        self.start()
        self.add_change()
        self.prepare()
        self.record_as("Mira Holt", answers=("C-001=yes",))
        self.command("client-copy", setup=LEGACY_BUILD_COPY)
        self.assertNotIn("Mira Holt", self.extract_pdf(layout=True))
        pdf = self.pdf.read_bytes()
        self.command("sign", "--by", "the client", "--on", self.meeting_date, setup=LEGACY_BUILD_COPY)
        self.command("lock", setup=LEGACY_BUILD_COPY)
        week = self.week.read_bytes()

        self.command("client-copy")
        self.assertEqual(self.pdf.read_bytes(), pdf)
        self.assertEqual(self.week.read_bytes(), week)

    def test_unlocked_pdf_with_an_old_or_wrong_decider_receipt_cannot_be_signed(self):
        self.start()
        self.add_change()
        self.prepare()
        self.record_as("Mira Holt", answers=("C-001=yes",))
        self.command("client-copy", setup=LEGACY_BUILD_COPY)
        sign = ("sign", "--by", "the client", "--on", self.meeting_date)
        self.assertIn("make the current pdf", self.refuse(*sign))

        self.client_copy()
        [change] = self.read_json(self.changes)
        self.write_json(self.changes, [dict(change, decided_by="Eli Moss")])
        self.assertIn("make the current pdf", self.refuse(*sign))
        self.write_json(self.changes, [dict(change, decided_by="")])
        self.assertIn("use record to give who decided c-001", self.refuse("client-copy"))

    def test_removing_the_decider_name_rebuilds_the_locked_pdf_from_redacted_record(self):
        self.start()
        self.add_change()
        self.prepare()
        self.record_as("Mira Holt", answers=("C-001=no",))
        self.client_copy()
        self.command("lock")

        self.command("remove-name", "--name", "Mira Holt", "--what", "Remove a name",
                     "--reason", "Privacy", "--by", "the owner")
        [change] = self.read_json(self.changes)
        self.assertNotIn("Mira Holt", change["decided_by"])
        self.client_copy()
        drawn = " ".join(self.extract_pdf(layout=True).split())
        self.assertNotIn("Mira Holt", drawn)
        self.assertIn(f'Decided by {change["decided_by"]} on 26 February', drawn)
