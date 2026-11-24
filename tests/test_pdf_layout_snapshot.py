"""Keep the prepared PDF layout through the public meeting commands."""

from hashlib import sha256
import json
import subprocess
import unittest

import test_docs_meetings as docs
import test_picture_removal as pictures
from test_recorded_meeting import PDFTOTEXT, REPORTLAB, STUB_PDF, RecordedMeetingFixture
from test_weekflow import cli_date_setup


REVISED_BUILD_LAYOUT = "c-2"


def set_pdf_layout(content_path, layout):
    content = json.loads(content_path.read_text(encoding="utf-8"))
    pdf = content["design"]["pdf"]
    if layout is None:
        pdf.pop("layout", None)
    else:
        pdf["layout"] = layout
    content_path.write_text(json.dumps(content), encoding="utf-8")


def use_legacy_pdf(content_path):
    set_pdf_layout(content_path, None)


class PdfLayoutSnapshotTests(RecordedMeetingFixture, unittest.TestCase):
    def assert_rendered_layout(self, pdf, *, legacy):
        text = subprocess.check_output([PDFTOTEXT, str(pdf), "-"], text=True, timeout=15)
        if legacy:
            self.assertIn("Delivery date before the meeting:", text)
        else:
            self.assertNotIn("Delivery date before the meeting:", text)
            self.assertIn("on time", text.casefold())
        return text

    def test_refresh_keeps_saved_layout_and_confirmation_download(self):
        self.start()
        self.add_change()
        self.prepare(confirm=False)
        self.assertEqual(self.read_json(self.content)["design"]["pdf"]["layout"], REVISED_BUILD_LAYOUT)
        self.command("confirm")
        self.prepare(confirm=False)
        self.assertEqual(self.read_json(self.content)["design"]["pdf"]["layout"], REVISED_BUILD_LAYOUT)
        initial_page = self.page.read_bytes()

        set_pdf_layout(self.content, "c")
        self.command("confirm")
        self.prepare(confirm=False)
        self.assertEqual(self.read_json(self.content)["design"]["pdf"]["layout"], "c")
        self.assertEqual(self.page.read_bytes(), initial_page)

        use_legacy_pdf(self.content)
        self.command("confirm")
        self.write_json(self.answers_path, self.answer_file({"C-001": "no"}))

        self.prepare(confirm=False)
        self.assertNotIn("layout", self.read_json(self.content)["design"]["pdf"])
        self.assertEqual(self.page.read_bytes(), initial_page)
        self.prepare()
        self.assertNotIn("layout", self.read_json(self.content)["design"]["pdf"])
        self.record_download()

    def test_new_layout_receipt_changes_independently_of_the_answer_fingerprint(self):
        self.start()
        self.prepare()
        self.record_manual()
        self.command("client-copy", setup=STUB_PDF)
        marked_copy = self.pdf.read_bytes()
        page = self.page.read_bytes()

        use_legacy_pdf(self.content)
        self.assertIn("make the current pdf", self.refuse("lock"))
        self.command("client-copy", setup=STUB_PDF)
        unmarked_copy = self.pdf.read_bytes()
        self.command("lock")

        self.assertNotEqual(marked_copy, unmarked_copy)
        self.assertEqual(self.page.read_bytes(), page)
        self.assertEqual(self.pdf.read_bytes(), unmarked_copy)

    def test_docs_continue_to_prepare_with_layout_c(self):
        meeting = docs.DocsMeetingTests()
        meeting.setUp()
        self.addCleanup(meeting.doCleanups)
        meeting.start()
        meeting.write_draft()
        meeting.prepare()
        content = meeting.read(meeting.page.with_name("week-3-content.json"))
        self.assertEqual(content["design"]["pdf"]["layout"], "c")

    @unittest.skipUnless(REPORTLAB and PDFTOTEXT, "ReportLab and pdftotext are required")
    def test_record_lock_and_removals_rebuild_each_week_in_its_prepared_layout(self):
        meeting = pictures.PictureRemovalTests()
        meeting.setUp()
        self.addCleanup(meeting.doCleanups)
        image_path = meeting.save_picture(b"\x01\x03\x05", "2026-02-25")
        meeting.prepare(confirm=False)
        use_legacy_pdf(meeting.content)
        meeting.command("confirm")
        meeting.client_copy()
        self.assert_rendered_layout(meeting.pdf, legacy=True)

        meeting.command("record", "--answer", "--attendee", "the manager")
        old_pdf = meeting.client_copy()
        meeting.command("lock")
        self.assertEqual(meeting.pdf.read_bytes(), old_pdf)
        meeting.pdf.unlink()
        self.assertEqual(meeting.client_copy(), old_pdf)
        self.assert_rendered_layout(meeting.pdf, legacy=True)

        meeting.meeting_date = "2026-03-05"
        meeting.command("check-promise", "--id", "P-001", "--status", "done")
        meeting.save_picture(b"\x02\x04\x06", "2026-03-04")
        meeting.prepare()
        next_content = meeting.content.with_name("week-4-content.json")
        self.assertEqual(meeting.read_json(next_content)["design"]["pdf"]["layout"], REVISED_BUILD_LAYOUT)
        meeting.command("record", "--answer", "--attendee", "the manager")
        meeting.command("client-copy")
        meeting.command("lock")
        next_pdf = meeting.pdf.with_name("week-4.pdf")
        self.assert_rendered_layout(next_pdf, legacy=False)

        meeting.command("remove-name", "--name", "the manager", "--what", "Personal detail",
                        "--reason", "Asked for removal", "--by", "the owner")
        named_copies = (meeting.pdf.read_bytes(), next_pdf.read_bytes())
        self.assertNotEqual(named_copies[0], old_pdf)
        for pdf, legacy in ((meeting.pdf, True), (next_pdf, False)):
            rendered = self.assert_rendered_layout(pdf, legacy=legacy)
            self.assertNotIn("the manager", rendered)
        meeting.remove_picture(image_path)

        self.assertNotEqual(meeting.pdf.read_bytes(), named_copies[0])
        self.assertNotEqual(next_pdf.read_bytes(), named_copies[1])
        for pdf, legacy in ((meeting.pdf, True), (next_pdf, False)):
            rendered = self.assert_rendered_layout(pdf, legacy=legacy)
            self.assertNotIn("the manager", rendered)
            self.assertIn("Removed on", rendered)
        self.assertNotIn("layout", meeting.read_json(meeting.content)["design"]["pdf"])
        self.assertEqual(meeting.read_json(next_content)["design"]["pdf"]["layout"], REVISED_BUILD_LAYOUT)


