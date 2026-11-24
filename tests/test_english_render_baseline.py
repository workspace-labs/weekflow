"""Keep the English meeting artifacts compatible with commit 800de43."""

from functools import partial
from hashlib import sha256
import subprocess
import unittest

import test_docs_meetings as docs
import test_recorded_meeting as build
from test_pdf_layout_snapshot import use_legacy_pdf
from test_weekflow import ORIGINAL_PAGE_PREPARE, cli_date_setup


# Captured from actual CLI output in an isolated archive of 800de43 with ReportLab 5.0.0.
BASELINE = {
    ("build", "html"): "aae384b78280f51052bc81fdc493075d0d8bc2e175b6cbc8e8892dc79436b717",
    ("build", "prepared_pdf"): "e3396763f56edac346cc296379c6c7bd8d34e2fe37382bea4ed983f9d97da87e",
    ("build", "unanswered_pdf"): "6dd8f5738a52e1dd322dde29b5066ad26940169009c74904a5098d25eea16d9f",
    ("docs", "html"): "0fbb056d157c01d0ee9ceea0ee228ada77b08cfbe2ef4a617e83a925cdca36db",
    ("docs", "pdf"): "d7efd13c2e6c4c7da6ff765cd8eb6dc3e4af6fd2e74a094c1bea8758781ff2c5",
}
# The answered build reference now adds a byline. Hash the entire old PDF text
# after extracting in drawing order and removing whitespace.
ANSWERED_PDF_TEXT = "869e6eba0150177efefed04d855753b673b746d8dbf2de1007f7b4b087011fbe"
# Captured from the answered build fixture in an isolated archive of f767319.
ANSWERED_PDF_BYTES = "60c5e8bd96da94b243ef4846749d49dd66ab017b0800b30a89b434bf85f1c9ee"
# Keep the recorded change date and confirmation checks on the capture date.
BASELINE_CLOCK = cli_date_setup("2026-11-23")


def require_baseline_pdf(test):
    if not build.REPORTLAB:
        test.skipTest("ReportLab is required for the English PDF byte comparison")
    from reportlab import Version

    if Version != "5.0.0":
        test.skipTest("The English PDF baseline is pinned to ReportLab 5.0.0")


class EnglishBuildBaselineTests(build.RecordedMeetingFixture, unittest.TestCase):
    def command(self, command, *args, setup="", expected=0):
        return super().command(command, *args, setup=BASELINE_CLOCK + ORIGINAL_PAGE_PREPARE + setup, expected=expected)

    def prepare_change(self, *, legacy_pdf=False):
        self.start()
        self.add_change()
        self.prepare(confirm=False)
        if legacy_pdf:
            use_legacy_pdf(self.content)
        self.command("confirm")

    def test_build_html_matches_800de43(self):
        self.prepare_change()
        self.record_manual("C-001=yes")
        self.assertEqual(sha256(self.page.read_bytes()).hexdigest(), BASELINE["build", "html"])

    def test_prepared_build_pdf_matches_800de43(self):
        require_baseline_pdf(self)
        self.prepare_change(legacy_pdf=True)
        self.assertEqual(sha256(self.client_copy()).hexdigest(), BASELINE["build", "prepared_pdf"])

    def test_unanswered_build_pdf_matches_800de43(self):
        require_baseline_pdf(self)
        self.prepare_change(legacy_pdf=True)
        self.record_manual()
        self.assertEqual(sha256(self.client_copy()).hexdigest(), BASELINE["build", "unanswered_pdf"])

    @unittest.skipUnless(build.PDFTOTEXT, "pdftotext is required for the English PDF text comparison")
    def test_answered_build_pdf_adds_only_the_decider_line_to_the_800de43_text(self):
        require_baseline_pdf(self)
        self.prepare_change(legacy_pdf=True)
        self.record_manual("C-001=yes")
        self.client_copy()
        extracted = subprocess.check_output([build.PDFTOTEXT, "-raw", str(self.pdf), "-"], text=True)
        text = "".join(extracted.split())
        byline = "Decidedbytheclienton26February"
        self.assertEqual(text.count(byline), 1)
        self.assertIn(f"Offeralaterpickupslot{byline}Datemoved", text)
        self.assertEqual(sha256(text.replace(byline, "", 1).encode()).hexdigest(), ANSWERED_PDF_TEXT)

    def test_answered_build_keeps_the_pre_layout_receipt_and_bytes_after_lock(self):
        require_baseline_pdf(self)
        self.prepare_change(legacy_pdf=True)
        self.record_manual("C-001=yes")
        original = self.client_copy()
        self.assertEqual(sha256(original).hexdigest(), ANSWERED_PDF_BYTES)

        self.command("sign", "--by", "the client", "--on", self.meeting_date)
        self.command("lock")
        self.assertEqual(self.client_copy(), original)
        self.pdf.unlink()
        self.assertEqual(self.client_copy(), original)


class EnglishDocsBaselineTests(unittest.TestCase):
    def prepare_and_record(self, *, legacy_pdf=False):
        meeting = docs.DocsMeetingTests()
        meeting.setUp()
        self.addCleanup(meeting.doCleanups)
        meeting.invoke = partial(meeting.invoke, setup=BASELINE_CLOCK + ORIGINAL_PAGE_PREPARE)
        meeting.start()
        meeting.write_draft()
        meeting.prepare()
        if legacy_pdf:
            use_legacy_pdf(meeting.page.with_name("week-3-content.json"))
        meeting.invoke("confirm")
        meeting.record("D-001=the manager", "D-002=later")
        return meeting

    def test_docs_html_matches_800de43(self):
        meeting = self.prepare_and_record()
        self.assertEqual(sha256(meeting.page.read_bytes()).hexdigest(), BASELINE["docs", "html"])

    def test_docs_pdf_matches_800de43(self):
        require_baseline_pdf(self)
        meeting = self.prepare_and_record(legacy_pdf=True)
        meeting.invoke("client-copy")
        pdf = meeting.page.with_suffix(".pdf")
        self.assertEqual(sha256(pdf.read_bytes()).hexdigest(), BASELINE["docs", "pdf"])


if __name__ == "__main__":
    unittest.main()
