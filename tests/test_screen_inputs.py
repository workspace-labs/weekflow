"""Try screen-list and picture commands on disposable project copies."""

from datetime import date, timedelta
from struct import pack
import shutil
import subprocess
import unittest
from zlib import crc32

from test_recorded_meeting import RecordedMeetingFixture
from test_screen_meetings import png


SCREEN_FIELDS = {
    "id", "order", "name", "state", "source", "picture", "picture_kind", "taken_on",
    "previous_picture", "owner_checked_on",
}


def png_chunk(tag, payload):
    return pack(">I", len(payload)) + tag + payload + pack(">I", crc32(tag + payload))


def tagged_png():
    original = png((40, 80, 120))
    metadata = b"".join((
        png_chunk(b"tEXt", b"Comment\x00Sample caption"),
        png_chunk(b"zTXt", b"Comment\x00\x00x\x9cS\x00\x00\x00!\x00!"),
        png_chunk(b"iTXt", b"Description\x00\x00\x00\x00\x00Sample description"),
        png_chunk(b"eXIf", b"II\x2a\x00\x08\x00\x00\x00\x00\x00\x00\x00\x00\x00"),
    ))
    return original[:33] + metadata + original[33:]


def jpeg(width=1, height=1, *, metadata=False, tables=True):
    """One grayscale pixel encoded with DC zero and an end-of-block symbol."""
    def segment(code, payload):
        return b"\xff" + bytes((code,)) + pack(">H", len(payload) + 2) + payload

    data = b"\xff\xd8"
    if metadata:
        data += segment(0xE1, b"Exif\x00\x00Example GPS data")
        data += segment(0xE2, b"Example profile")
        data += segment(0xFE, b"Example comment")
    if tables:
        data += segment(0xDB, bytes(1) + b"\x01" * 64)
        one_code = b"\x01" + bytes(16)
        data += segment(0xC4, b"\x00" + one_code + b"\x10" + one_code)
    data += segment(0xC0, pack(">BHHBBBB", 8, height, width, 1, 1, 0x11, 0))
    return data + segment(0xDA, b"\x01\x01\x00\x00\x3f\x00") + b"\x3f\xff\xd9"