@unittest.skipUnless(REPORTLAB, "ReportLab is required for the original Layout C PDF comparison")
class OriginalLayoutCByteTests(RecordedMeetingFixture, unittest.TestCase):
    def command(self, command, *args, setup="", expected=0):
        return super().command(command, *args, setup=cli_date_setup("2026-11-24") + setup,
                               expected=expected)

    def assert_original_copy_survives(self, planned_end, digest, *, answered):
        from reportlab import Version

        if Version != "5.0.0":
            self.skipTest("The original Layout C PDF baseline is pinned to ReportLab 5.0.0")

        self.start(planned_end=planned_end)
        if answered:
            self.add_change(days=1)
        self.prepare(confirm=False)
        set_pdf_layout(self.content, "c")
        self.command("confirm")
        self.record_manual(*(["C-001=yes"] if answered else []))

        original = self.client_copy()
        self.assertEqual(sha256(original).hexdigest(), digest)
        self.assertEqual(self.client_copy(), original)
        if answered:
            self.command("sign", "--by", "the client", "--on", self.meeting_date)
        self.command("lock")
        self.assertEqual(self.client_copy(), original)
        self.pdf.unlink()
        self.assertEqual(self.client_copy(), original)

    # Full stamped bytes captured from disposable copies at 4f9e903, before Fix 1.
    def test_unanswered_copy_with_coincident_markers_keeps_its_bytes(self):
        self.assert_original_copy_survives(
            self.meeting_date, "8a8fff15b6bd7f061eceb4b63c723870de4c863eddfef061c791dde2b508b759",
            answered=False,
        )

    def test_answered_copy_with_squeezed_move_keeps_its_bytes(self):
        self.assert_original_copy_survives(
            "2026-06-26", "c06341aed9d7314987c02b8fecdb26229a69411b243b7b5893c20f8fd37f3881",
            answered=True,
        )
