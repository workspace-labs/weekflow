"""Exercise the owner's saved colour choice through the public commands."""

import re
import subprocess
import sys
import unittest

from test_frozen_meeting_design import READY
from test_pdf_paper import UNCOMPRESSED_PDF, pdf_inks
from test_recorded_meeting import REPORTLAB, STUB_PDF, RecordedMeetingFixture
from test_weekflow import ORIGINAL_PAGE_PREPARE, TOOL, snapshot
from weekflow_tool.meeting_design_colors import STUDIO_COLORS, palette_is_readable


class MeetingColoursTests(RecordedMeetingFixture, unittest.TestCase):
    def prepare_with(self, *options, expected=0):
        result = subprocess.run(
            [sys.executable, str(TOOL), "prepare", str(self.project),
             "--date", self.meeting_date, "--content", str(self.draft), *options],
            cwd=self.scratch, capture_output=True, text=True, encoding="utf-8", timeout=15,
        )
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, expected, output)
        return output

    def test_colour_prompt_precedes_writes_and_standard_is_remembered(self):
        self.start()
        before = snapshot(self.project)
        for values in (None, READY.replace("Approved", "Draft"), "## Ready values\nwhite"):
            design = self.project / "DESIGN.md"
            if values is not None:
                design.write_text(values)
                before = snapshot(self.project)
            with self.subTest(design=values):
                output = self.prepare_with(expected=2)
                self.assertIn("--colors standard", output)
                self.assertIn("--main-color", output)
                self.assertEqual(snapshot(self.project), before)
        self.prepare_with("--colors", "standard")
        self.assertEqual(self.read_json(self.project_file)["meeting_colors"], "standard")
        self.prepare_with()
        saved = self.read_json(self.content)["design"]
        self.assertEqual(saved["page_layout"], "a")
        self.assertEqual(saved["colors"], STUDIO_COLORS)

    def test_project_design_wins_over_a_previous_owner_choice(self):
        self.start()
        self.prepare_with("--main-color", "#0F766E")
        design = self.project / "DESIGN.md"
        design.write_text(READY, encoding="utf-8")
        self.prepare_with()
        self.assertEqual(self.read_json(self.content)["design"]["colors"]["main"], "#734225")
        self.assertEqual(self.read_json(self.project_file)["meeting_colors"], {"main": "#0F766E"})
        self.assertEqual(design.read_text(encoding="utf-8"), READY)

    def test_usable_project_design_prepares_without_a_saved_owner_choice(self):
        (self.project / "DESIGN.md").write_text(READY, encoding="utf-8")
        self.start()
        self.prepare_with()
        self.assertEqual(self.read_json(self.content)["design"]["colors"]["main"], "#734225")
        self.assertNotIn("meeting_colors", self.read_json(self.project_file))

    def test_chosen_colours_are_readable_and_shared_with_the_pdf_palette(self):
        self.start()
        output = self.prepare_with("--main-color", "#0f766e", "--background-color", "#ffffff",
                                   "--text-color", "#ffffff")
        self.assertEqual(self.read_json(self.project_file)["meeting_colors"], {
            "main": "#0F766E", "background": "#FFFFFF", "text": "#FFFFFF",
        })
        saved = self.read_json(self.content)["design"]
        self.assertGreaterEqual(len(set(saved["colors"].values())), 6)
        self.assertTrue(palette_is_readable(saved["colors"], saved["main_text"], saved["answer_tint"],
                                            saved["answer_text"], saved["badge_inks"]))
        self.assertEqual(saved["colors"], saved["pdf"]["colors"])
        self.assertIn("--color-main:#0F766E", self.page.read_text(encoding="utf-8").replace(" ", ""))
        self.assertIn("Text changed", output)
        self.assertNotIn("Text changed", self.prepare_with())

    def test_name_removal_treats_the_verified_standard_choice_as_metadata(self):
        self.start()
        self.prepare_with("--colors", "standard")
        self.command("confirm")
        self.command("record", "--answer", "--attendee", "Standard")
        setup = STUB_PDF if not REPORTLAB else ""
        self.command("client-copy", setup=setup)
        self.command("lock")
        self.command("remove-name", "--name", "Standard", "--what", "Personal detail",
                     "--reason", "Privacy request", "--by", "the owner", setup=setup)
        self.assertEqual(self.read_json(self.project_file)["meeting_colors"], "standard")
        self.assertNotIn("Standard", self.read_json(self.week)["attendees"])

    @unittest.skipUnless(REPORTLAB, "ReportLab is required to check the selected PDF ink")
    def test_chosen_main_is_drawn_in_the_client_pdf(self):
        self.start()
        self.prepare_with("--main-color", "#0F766E", "--background-color", "#FFFFFF")
        self.command("confirm")
        self.command("client-copy", setup=UNCOMPRESSED_PDF)
        self.assertIn("#0F766E", pdf_inks(self.pdf.read_bytes()))

    def test_dark_background_requires_paper_choice_and_invalid_flags_do_not_write(self):
        self.start()
        before = snapshot(self.project)
        for options in (("--background-color", "#FFFFFF"), ("--main-color", "teal"),
                        ("--colors", "standard", "--text-color", "#FFFFFF")):
            with self.subTest(options=options):
                self.prepare_with(*options, expected=2)
                self.assertEqual(snapshot(self.project), before)
        colors = ("--main-color", "#0F766E", "--background-color", "#101010")
        self.assertIn("--pdf-paper", self.prepare_with(*colors, expected=2))
        self.assertEqual(snapshot(self.project), before)
        self.prepare_with(*colors, "--pdf-paper", "white")
        saved = self.read_json(self.content)["design"]
        self.assertEqual(saved["colors"]["background"], "#101010")
        self.assertEqual(saved["pdf"]["colors"]["background"], "#FFFFFF")

    def test_confirmed_refresh_and_later_colour_change_preserve_saved_appearance(self):
        self.start()
        self.prepare_with("--main-color", "#0F766E")
        self.prepare_with("--main-color", "#812C38")
        saved = self.read_json(self.content)["design"]
        self.assertEqual(saved["colors"]["main"], "#812C38")
        self.command("confirm")
        before = snapshot(self.project)
        self.assertIn("confirmed", self.prepare_with("--colors", "standard", expected=2))
        self.assertEqual(snapshot(self.project), before)
        design = self.project / "DESIGN.md"
        design.write_text(READY, encoding="utf-8")
        self.prepare_with()
        self.assertEqual(self.read_json(self.content)["design"], saved)
        self.command("confirm")
        self.record_manual()
        self.command("client-copy", setup=STUB_PDF if not REPORTLAB else "")
        self.command("lock")
        prior = {path: path.read_bytes() for path in (self.content, self.page, self.pdf)}
        design.unlink()
        self.command("check-promise", "--id", "P-001", "--status", "done")
        self.meeting_date = "2026-03-05"
        self.prepare_with("--colors", "standard")
        following = self.read_json(self.content.with_name("week-4-content.json"))["design"]
        self.assertEqual(following["colors"], STUDIO_COLORS)
        self.assertEqual({path: path.read_bytes() for path in prior}, prior)

    def test_confirmed_pre_layout_page_refresh_keeps_the_original_look(self):
        self.start()
        self.command("prepare", "--date", self.meeting_date, "--content", str(self.draft),
                     setup=ORIGINAL_PAGE_PREPARE)
        project = self.read_json(self.project_file)
        project.pop("meeting_colors")
        self.write_json(self.project_file, project)
        original = self.page.read_bytes()
        saved_design = self.read_json(self.content)["design"]
        self.assertNotIn("page_layout", saved_design)
        self.command("confirm")

        (self.project / "DESIGN.md").write_text(READY, encoding="utf-8")
        self.prepare_with()

        # Refresh can update the fingerprint when it freezes corrections.
        fingerprint = rb'(?<=Draft fingerprint: )[0-9a-f]{64}|(?<=data-fingerprint=")[0-9a-f]{64}'
        self.assertEqual(re.sub(fingerprint, b"", self.page.read_bytes()), re.sub(fingerprint, b"", original))
        self.assertEqual(self.read_json(self.content)["design"], saved_design)