class ScreenInputs(RecordedMeetingFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.weekly = self.project_file.parent
        self.screens = self.weekly / "screens.json"
        self.ignore = self.weekly / ".gitignore"
        self.source_picture = self.scratch / "camera.png"
        self.flow = self.project / "docs/app-flow/app-flow.md"
        self.flow.parent.mkdir()

    def screen(self, identifier="menu", name="Menu", state="finished"):
        self.command("screen", "--id", identifier, "--name", name, "--state", state)

    def picture_args(self, *, identifier="menu", path=None, kind="screenshot", day="2026-02-25"):
        args = ["--id", identifier, "--file", str(path or self.source_picture), "--kind", kind]
        if day is not None:
            args.extend(("--taken-on", day))
        return args

    def save_picture(self, data, **options):
        self.source_picture.write_bytes(data)
        self.command("screen-picture", *self.picture_args(**options))
        row = next(row for row in self.read_json(self.screens) if row["id"] == options.get("identifier", "menu"))
        self.assertEqual(self.source_picture.read_bytes(), data)
        return self.weekly / row["picture"]

    @unittest.skipUnless(shutil.which("git"), "Git is needed to prove ignored paths.")
    def test_weekly_ignores_preserve_existing_lines_and_override_directory_negation(self):
        def git(*args):
            result = subprocess.run(
                ["git", "-c", "init.templateDir=", *args], cwd=self.project, text=True, encoding="utf-8",
                capture_output=True, timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout.splitlines()

        git("init", "-q")
        root_ignore = self.project / ".gitignore"
        root_ignore.write_bytes(b"# unrelated project rule\n.cache/\n")
        existing = b"# retained\r\n/screens/\r\n!**/screens/\r\n/pages/"
        self.ignore.write_bytes(existing)
        self.start()
        self.screen()
        picture = self.save_picture(png((10, 20, 30)))
        self.page.write_bytes(b"Synthetic HTML")
        self.pdf.write_bytes(b"Synthetic PDF")
        paths = [path.relative_to(self.project).as_posix() for path in (picture, self.page, self.pdf)]
        self.assertEqual(git("check-ignore", "--", *paths), paths)
        self.assertEqual(self.ignore.read_bytes(), existing + b"\r\nscreens/\r\n")
        self.assertEqual(root_ignore.read_bytes(), b"# unrelated project rule\n.cache/\n")
        unignored = git("ls-files", "--others", "--exclude-standard")
        self.assertIn("docs/weekly/project.json", unignored)
        self.assertIn("docs/weekly/screens.json", unignored)
        self.assertTrue(set(paths).isdisjoint(unignored))

    def test_flow_adds_once_and_keeps_the_first_order_states_and_pictures(self):
        self.flow.write_text(
            "# Sample product\n\n## Ordering\n"
            "1. Home [grid]: Sees choices.\n"
            "   ! Empty menu: Sees an empty view.\n"
            "   shot: ../../outside.png\n"
            "2. Menu: Sees bread.\n"
            "\n## Pick up\n"
            "  1. HOME [GRID]: Sees choices again.\n"
            "  2. Pick up: Sees the time.\n"
            "   ! 3. Retry: Goes back.\n"
            "\n```md\n## Quoted example\n1. Quoted: Sees a code example.\n```\n",
            encoding="utf-8",
        )
        self.start()
        self.command("screens-from-flow")
        rows = self.read_json(self.screens)
        self.assertEqual([row["name"] for row in rows], ["Home", "Menu", "Pick up"])
        for row in rows:
            self.assertEqual(set(row), SCREEN_FIELDS)
            self.assertEqual((row["source"], row["state"], row["picture"]), ("frameflow", "not built", ""))
        code = rows[0]["id"]
        self.command("screen", "--id", code, "--state", "being-built")
        picture = self.save_picture(png((30, 20, 10)), identifier=code)
        saved_rows = self.read_json(self.screens)
        self.command("screens-from-flow")
        self.assertEqual(self.read_json(self.screens), saved_rows)
        self.flow.write_text(
            "# Sample product\n## Pick up\n1. Pick up: Sees the time.\n"
            "2. <b>Receipt</b>: Sees a receipt.\n", encoding="utf-8",
        )
        message = self.command("screens-from-flow")
        self.assertIn("Home", message)
        self.assertIn("no longer in the flow", message)
        updated = self.read_json(self.screens)
        self.assertEqual(updated[:3], saved_rows)
        self.assertEqual(updated[3]["name"], "<b>Receipt</b>")
        self.assertEqual(updated[3]["order"], 4)
        self.assertTrue(picture.is_file())
        draft = self.read_json(self.draft)
        self.write_json(self.draft, dict(draft, app_ran=True))
        self.command("prepare", "--date", self.meeting_date, "--content", str(self.draft))
        self.assertIn("&lt;b&gt;Receipt&lt;/b&gt;", self.page.read_text(encoding="utf-8"))

    def test_screen_ids_orders_and_names_are_checked_at_entry(self):
        self.start()
        self.screen()
        self.assertEqual(self.read_json(self.screens)[0]["source"], "owner")
        for args in (("--id", "../menu", "--name", "Menu"),
                     ("--id", "other", "--name", "Other", "--order", "1"),
                     ("--id", "other", "--name", "Other", "--order", "0"),
                     ("--id", "other", "--name", "Menu 🛰"),
                     ("--id", "other")):
            with self.subTest(args=args):
                self.refuse("screen", *args)

    def test_pictures_are_bounded_and_must_use_a_real_supported_format(self):
        self.start()
        self.screen()
        too_wide = png((10, 20, 30))
        too_wide = too_wide[:8] + png_chunk(b"IHDR", pack(">2I5B", 6001, 1, 8, 2, 0, 0, 0)) + too_wide[33:]
        for data, wording in (
            (b"<svg xmlns=\"http://www.w3.org/2000/svg\"/>", "valid PNG or JPEG"),
            (b" " * 1_000_001, "1 MB"),
            (png((12, 23, 34))[:-1], "valid PNG or JPEG"),
            (b"\xff\xd8\xff\xd9", "valid PNG or JPEG"),
            (jpeg(tables=False), "valid PNG or JPEG"),
            (too_wide, "6000 pixels"),
            (jpeg(height=6001), "6000 pixels"),
        ):
            with self.subTest(wording=wording, header=data[:2]):
                self.source_picture.write_bytes(data)
                self.assertIn(wording.casefold(), self.refuse("screen-picture", *self.picture_args()))
        for path in (self.scratch, self.scratch / "missing.jpg"):
            with self.subTest(path=path.name):
                self.assertIn("regular file", self.refuse("screen-picture", *self.picture_args(path=path)))
        self.assertEqual(self.read_json(self.screens)[0]["picture"], "")

    def test_picture_input_rejects_a_link_to_another_file(self):
        self.start()
        self.screen()
        self.source_picture.write_bytes(png((12, 34, 56)))
        link = self.scratch / "picture-link.png"
        try:
            link.symlink_to(self.source_picture)
        except (OSError, NotImplementedError):
            self.skipTest("This system does not allow test symlinks.")
        self.assertIn("regular file", self.refuse("screen-picture", *self.picture_args(path=link)))

    def test_picture_metadata_is_removed_and_matches_by_clean_bytes(self):
        self.start()
        self.screen()
        first = self.save_picture(tagged_png())
        self.assertEqual(first.read_bytes(), png((40, 80, 120)))
        self.assertIn("-w3-", first.name)
        self.command("screen-check", "--id", "menu")
        self.source_picture.write_bytes(first.read_bytes())
        self.command("screen-picture", *self.picture_args())
        self.assertTrue(self.read_json(self.screens)[0]["owner_checked_on"])
        message = self.refuse("screen-picture", *self.picture_args(day="2026-02-26"))
        self.assertIn("2026-02-25", message)
        second = self.save_picture(jpeg(metadata=True), day="2026-02-26")
        self.assertEqual(second.suffix, ".jpg")
        self.assertNotEqual(first, second)
        self.assertEqual(second.read_bytes(), jpeg())
        self.assertEqual(first.read_bytes(), png((40, 80, 120)))
        row = self.read_json(self.screens)[0]
        self.assertEqual(row["previous_picture"], f"screens/{first.name}")
        self.assertEqual(row["owner_checked_on"], "")

    def test_screenshot_dates_and_design_states_are_checked(self):
        self.start()
        self.screen(state="not-built")
        self.source_picture.write_bytes(png((10, 20, 30)))
        self.assertIn("finished or being built", self.refuse("screen-picture", *self.picture_args()))
        self.assertIn("leave out --taken-on",
                      self.refuse("screen-picture", *self.picture_args(kind="design")))
        design = self.save_picture(png((10, 20, 30)), kind="design", day=None)
        row = self.read_json(self.screens)[0]
        self.assertEqual((row["picture_kind"], row["taken_on"]), ("design", ""))
        self.command("screen", "--id", "menu", "--state", "finished")
        self.assertIn("only for a screen marked not built",
                      self.refuse("screen-picture", *self.picture_args(kind="design", day=None)))
        self.assertIn("already saved as a design", self.refuse("screen-picture", *self.picture_args()))
        for day, message in ((None, "real date"), ("2026-02-30", "real date"),
                             ((date.today() + timedelta(days=1)).isoformat(), "today or earlier")):
            with self.subTest(day=day):
                self.assertIn(message, self.refuse("screen-picture", *self.picture_args(day=day)))
        self.assertEqual(design.read_bytes(), png((10, 20, 30)))
