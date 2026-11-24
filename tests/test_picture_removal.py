"""Try picture removal across saved meetings and interrupted writes."""

from base64 import b64decode, b64encode
from datetime import date
import shutil
import struct
import unittest
import zlib

from test_recorded_meeting import BLOCK_REPORTLAB, PDFTOTEXT, REPORTLAB, STUB_PDF, RecordedMeetingFixture
from test_weekflow import snapshot


def test_png(color):
    def chunk(kind, data):
        packet = kind + data
        return struct.pack(">I", len(data)) + packet + struct.pack(">I", zlib.crc32(packet))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress((b"\x00" + color * 2) * 2))
            + chunk(b"IEND", b""))


REASON = "The owner found customer data"
STUB_REMOVAL_PDF = STUB_PDF + """
from weekflow_tool import picture_removal, removal
removal.render_pdf = client_pdf.render_pdf
picture_removal.render_pdf = client_pdf.render_pdf
"""


class PictureRemovalTests(RecordedMeetingFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.weekly = self.project / "docs/weekly"
        self.screens = self.weekly / "screens.json"
        draft = self.read_json(self.draft)
        self.write_json(self.draft, dict(draft, app_ran=True))
        self.start()
        self.command("screen", "--id", "pickup", "--name", "Pickup", "--state", "finished")

    def save_picture(self, color, taken_on):
        picture = self.scratch / "sample.png"
        picture.write_bytes(test_png(color))
        self.command("screen-picture", "--id", "pickup", "--file", str(picture),
                     "--kind", "screenshot", "--taken-on", taken_on)
        self.command("screen-check", "--id", "pickup")
        return self.read_json(self.screens)[0]["picture"]

    def close_meeting(self):
        self.prepare()
        self.record_manual()
        self.client_copy()
        self.command("lock")

    def remove_picture(self, picture, *, setup=None, expected=0):
        if setup is None:
            setup = "" if REPORTLAB else STUB_REMOVAL_PDF
        return self.command("remove-picture", "--id", "pickup", "--file", picture,
                            "--what", "Customer data in a picture", "--reason", REASON,
                            "--by", "the owner", setup=setup, expected=expected)

    def assert_picture_bytes_gone(self, raw):
        for path in self.weekly.rglob("*"):
            if path.is_file():
                contents = path.read_bytes()
                self.assertNotIn(raw, contents, path.name)
                self.assertNotIn(b64encode(raw), contents, path.name)

    def test_removal_replaces_only_the_matching_picture_across_locked_weeks(self):
        earlier = self.save_picture(b"\x01\x03\x05", "2026-02-25")
        earlier_bytes = (self.weekly / earlier).read_bytes()
        self.close_meeting()
        record = self.week.read_bytes()

        self.meeting_date = "2026-03-05"
        self.command("check-promise", "--id", "P-001", "--status", "done")
        later = self.save_picture(b"\x02\x04\x06", "2026-03-04")
        later_bytes = (self.weekly / later).read_bytes()
        self.close_meeting()
        next_week = self.week.with_name("week-4.json")
        next_page = self.page.with_name("week-4.html")
        next_copy = next_page.with_suffix(".pdf")
        second_record = next_week.read_bytes()
        second_copy = next_copy.read_bytes()

        output = self.remove_picture(earlier)
        self.assertIn("Changed weeks 3, 4.", output)
        self.assertIn("cannot be recalled", output)
        self.assertEqual(record, self.week.read_bytes())
        self.assertEqual(second_record, next_week.read_bytes())
        self.assertNotEqual(second_copy, next_copy.read_bytes())
        self.assertEqual(later_bytes, (self.weekly / later).read_bytes())
        self.assertEqual(self.read_json(self.screens)[0]["picture"], later)
        self.assertFalse(self.read_json(self.screens)[0].get("previous_picture"))
        for shown in (self.page, next_page):
            self.assertRegex(shown.read_text(), rf"Removed on .+ because {REASON}")
            screen = self.read_json(shown.with_name(f"{shown.stem}-content.json"))["meeting_screens"][0]
            pictures = [slot for slot in (screen["picture"], screen["previous_picture"]) if slot]
            self.assertEqual([slot["file"] for slot in pictures if "removed" in slot], [earlier])
            self.assertRegex(next(slot["removed"] for slot in pictures if "removed" in slot),
                             rf"Removed on .+ because {REASON}")
        self.assertIn(b64encode(later_bytes), next_page.read_bytes())
        self.assert_picture_bytes_gone(earlier_bytes)
        corrections = self.read_json(self.weekly / "corrections.json")
        self.assertEqual([(row["week"], row["kind"], row["date"]) for row in corrections],
                         [(3, "removal", date.today().isoformat()),
                          (4, "removal", date.today().isoformat())])
        self.command("client-copy", setup="" if REPORTLAB else STUB_PDF)
        self.assertFalse(list(self.weekly.rglob(".weekflow-*")))

    @unittest.skipUnless(REPORTLAB and PDFTOTEXT, "ReportLab and pdftotext are required")
    def test_removal_notice_appears_where_the_picture_was_in_the_pdf(self):
        image = self.save_picture(b"\x01\x03\x05", "2026-02-25")
        self.close_meeting()
        self.assertIn(b"/Subtype /Image", self.pdf.read_bytes())

        self.remove_picture(image)

        self.assertRegex(" ".join(self.extract_pdf().split()), rf"Removed on .+ because {REASON}")
        self.assertNotIn(b"/Subtype /Image", self.pdf.read_bytes())

    def test_duplicate_picture_bytes_are_removed_with_one_correction_for_the_week(self):
        first = self.save_picture(b"\x01\x03\x05", "2026-02-25")
        raw = (self.weekly / first).read_bytes()
        self.command("screen", "--id", "menu", "--name", "Menu", "--state", "finished")
        self.command("screen-picture", "--id", "menu", "--file", str(self.scratch / "sample.png"),
                     "--kind", "screenshot", "--taken-on", "2026-02-25")
        self.command("screen-check", "--id", "menu")
        self.close_meeting()
        files = [row["picture"] for row in self.read_json(self.screens)]
        self.assertEqual(len(set(files)), 2)

        self.remove_picture(first)

        self.assertTrue(all(not (self.weekly / picture).exists() for picture in files))
        self.assert_picture_bytes_gone(raw)
        content = self.read_json(self.content)["meeting_screens"]
        self.assertTrue(all("removed" in row["picture"] for row in content))
        corrections = self.read_json(self.weekly / "corrections.json")
        self.assertEqual([(row["week"], row["kind"]) for row in corrections], [(3, "removal")])

    def test_rebuilds_a_surviving_pdf_without_restoring_missing_html(self):
        image = self.save_picture(b"\x01\x03\x05", "2026-02-25")
        self.close_meeting()
        original_pdf = self.pdf.read_bytes()
        self.page.unlink()

        self.remove_picture(image)

        self.assertFalse(self.page.exists())
        self.assertNotEqual(self.pdf.read_bytes(), original_pdf)
        self.assertFalse((self.weekly / image).exists())

    def test_locked_copies_without_content_are_kept_byte_identical(self):
        image = self.save_picture(b"\x01\x03\x05", "2026-02-25")
        self.close_meeting()
        self.content.unlink()
        original_page = self.page.read_bytes()
        original_pdf = self.pdf.read_bytes()

        output = self.remove_picture(image, setup=BLOCK_REPORTLAB)

        self.assertRegex(output, r"(?i)week 3[^\n]*could not be rebuilt")
        self.assertIn("may still hold the picture", output)
        self.assertEqual(self.page.read_bytes(), original_page)
        self.assertEqual(self.pdf.read_bytes(), original_pdf)
        self.assertFalse((self.weekly / image).exists())
        self.assertFalse(self.read_json(self.screens)[0].get("picture"))
        self.assertFalse(list(self.weekly.rglob(".weekflow-*")))

    def test_missing_renderer_refuses_before_changing_any_file_and_can_retry(self):
        image = self.save_picture(b"\x01\x03\x05", "2026-02-25")
        self.close_meeting()
        original_pdf = self.pdf.read_bytes()
        (self.weekly / ".gitignore").write_text("# Existing local rule\n")
        original = snapshot(self.scratch)

        output = self.remove_picture(image, setup=BLOCK_REPORTLAB, expected=2)

        self.assertIn("reportlab package", output)
        self.assertEqual(snapshot(self.scratch), original)
        self.remove_picture(image)
        self.assertNotEqual(self.pdf.read_bytes(), original_pdf)
        self.assertRegex(self.page.read_text(), rf"Removed on .+ because {REASON}")
        self.assertFalse((self.weekly / image).exists())

    def test_removes_a_known_lost_picture_after_a_git_only_restore(self):
        image = self.save_picture(b"\x01\x03\x05", "2026-02-25")
        self.close_meeting()
        record = self.week.read_bytes()
        (self.weekly / "screens").rename(self.scratch / "lost-screens")
        (self.weekly / "pages").rename(self.scratch / "lost-pages")
        before = snapshot(self.weekly)

        unknown_filename = image.replace("-1.png", "-2.png")
        self.assertNotEqual(unknown_filename, image)
        self.assertIn("known saved picture", self.remove_picture(unknown_filename, expected=2))
        self.assertEqual(snapshot(self.weekly), before)
        failure = """
replace = os.replace

def interrupt(source, destination):
    if os.path.basename(destination) == 'screens.json':
        os._exit(92)
    replace(source, destination)

os.replace = interrupt
"""
        self.remove_picture(image, setup=BLOCK_REPORTLAB + failure, expected=92)
        recovery = self.command("screen", "--id", "pickup", "--name", "Pickup")

        self.assertIn("Recovered removal changed no weeks.", recovery)
        self.assertNotIn("hold the name", recovery)
        self.assertFalse(self.read_json(self.screens)[0]["picture"])
        self.assertEqual(self.week.read_bytes(), record)
        self.assertFalse((self.weekly / "screens").exists())
        self.assertFalse((self.weekly / "pages").exists())
        self.assertFalse(list(self.weekly.rglob(".weekflow-*")))

    def test_lost_picture_known_only_to_a_snapshot_can_be_remarked(self):
        image = self.save_picture(b"\x01\x03\x05", "2026-02-25")
        self.close_meeting()
        self.save_picture(b"\x02\x04\x06", "2026-02-26")
        current = self.save_picture(b"\x03\x05\x07", "2026-02-27")
        self.assertNotIn(image, self.screens.read_text())
        (self.weekly / image).unlink()
        original_page, original_pdf = self.page.read_bytes(), self.pdf.read_bytes()

        output = self.remove_picture(image)

        self.assertIn("Changed weeks 3.", output)
        self.assertRegex(output, r"Week 3 copies .* could not be rebuilt")
        self.assertEqual(self.page.read_bytes(), original_page)
        self.assertEqual(self.pdf.read_bytes(), original_pdf)
        self.assertEqual(self.read_json(self.screens)[0]["picture"], current)
        slot = self.read_json(self.content)["meeting_screens"][0]["picture"]
        self.assertIn(REASON, slot["removed"])

    def test_lost_picture_exception_does_not_accept_altered_existing_bytes(self):
        image = self.save_picture(b"\x01\x03\x05", "2026-02-25")
        self.close_meeting()
        (self.weekly / image).write_bytes(test_png(b"\x02\x04\x06"))
        before = snapshot(self.weekly)

        self.assertIn("missing or changed", self.remove_picture(image, expected=2))
        self.assertEqual(snapshot(self.weekly), before)

    def test_lost_source_still_checks_for_an_extra_html_with_the_picture(self):
        image = self.save_picture(b"\x01\x03\x05", "2026-02-25")
        self.close_meeting()
        shutil.copyfile(self.page, self.page.with_name("extra.html"))
        (self.weekly / image).unlink()
        before = snapshot(self.weekly)

        self.assertIn("extra.html", self.remove_picture(image, expected=2))
        self.assertEqual(snapshot(self.weekly), before)

    def test_removing_a_lost_picture_replaces_the_prepared_unavailable_slot(self):
        image = self.save_picture(b"\x01\x03\x05", "2026-02-25")
        (self.weekly / image).unlink()
        self.prepare(confirm=False)
        row, = self.read_json(self.content)["meeting_screens"]
        self.assertTrue(row["picture"]["unavailable"])

        self.remove_picture(image)

        row, = self.read_json(self.content)["meeting_screens"]
        self.assertIn(REASON, row["picture"]["removed"])
        self.assertNotIn("unavailable", row["picture"])
        self.assertRegex(self.page.read_text(), rf"Removed on .+ because {REASON}")
        self.command("confirm")

    def test_a_locked_pdf_that_differs_from_its_snapshot_is_reported_and_kept(self):
        earlier = self.save_picture(b"\x01\x03\x05", "2026-02-25")
        self.close_meeting()
        later = self.save_picture(b"\x02\x04\x06", "2026-02-26")
        original_page = self.page.read_bytes()
        unmatched_pdf = self.pdf.read_bytes() + b"\n% changed copy\n"
        self.pdf.write_bytes(unmatched_pdf)

        output = self.remove_picture(later)

        self.assertIn("No weeks changed.", output)
        self.assertRegex(output, r"Week 3 copies \(PDF\) could not be rebuilt")
        self.assertEqual(self.pdf.read_bytes(), unmatched_pdf)
        self.assertEqual(self.page.read_bytes(), original_page)
        self.assertTrue((self.weekly / earlier).exists())
        self.assertFalse((self.weekly / later).exists())

    def test_refuses_an_extra_copy_of_the_picture_before_changing_anything(self):
        image = self.save_picture(b"\x01\x03\x05", "2026-02-25")
        self.close_meeting()
        raw = (self.weekly / image).read_bytes()
        (self.weekly / "pages/extra.html").write_bytes(b"<img src='data:image/png;base64," + b64encode(raw) + b"'>")
        original = snapshot(self.weekly)

        output = self.remove_picture(image, expected=2)

        self.assertIn("extra.html", output)
        self.assertEqual(snapshot(self.weekly), original)

    def test_refuses_to_journal_replacement_text_that_still_contains_the_picture(self):
        image = self.save_picture(b"\x01\x03\x05", "2026-02-25")
        encoded = b64encode((self.weekly / image).read_bytes()).decode("ascii")
        draft = self.read_json(self.draft)
        self.write_json(self.draft, dict(draft, headline=encoded))
        self.close_meeting()
        self.write_json(self.draft, draft)
        original = snapshot(self.weekly)

        output = self.remove_picture(image, expected=2)

        self.assertIn("week-3-content.json", output)
        self.assertEqual(snapshot(self.weekly), original)

    def test_picture_removal_restores_ignores_before_publishing_replacements(self):
        image = self.save_picture(b"\x01\x03\x05", "2026-02-25")
        self.close_meeting()
        ignore = self.weekly / ".gitignore"
        ignore.write_text("# Local rule\nbackup/\n")
        trace = """
sys.path.insert(0, os.path.dirname(sys.argv[1]))
from weekflow_tool import lock_transaction as transaction
from weekflow_tool.screens import IGNORE_FILE

publish = transaction.replace_redacted_file

def check_ignores(files, relative, data):
    if relative == transaction.REDACTION_FILE:
        assert files.read_text(IGNORE_FILE).splitlines() == ['# Local rule', 'backup/', 'screens/', 'pages/']
    publish(files, relative, data)

transaction.replace_redacted_file = check_ignores
"""

        self.remove_picture(image, setup=("" if REPORTLAB else STUB_REMOVAL_PDF) + trace)

        self.assertRegex(self.page.read_text(), rf"Removed on .+ because {REASON}")

    def test_recover_after_every_publication_without_staging_removed_bytes(self):
        image = self.save_picture(b"\x01\x03\x05", "2026-02-25")
        raw = (self.weekly / image).read_bytes()
        self.close_meeting()
        before = snapshot(self.weekly)
        self.remove_picture(image)
        after = snapshot(self.weekly)
        affected = set(before).symmetric_difference(after)
        affected.update(path for path in before.keys() & after.keys()
                        if before[path] != after[path])
        # Journal publication followed by each final write or unlink.
        for stop in range(0, len(affected) + 1):
            with self.subTest(after_publication=stop):
                for current in self.weekly.iterdir():
                    if current.is_dir():
                        shutil.rmtree(current)
                    else:
                        current.unlink()
                for path, data in before.items():
                    target = self.weekly / path
                    if data is None:
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(data)
                failure = f"""
sys.path.insert(0, os.path.dirname(sys.argv[1]))
from weekflow_tool import lock_transaction

publish = lock_transaction.publish_redaction_entry
count = 0

def interrupt(files, relative, data):
    global count
    if count == {stop}:
        os._exit(91)
    publish(files, relative, data)
    count += 1
    if count == {stop}:
        os._exit(91)

lock_transaction.publish_redaction_entry = interrupt
"""
                renderer = "" if REPORTLAB else STUB_REMOVAL_PDF
                self.remove_picture(image, setup=renderer + failure, expected=91)
                for path in self.weekly.rglob(".weekflow-*"):
                    contents = path.read_bytes()
                    self.assertNotIn(raw, contents)
                    self.assertNotIn(b64encode(raw), contents)
                    if path.suffix == ".json":
                        journal = self.read_json(path)
                        self.assertFalse(any(entry["path"].endswith(image) and entry["data"] is not None
                                             for entry in journal["entries"]))
                        for entry in journal["entries"]:
                            if entry["data"] is not None:
                                decoded = b64decode(entry["data"])
                                self.assertNotIn(raw, decoded, entry["path"])
                                self.assertNotIn(b64encode(raw), decoded, entry["path"])
                output = self.command("client-copy", setup="" if REPORTLAB else STUB_PDF)
                self.assertIn("Recovered removal changed weeks 3.", output)
                self.assertNotIn("hold the name", output)
                self.assertEqual(snapshot(self.weekly), after)
                self.assert_picture_bytes_gone(raw)

    def test_recovery_when_a_staged_file_was_not_yet_published(self):
        image = self.save_picture(b"\x01\x03\x05", "2026-02-25")
        raw = (self.weekly / image).read_bytes()
        self.close_meeting()
        seed = self.scratch / "before-removal"
        shutil.copytree(self.project, seed)
        self.remove_picture(image)
        after = snapshot(self.weekly)

        for destination in (".weekflow-removal.json", "corrections.json", "screens.json",
                            "week-3-content.json", "week-3.html", "week-3.pdf"):
            with self.subTest(destination=destination):
                self.project = self.scratch / f"before-{destination}"
                shutil.copytree(seed, self.project)
                self.weekly = self.project / "docs/weekly"
                failure = f"""
replace = os.replace

def interrupt(source, destination):
    if os.path.basename(destination) == {destination!r}:
        os._exit(92)
    replace(source, destination)

os.replace = interrupt
"""
                renderer = "" if REPORTLAB else STUB_REMOVAL_PDF
                self.remove_picture(image, setup=renderer + failure, expected=92)
                staged = list(self.weekly.rglob(".weekflow-removal-stage"))
                self.assertEqual(len(staged), 1)
                contents = staged[0].read_bytes()
                self.assertNotIn(raw, contents)
                self.assertNotIn(b64encode(raw), contents)
                if destination == ".weekflow-removal.json":
                    # The removal had only been planned. Re-run it after the orphan stage is cleared.
                    self.assertTrue((self.weekly / image).exists())
                    self.remove_picture(image)
                else:
                    output = self.command("client-copy", setup="" if REPORTLAB else STUB_PDF)
                    self.assertIn("Recovered removal changed weeks 3.", output)
                self.assertEqual(snapshot(self.weekly), after)
                self.assert_picture_bytes_gone(raw)

    def test_name_removal_covers_live_screens_and_the_meeting_snapshot(self):
        self.command("screen", "--id", "pickup", "--name", "Pickup with Sam")
        picture = self.save_picture(b"\x02\x04\x06", "2026-02-25")
        self.close_meeting()
        original_picture = (self.weekly / picture).read_bytes()
        ignore = self.weekly / ".gitignore"
        ignore.write_text("# Local rule\nbackup/\n")

        self.command("remove-name", "--name", "Sam", "--what", "Personal name in the screen title",
                     "--reason", "The owner requested removal", "--by", "the owner",
                     setup="" if REPORTLAB else STUB_REMOVAL_PDF)

        self.assertIn("Pickup with Removed on", self.read_json(self.screens)[0]["name"])
        self.assertIn("Pickup with Removed on", self.read_json(self.content)["meeting_screens"][0]["name"])
        self.assertIn("Pickup with Removed on", self.page.read_text())
        self.assertNotIn("Pickup with Sam", self.page.read_text())
        self.assertEqual((self.weekly / picture).read_bytes(), original_picture)
        self.assertEqual(ignore.read_text().splitlines(), ["# Local rule", "backup/", "screens/", "pages/"])

    def test_name_removal_does_not_treat_picture_metadata_as_a_personal_name(self):
        self.command("screen", "--id", "pickup", "--name", "Pickup with Digest")
        self.save_picture(b"\x01\x03\x05", "2026-02-25")
        self.command("screen", "--id", "display", "--name", "Display with Design")
        design = self.scratch / "design.png"
        design.write_bytes(test_png(b"\x02\x04\x06"))
        self.command("screen-picture", "--id", "display", "--file", str(design), "--kind", "design")
        self.command("screen-check", "--id", "display")
        metadata = {path: path.read_bytes() for path in (self.weekly / "screens").rglob("*.json")}

        for name in ("Digest", "Design"):
            self.command("remove-name", "--name", name, "--what", "Personal name in a screen title",
                         "--reason", "The owner requested removal", "--by", "the owner")

        self.assertTrue(all("Removed on" in row["name"] for row in self.read_json(self.screens)))
        self.assertEqual({path: path.read_bytes() for path in metadata}, metadata)

    def test_name_removal_still_checks_unexpected_fields_in_picture_metadata(self):
        self.command("screen", "--id", "pickup", "--name", "Pickup with Sam")
        self.save_picture(b"\x01\x03\x05", "2026-02-25")
        receipt, = (self.weekly / "screens/.checked").glob("*.json")
        self.write_json(receipt, dict(self.read_json(receipt), note="Sam"))
        original = snapshot(self.weekly)

        output = self.command("remove-name", "--name", "Sam", "--what", "Personal name in a screen title",
                              "--reason", "The owner requested removal", "--by", "the owner", expected=2)

        self.assertIn("An extra file", output)
        self.assertEqual(snapshot(self.weekly), original)
