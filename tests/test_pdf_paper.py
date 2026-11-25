"""Exercise PDF paper choices through the local meeting commands."""

from base64 import b32encode
import json
import re
import shutil
import sys
import unittest

import test_docs_meetings as docs
from test_frozen_meeting_design import READY
from test_pdf_layout_snapshot import use_legacy_pdf
from test_recorded_meeting import PDFTOTEXT, REPORTLAB, STUB_PDF, RecordedMeetingFixture
from test_weekflow import TOOL, snapshot


sys.path.insert(0, str(TOOL.parent))
from weekflow_tool.meeting_design_colors import BADGE_ROLES, STUDIO_COLORS, badge_contrast, contrast


DARK = (READY.replace("#FAF6EE", "#14141A").replace("#F3E7D3", "#272730")
        .replace("#21150C", "#F6F6FA").replace("#624632", "#D0D0D8")
        .replace("#734225", "#FEEAC3").replace("#CBBBA8", "#52525D")
        .replace("#9B241A", "#FFC1BD").replace("--color-on-main: #FFFFFF", "--color-on-main: #17171C"))
UNCOMPRESSED_PDF = """
from reportlab import rl_config
rl_config.pageCompression = 0
"""
SHOW_SCREEN_RADIUS = """
from reportlab.pdfgen.canvas import Canvas

round_rect = Canvas.roundRect

def show_radius(self, x, y, width, height, radius, **kwargs):
    print(f'PDF card radius: {radius}')
    return round_rect(self, x, y, width, height, radius, **kwargs)

Canvas.roundRect = show_radius
"""


def pdf_inks(data, operator=b"rg"):
    matches = re.finditer(rb"(?m)^([.0-9]+) ([.0-9]+) ([.0-9]+) " + operator + rb"\b", data)
    return ["#" + "".join(f"{round(float(part) * 255):02X}" for part in match.groups())
            for match in matches]


