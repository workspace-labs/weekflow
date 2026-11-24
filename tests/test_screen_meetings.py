"""Exercise screen snapshots and owner gates through the meeting commands."""

from base64 import b64encode
from hashlib import sha256
from struct import pack
import unittest
from zlib import compress, crc32

from test_recorded_meeting import PDFTOTEXT, RecordedMeetingFixture, REPORTLAB, STUB_PDF


def png(color):
    def chunk(code, data):
        return pack(">I", len(data)) + code + data + pack(">I", crc32(code + data))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", pack(">2I5B", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", compress(bytes((0, *color))))
            + chunk(b"IEND", b""))


class ScreenMeetingTests(RecordedMeetingFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.start()
        self.screens = self.project / "docs/weekly/screens.json"
        self.input_picture = self.scratch / "input.png"

    def add_screen(self, identifier, *, state="finished"):
        self.command("screen", "--id", identifier, "--name", identifier.title(), "--state", state)

    def add_screenshot(self, identifier, color, day="2026-02-25"):
        self.input_picture.write_bytes(png(color))
        self.command("screen-picture", "--id", identifier, "--file", str(self.input_picture),
                     "--kind", "screenshot", "--taken-on", day)
        row = next(row for row in self.read_json(self.screens) if row["id"] == identifier)
        return self.screens.parent / row["picture"]

    def app_ran(self, value):
        self.write_json(self.draft, dict(self.read_json(self.draft), app_ran=value))

    def test_screen_commands_feed_a_gated_snapshot_and_name_each_unchecked_picture(self):
        self.add_screen("menu")
        menu = self.add_screenshot("menu", (11, 12, 13))
        self.add_screen("orders")
        orders = self.add_screenshot("orders", (21, 22, 23))
        self.assertIn("app_ran", self.refuse("prepare", "--date", self.meeting_date,
                                             "--content", str(self.draft)))
        self.app_ran("false")
        self.assertIn("app_ran", self.refuse("prepare", "--date", self.meeting_date,
                                             "--content", str(self.draft)))
        self.app_ran(False)
        self.prepare(confirm=False)
        saved = self.read_json(self.content)
        self.assertIs(saved["app_ran"], False)
        self.assertEqual([row["picture"]["digest"] for row in saved["meeting_screens"]],
                         [sha256(path.read_bytes()).hexdigest() for path in (menu, orders)])
        for command in ("confirm", "client-copy"):
            output = self.refuse(command)
            self.assertIn(menu.name, output)
            self.assertIn(orders.name, output)
        self.command("screen-check", "--id", "menu")
        self.command("screen-check", "--id", "orders")
        self.command("confirm")
        self.command("client-copy", setup="" if REPORTLAB else STUB_PDF)

    def test_later_screen_edits_keep_confirmed_record_signature_and_locked_copies(self):
        self.add_change()
        self.add_screen("menu")
        self.add_screenshot("menu", (11, 12, 13))
        self.command("screen-check", "--id", "menu")
        self.app_ran(True)
        self.prepare()
        original_page = self.page.read_bytes()
        original_snapshot = self.content.read_bytes()

        self.add_screenshot("menu", (21, 22, 23), "2026-02-27")
        self.command("screen", "--id", "menu", "--name", "Updated menu")
        self.assertFalse(self.read_json(self.screens)[0]["owner_checked_on"])
        self.record_saved({"C-001": "yes"})
        self.command("client-copy", setup="" if REPORTLAB else STUB_PDF)
        self.command("sign", "--by", "the client", "--on", "2026-02-26")
        self.command("lock")
        original_pdf = self.pdf.read_bytes()

        self.add_screen("summary", state="not-built")
        self.command("client-copy", setup="" if REPORTLAB else STUB_PDF)
        self.assertEqual(original_page, self.page.read_bytes())
        self.assertEqual(original_snapshot, self.content.read_bytes())
        self.assertEqual(original_pdf, self.pdf.read_bytes())

    def test_missing_and_altered_picture_make_a_confirmed_copy_stale(self):
        self.add_screen("menu")
        image = self.add_screenshot("menu", (11, 12, 13))
        self.command("screen-check", "--id", "menu")
        self.app_ran(True)
        self.prepare()
        original = image.read_bytes()
        image.write_bytes(png((31, 32, 33)))
        self.assertIn(image.name, self.refuse("client-copy"))
        self.assertIn(image.name, self.refuse("prepare", "--date", self.meeting_date,
                                              "--content", str(self.draft)))
        image.unlink()
        self.assertIn(image.name, self.refuse("client-copy"))
        image.write_bytes(original)
        self.command("client-copy", setup="" if REPORTLAB else STUB_PDF)

    def test_confirmation_also_checks_the_earlier_picture_in_a_comparison(self):
        self.add_screen("menu")
        earlier = self.add_screenshot("menu", (11, 12, 13))
        current = self.add_screenshot("menu", (21, 22, 23), "2026-02-26")
        self.command("screen-check", "--id", "menu")
        self.app_ran(True)
        self.prepare(confirm=False)
        for command in ("confirm", "client-copy"):
            output = self.refuse(command)
            self.assertIn(earlier.name, output)
            self.assertNotIn(current.name, output)
            self.assertIn(f"--file screens/{earlier.name}", output)
        self.add_screen("orders")
        self.refuse("screen-check", "--id", "orders", "--file", f"screens/{earlier.name}")
        original = earlier.read_bytes()
        earlier.write_bytes(current.read_bytes())
        self.refuse("screen-check", "--id", "menu", "--file", f"screens/{earlier.name}")
        earlier.write_bytes(original)
        self.assertIn(earlier.name, self.command("screen-check", "--id", "menu",
                                                 "--file", f"screens/{earlier.name}"))
        self.command("confirm")
        self.client_copy()

    def test_checking_earlier_picture_leaves_current_unchecked(self):
        self.add_screen("menu")
        earlier = self.add_screenshot("menu", (11, 12, 13))
        current = self.add_screenshot("menu", (21, 22, 23))
        self.command("screen-check", "--id", "menu", "--file", f"screens/{earlier.name}")
        [row] = self.read_json(self.screens)
        self.assertEqual(row["owner_checked_on"], "")
        self.app_ran(True)
        self.prepare(confirm=False)
        output = self.refuse("confirm")
        self.assertIn(current.name, output)
        self.assertNotIn(earlier.name, output)

    def test_restore_without_pictures_or_pages_continues_to_the_next_lock(self):
        self.add_screen("menu")
        earlier_menu = self.add_screenshot("menu", (11, 12, 13))
        self.add_screen("orders")
        earlier_orders = self.add_screenshot("orders", (21, 22, 23))
        for screen_id in ("menu", "orders"):
            self.command("screen-check", "--id", screen_id)
        self.write_json(self.draft, {"headline": "The bread menu is ready.", "app_ran": True})
        self.prepare()
        self.record_manual()
        self.client_copy()
        self.command("lock")
        old_week = self.week.read_bytes()
        old_tokens = [b64encode(path.read_bytes()).decode("ascii") for path in (earlier_menu, earlier_orders)]
        earlier_menu.parent.rename(self.scratch / "saved-pictures")
        self.page.parent.rename(self.scratch / "saved-pages")
        self.assertFalse(earlier_menu.parent.exists())
        self.assertFalse(self.page.parent.exists())

        self.page.parent.mkdir()
        self.write_json(self.draft, {"headline": "The bread menu is ready.", "app_ran": True})
        next_day = "2026-03-05"
        output = self.command("prepare", "--date", next_day, "--content", str(self.draft))
        self.assertIn("Save a new picture for Menu", output)
        self.assertIn("Save a new picture for Orders", output)
        new_page = self.page.with_name("week-4.html")
        self.assertNotIn('class="screen-new"', new_page.read_text(encoding="utf-8"))

        self.input_picture.write_bytes(png((11, 12, 13)))
        self.assertIn("taken on 2026-02-25", self.refuse(
            "screen-picture", "--id", "menu", "--file", str(self.input_picture),
            "--kind", "screenshot", "--taken-on", "2026-03-04",
        ))
        self.add_screenshot("menu", (31, 32, 33), "2026-03-04")
        self.command("screen-check", "--id", "menu")
        output = self.command("prepare", "--date", next_day, "--content", str(self.draft))
        self.assertIn(earlier_menu.name, output)
        self.assertIn(earlier_orders.name, output)
        markup = new_page.read_text(encoding="utf-8")
        self.assertEqual(markup.count("The picture is no longer available."), 2)
        self.assertEqual(markup.count('class="screen-new"'), 1)
        self.assertEqual(markup.count('src="data:image/'), 1)
        for token in old_tokens:
            self.assertNotIn(token, markup)

        self.command("confirm")
        self.record_manual()
        self.pdf = new_page.with_suffix(".pdf")
        self.client_copy()
        if REPORTLAB and PDFTOTEXT:
            self.assertEqual(self.extract_pdf().count("The picture is no longer available."), 2)
        self.command("lock")
        self.assertTrue(self.read_json(self.week.with_name("week-4.json"))["locked_on"])
        self.assertEqual(self.week.read_bytes(), old_week)

    def test_next_held_comparison_freezes_real_dates_new_and_prior_privacy(self):
        self.add_screen("menu")
        first = self.add_screenshot("menu", (11, 12, 13))
        self.command("screen-check", "--id", "menu")
        self.write_json(self.draft, {"headline": "The bread menu is ready.", "app_ran": True})
        self.prepare()
        self.command("record", "--answer", "--attendee", "the owner")
        self.command("client-copy", setup="" if REPORTLAB else STUB_PDF)
        self.command("lock")
        self.command("no-meeting", "--date", "2026-03-02")
        self.add_screenshot("menu", (21, 22, 23), "2026-02-27")
        current = self.add_screenshot("menu", (31, 32, 33), "2026-02-28")
        self.command("screen-check", "--id", "menu")
        self.command("prepare", "--date", "2026-03-05", "--content", str(self.draft))
        new_content = self.content.with_name("week-5-content.json")
        row = self.read_json(new_content)["meeting_screens"][0]
        self.assertEqual(row["previous_picture"]["file"], f"screens/{first.name}")
        self.assertEqual(row["previous_picture"]["taken_on"], "2026-02-25")
        self.assertEqual(row["picture"]["file"], f"screens/{current.name}")
        self.assertEqual(row["picture"]["taken_on"], "2026-02-28")
        self.assertIs(row["picture"]["new"], True)
        self.command("confirm")
        self.app_ran(False)
        self.command("prepare", "--date", "2026-03-05", "--content", str(self.draft))
        row = self.read_json(new_content)["meeting_screens"][0]
        self.assertIs(row["picture"]["new"], False)

    def test_unchanged_picture_has_its_original_date_without_a_comparison_or_new_mark(self):
        self.add_screen("menu")
        image = self.add_screenshot("menu", (11, 12, 13))
        self.command("screen-check", "--id", "menu")
        self.write_json(self.draft, {"headline": "The bread menu is ready.", "app_ran": True})
        self.prepare()
        self.record_manual()
        self.client_copy()
        self.command("lock")
        self.command("screen", "--id", "menu", "--name", "Bread menu")
        self.command("prepare", "--date", "2026-03-05", "--content", str(self.draft))
        [row] = self.read_json(self.content.with_name("week-4-content.json"))["meeting_screens"]
        self.assertEqual(row["name"], "Bread menu")
        self.assertEqual(row["picture"]["file"], f"screens/{image.name}")
        self.assertEqual(row["picture"]["taken_on"], "2026-02-25")
        self.assertIs(row["picture"]["new"], False)
        self.assertIsNone(row["previous_picture"])