class PaperChoiceTests(RecordedMeetingFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.design_path = self.project / "DESIGN.md"
        self.prepare_args = ("--date", self.meeting_date, "--content", str(self.draft))

    def test_dark_design_without_a_choice_refuses_without_writing(self):
        self.design_path.write_text(DARK, encoding="utf-8")
        self.start()

        message = self.refuse("prepare", *self.prepare_args)

        self.assertIn("choose the pdf paper with --pdf-paper design or --pdf-paper white", message)

    def test_bad_given_paper_is_refused_without_writing(self):
        self.start()

        message = self.refuse("prepare", *self.prepare_args, "--pdf-paper", "cream")

        self.assertIn("--pdf-paper", message)
        self.assertIn("design", message)
        self.assertIn("white", message)

    def test_bad_saved_paper_is_refused_without_writing(self):
        self.start()
        project = self.read_json(self.project_file)
        for bad in ("cream", None, [], False):
            with self.subTest(bad=bad):
                self.write_json(self.project_file, dict(project, pdf_paper=bad))

                message = self.refuse("prepare", *self.prepare_args)

                self.assertIn("pdf_paper", message)
                self.assertIn("design", message)
                self.assertIn("white", message)

    def test_light_preparation_leaves_the_setup_choice_unset(self):
        self.design_path.write_text(READY, encoding="utf-8")
        self.start()
        project = self.project_file.read_bytes()

        self.command("prepare", *self.prepare_args)

        self.assertEqual(self.project_file.read_bytes(), project)
        self.assertEqual(self.read_json(self.content)["design"]["pdf"]["paper"], "design")

    def test_changing_the_unconfirmed_draft_preserves_every_html_byte(self):
        self.design_path.write_text(DARK, encoding="utf-8")
        self.start()
        self.command("prepare", *self.prepare_args, "--pdf-paper", "design")
        page = self.page.read_bytes()

        output = self.command("prepare", *self.prepare_args, "--pdf-paper", "white")

        self.assertEqual(self.page.read_bytes(), page)
        self.assertEqual(self.read_json(self.project_file)["pdf_paper"], "white")
        saved = self.read_json(self.content)["design"]
        self.assertEqual(saved["colors"]["background"], "#14141A")
        self.assertEqual(saved["pdf"]["colors"]["background"], "#FFFFFF")
        adjusted_main = saved["pdf"]["colors"]["main"]
        self.assertNotEqual(adjusted_main, "#FEEAC3")
        self.assertEqual(output.count(f"#FEEAC3 to {adjusted_main}"), 1)

        repeated = self.command("prepare", *self.prepare_args)

        self.assertNotIn(f"#FEEAC3 to {adjusted_main}", repeated)
        self.assertEqual(self.read_json(self.content)["design"], saved)
        self.assertEqual(self.page.read_bytes(), page)

    def test_confirmed_and_recorded_weeks_refuse_a_different_paper(self):
        self.design_path.write_text(DARK, encoding="utf-8")
        self.start()
        self.command("prepare", *self.prepare_args, "--pdf-paper", "design")
        self.command("confirm")

        self.assertIn("confirm", self.refuse("prepare", *self.prepare_args, "--pdf-paper", "white"))

        self.command("prepare", *self.prepare_args, "--pdf-paper", "design")
        self.assertFalse(self.read_json(self.week)["owner_confirmed_on"])
        self.command("confirm")
        self.record_manual()
        self.assertIn("recorded", self.refuse("prepare", *self.prepare_args, "--pdf-paper", "white"))

    def confirm_dark_draft_on_white(self):
        self.design_path.write_text(DARK, encoding="utf-8")
        self.start()
        self.command("prepare", *self.prepare_args, "--pdf-paper", "white")
        self.command("confirm")
        return self.project_file.read_bytes()

    def check_recovered_white_meeting(self, project_before):
        self.assertEqual(self.project_file.read_bytes(), project_before)
        design = self.read_json(self.content)["design"]
        self.assertEqual(design["colors"]["background"], "#14141A")
        self.assertEqual(design["pdf"]["paper"], "white")
        self.assertEqual(design["pdf"]["colors"]["background"], "#FFFFFF")
        self.assertFalse(self.read_json(self.week)["owner_confirmed_on"])

        self.command("confirm")
        self.record_manual()
        self.command("client-copy", setup=UNCOMPRESSED_PDF if REPORTLAB else STUB_PDF)
        self.command("lock")
        saved = self.read_json(self.week)
        self.assertTrue(saved["held"])
        self.assertTrue(saved["locked_on"])
        self.assertEqual(self.project_file.read_bytes(), project_before)

        with self.subTest(check="rendered PDF paper"):
            if not REPORTLAB:
                self.skipTest("ReportLab is required to check the rendered PDF paper")
            self.assertEqual(pdf_inks(self.pdf.read_bytes())[0], "#FFFFFF")

    def test_prepare_recovers_confirmed_white_draft_after_losing_saved_content(self):
        project_before = self.confirm_dark_draft_on_white()
        self.content.rename(self.scratch / self.content.name)

        self.command("prepare", *self.prepare_args)

        self.check_recovered_white_meeting(project_before)

    def test_prepare_recovers_confirmed_white_draft_after_losing_pages(self):
        project_before = self.confirm_dark_draft_on_white()
        pages = self.page.parent
        moved = pages.rename(self.scratch / "lost-pages")
        pages.mkdir()
        shutil.copyfile(moved / self.draft.name, self.draft)

        self.command("prepare", *self.prepare_args, "--pdf-paper", "white")

        self.check_recovered_white_meeting(project_before)

    def test_prepare_recovers_confirmed_white_draft_after_a_damaged_design(self):
        project_before = self.confirm_dark_draft_on_white()
        content = self.read_json(self.content)
        content["design"] = {"colors": {}}
        self.write_json(self.content, content)

        self.command("prepare", *self.prepare_args)

        self.check_recovered_white_meeting(project_before)

    def test_interrupted_prepare_rolls_back_project_choice_and_meeting(self):
        self.design_path.write_text(DARK, encoding="utf-8")
        self.start()
        self.command("prepare", *self.prepare_args, "--pdf-paper", "design")
        original = snapshot(self.project)

        self.command("prepare", *self.prepare_args, "--pdf-paper", "white", expected=91, setup="""
sys.path.insert(0, os.path.dirname(sys.argv[1]))
from weekflow_tool import lock_transaction

publish = lock_transaction.publish_entry

def stop_after_project(files, relative, data):
    publish(files, relative, data)
    if relative.name == 'project.json':
        os._exit(91)

lock_transaction.publish_entry = stop_after_project
""")
        self.assertEqual(self.read_json(self.project_file)["pdf_paper"], "white")
        self.command("prepare", "--date", "not-a-date", "--content", str(self.draft), expected=2)

        self.assertEqual(snapshot(self.project), original)

    def test_unsafe_page_refuses_before_writing_the_choice_or_ignore_rules(self):
        self.design_path.write_text(DARK, encoding="utf-8")
        self.start()
        ignore = self.project_file.with_name(".gitignore")
        ignore.write_text("# Existing ignore notes\n", encoding="utf-8")
        other_page = self.scratch / "unchanged.html"
        other_page.write_text("Keep this page.", encoding="utf-8")
        try:
            self.page.symlink_to(other_page)
        except (OSError, NotImplementedError):
            self.skipTest("This system does not allow test symlinks.")

        message = self.refuse("prepare", *self.prepare_args, "--pdf-paper", "white")

        self.assertIn("inside the project folder", message)


@unittest.skipUnless(REPORTLAB, "ReportLab is required to draw the paper choice PDF")
class PaperPdfTests(RecordedMeetingFixture, unittest.TestCase):
    def prepare_design_pdf(self, design, paper, *, setup=UNCOMPRESSED_PDF):
        (self.project / "DESIGN.md").write_text(design, encoding="utf-8")
        self.start()
        self.add_change()
        self.command("screen", "--id", "menu", "--name", "Pickup menu", "--order", "1",
                     "--state", "not-built")
        self.write_json(self.draft, dict(self.read_json(self.draft), app_ran=True))
        self.command("prepare", "--date", self.meeting_date, "--content", str(self.draft),
                     "--pdf-paper", paper)
        self.command("confirm")
        self.record_saved({"C-001": "no"})
        return self.command("client-copy", setup=setup)

    def test_build_pdf_with_dark_design_paper(self):
        self.prepare_design_pdf(DARK, "design")

        self.assertEqual(pdf_inks(self.pdf.read_bytes())[0], "#14141A")
        saved = self.read_json(self.content)["design"]
        self.assertEqual(saved["pdf"]["colors"], saved["colors"])

    def test_build_pdf_with_light_design_paper(self):
        self.prepare_design_pdf(READY, "design")

        self.assertEqual(pdf_inks(self.pdf.read_bytes())[0], "#FAF6EE")

    def test_build_pdf_with_light_white_paper(self):
        self.prepare_design_pdf(READY, "white")

        fills = pdf_inks(self.pdf.read_bytes())
        self.assertEqual(fills[0], "#FFFFFF")
        self.assertIn("#734225", fills)

    def test_dark_white_pdf_draws_print_colours_project_fonts_and_radius(self):
        live_fonts = self.project / "docs/fonts"
        shutil.copytree(TOOL.parent.parent / "assets/fonts", live_fonts)
        output = self.prepare_design_pdf(DARK, "white", setup=UNCOMPRESSED_PDF + SHOW_SCREEN_RADIUS)

        pdf = self.pdf.read_bytes()
        colors = pdf_inks(pdf)
        design = self.read_json(self.content)["design"]
        saved = design["pdf"]
        self.assertEqual(colors[0], "#FFFFFF")
        for role in ("background", "card", "text", "quiet", "lines", "error"):
            self.assertEqual(saved["colors"][role], STUDIO_COLORS[role])
        for role in ("card", "text", "quiet", "main", "on-main"):
            self.assertIn(saved["colors"][role], colors)
        self.assertIn(STUDIO_COLORS["lines"], pdf_inks(pdf, b"RG"))
        self.assertIn(saved["main_text"], colors)
        self.assertIn(saved["badge_inks"]["error"], colors)
        self.assertGreaterEqual(contrast(saved["colors"]["main"], "#FFFFFF"), 3)
        self.assertGreaterEqual(contrast(saved["colors"]["on-main"], saved["colors"]["main"]), 4.5)
        self.assertGreaterEqual(contrast(saved["main_text"], "#FFFFFF"), 4.5)
        for role in BADGE_ROLES:
            self.assertGreaterEqual(badge_contrast("#FFFFFF", saved["badge_inks"][role]), 4.5)
        for role in ("display", "body"):
            font = design["fonts"][role]
            self.assertEqual(font["source"], "project")
            digest = b32encode(bytes.fromhex(font["digest"])).rstrip(b"=")
            self.assertIn(b"+WF" + digest, pdf)
        self.assertIn("PDF card radius: 5", output)

    def test_studio_design_and_white_have_the_previous_pdf_bytes(self):
        self.start()
        self.prepare(confirm=False)
        original = self.read_json(self.content)
        original["design"].pop("pdf")
        self.write_json(self.content, original)
        self.command("confirm")
        legacy = self.client_copy()
        for paper in ("design", "white"):
            with self.subTest(paper=paper):
                project = PaperPdfTests()
                project.setUp()
                self.addCleanup(project.doCleanups)
                project.start()
                project.command("prepare", "--date", project.meeting_date, "--content", str(project.draft),
                                "--pdf-paper", paper)
                use_legacy_pdf(project.content)
                project.command("confirm")
                self.assertEqual(project.client_copy(), legacy)

    def test_meeting_with_pre_paper_design_snapshot_closes_and_rebuilds(self):
        (self.project / "DESIGN.md").write_text(READY, encoding="utf-8")
        self.start()
        self.prepare(confirm=False)
        content = self.read_json(self.content)
        content["design"].pop("pdf")
        self.write_json(self.content, content)
        self.command("confirm")
        self.record_manual()
        self.command("client-copy", setup=UNCOMPRESSED_PDF)
        original = self.pdf.read_bytes()
        self.command("lock")
        path = self.project_file
        self.write_json(path, dict(self.read_json(path), pdf_paper="white"))
        self.pdf.unlink()

        self.command("client-copy", setup=UNCOMPRESSED_PDF)

        self.assertEqual(pdf_inks(original)[0], "#FAF6EE")
        self.assertEqual(self.pdf.read_bytes(), original)
        self.assertNotIn("pdf", self.read_json(self.content)["design"])

    def test_new_choice_keeps_a_locked_white_pdf_through_rebuild_and_name_removal(self):
        (self.project / "DESIGN.md").write_text(DARK, encoding="utf-8")
        live_fonts = self.project / "docs/fonts"
        shutil.copytree(TOOL.parent.parent / "assets/fonts", live_fonts)
        self.start()
        self.command("prepare", "--date", self.meeting_date, "--content", str(self.draft),
                     "--pdf-paper", "white")
        self.command("confirm")
        self.command("record", "--answer", "--attendee", "the owner", "--attendee", "White")
        self.command("client-copy", setup=UNCOMPRESSED_PDF)
        self.command("lock")
        closed = {path: path.read_bytes() for path in (self.week, self.content, self.page, self.pdf)}
        self.assertEqual(pdf_inks(closed[self.pdf])[0], "#FFFFFF")

        self.pdf.unlink()
        self.command("client-copy", setup=UNCOMPRESSED_PDF)
        self.assertEqual(self.pdf.read_bytes(), closed[self.pdf])
        self.command("check-promise", "--id", "P-001", "--status", "done")
        self.command("prepare", "--date", "2026-03-05", "--content", str(self.draft),
                     "--pdf-paper", "design")

        self.assertEqual(self.read_json(self.project_file)["pdf_paper"], "design")
        new_design = self.read_json(self.page.with_name("week-4-content.json"))["design"]
        self.assertEqual(new_design["pdf"]["paper"], "design")
        self.assertEqual(new_design["pdf"]["colors"]["background"], "#14141A")
        self.assertEqual({path: path.read_bytes() for path in closed}, closed)

        frozen_fonts = self.page.parent / "fonts"
        frozen_fonts.rename(self.scratch / "lost-frozen-fonts")
        live_fonts.rename(self.scratch / "lost-live-fonts")
        self.page.unlink()
        self.command("remove-name", "--name", "White", "--what", "Personal detail",
                     "--reason", "Asked for removal", "--by", "the owner", setup=UNCOMPRESSED_PDF)

        sealed = self.read_json(self.content)["design"]["pdf"]
        self.assertEqual(sealed["paper"], "white")
        self.assertEqual(pdf_inks(self.pdf.read_bytes())[0], "#FFFFFF")
        self.assertIn(b"% Weekflow Studio font fallback", self.pdf.read_bytes())
        self.assertEqual(self.read_json(self.week)["locked_on"], json.loads(closed[self.week])["locked_on"])
        self.assertNotIn("White", self.read_json(self.week)["attendees"])
        if PDFTOTEXT:
            self.assertNotIn("White", self.extract_pdf())


@unittest.skipUnless(REPORTLAB, "ReportLab is required to draw the docs paper choice PDF")
class DocsPaperPdfTests(unittest.TestCase):
    def assert_pdf_background(self, design, paper, color):
        project = docs.DocsMeetingTests()
        project.setUp()
        self.addCleanup(project.doCleanups)
        (project.project / "DESIGN.md").write_text(design, encoding="utf-8")
        project.start()
        project.write_draft()
        project.invoke("prepare", "--date", "2026-08-15", "--content", docs.DRAFT_PATH,
                       "--pdf-paper", paper)
        project.invoke("confirm")
        project.record("D-001=the manager", "D-002=later")
        project.invoke("client-copy", setup=UNCOMPRESSED_PDF)
        self.assertEqual(pdf_inks(project.page.with_suffix(".pdf").read_bytes())[0], color)
        project.invoke("lock")
        self.assertTrue(project.week()["locked_on"])

    def test_docs_pdf_with_dark_design_paper(self):
        self.assert_pdf_background(DARK, "design", "#14141A")

    def test_docs_pdf_with_dark_white_paper(self):
        self.assert_pdf_background(DARK, "white", "#FFFFFF")

    def test_docs_pdf_with_light_design_paper(self):
        self.assert_pdf_background(READY, "design", "#FAF6EE")

    def test_docs_pdf_with_light_white_paper(self):
        self.assert_pdf_background(READY, "white", "#FFFFFF")
