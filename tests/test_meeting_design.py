"""Try project design parsing, contrast and frozen assets on disposable paths."""

from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/weekflow/scripts"))

from weekflow_tool.meeting_design import design_stamp, is_frozen_font, load_design, prepare_design, studio_design
from weekflow_tool.meeting_design_colors import BADGE_ROLES, COLOR_NAMES, badge_contrast, contrast
from weekflow_tool.meeting_design_fonts import FONT_DIR, FONT_LIMIT, font_codepoints
from weekflow_tool.storage import ProjectFiles, Refusal


HEADING_FAMILY = "Instrument Sans"
TEXT_FAMILY = "Bricolage Grotesque"


class MeetingDesignTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.files = ProjectFiles(self.root)
        self.fonts = self.root / "docs/fonts"
        self.fonts.mkdir(parents=True)
        for source in FONT_DIR.glob("*.ttf"):
            shutil.copyfile(source, self.fonts / source.name)
        self.design = self.root / "DESIGN.md"

    def write_design(self, *, stamp="v2 · Approved 2026-11-23", changes=None):
        values = {f"--color-{role}": value for role, value in studio_design().colors.items()}
        values.update({"--radius": "27px", "--font-heading": f'"{HEADING_FAMILY}", Georgia, serif',
                       "--font-text": f'"{TEXT_FAMILY}", system-ui, sans-serif'})
        values.update(changes or {})
        header = "# DESIGN.md: Corner Bakery\n"
        if stamp is not None:
            header += f"> {stamp}\n"
        css = "\n".join(f"  {name}: {value};" for name, value in values.items() if value is not None)
        self.design.write_text(f"{header}\n## Ready values\n```css\n:root {{\n{css}\n}}\n```\n",
                               encoding="utf-8")

    def use_project_fonts(self, design):
        self.assertEqual(design.font_names, {"heading": HEADING_FAMILY, "text": TEXT_FAMILY})
        self.assertEqual(len(design.assets), 4)
        for role, source in (("display", "InstrumentSans-Regular.ttf"),
                             ("title", "InstrumentSans-Bold.ttf"),
                             ("body", "BricolageGrotesque-Regular.ttf"),
                             ("bold", "BricolageGrotesque-Bold.ttf")):
            data = (self.fonts / source).read_bytes()
            digest = sha256(data).hexdigest()
            self.assertEqual(design.snapshot["fonts"][role], {"digest": digest, "source": "project"})
            self.assertEqual(design.assets[Path(f"docs/weekly/pages/fonts/{digest}.ttf")], data)

    def test_approved_or_unstamped_uses_only_ready_values(self):
        for stamp in ("v2 · Approved 2026-11-23", None):
            with self.subTest(stamp=stamp):
                self.write_design(stamp=stamp, changes={"--color-main": "#7f252e", "--space-1": "99px"})
                original = self.design.read_text(encoding="utf-8")
                self.design.write_text(original.replace("## Ready values", "```css\n## Ready values\n"
                                                        "```\n\n## Ready values").replace(
                    ":root {", ":root {\n  /*\n  --color-main: #123456;\n  */"), encoding="utf-8")
                design, messages = prepare_design(self.files)
                self.assertEqual(messages, [])
                self.assertEqual(design.colors["main"], "#7F252E")
                self.assertEqual(design.radius, 27)
                self.use_project_fonts(design)
                self.assertFalse((self.root / "docs/weekly").exists())

    def test_missing_empty_draft_and_nonapproved_design(self):
        self.assertEqual(prepare_design(self.files), (studio_design(), []))
        for stamp in ("v2 · Draft", "v2 · Pending"):
            with self.subTest(stamp=stamp):
                self.write_design(stamp=stamp)
                design, messages = prepare_design(self.files)
                self.assertEqual(design, studio_design())
                self.assertEqual(len(messages), 1)
        self.design.write_text("# DESIGN.md: Corner Bakery\n\n## Notes\nThe corner is 27 px.\n", encoding="utf-8")
        design, messages = prepare_design(self.files)
        self.assertEqual(design, studio_design())
        self.assertEqual(len(messages), 1)
        self.assertIn("no usable Ready values", messages[0])

    def test_arabic_draft_stamp_uses_the_studio_design(self):
        self.write_design(stamp="الإصدار 1 · مسودة")
        design, notices = prepare_design(self.files)
        self.assertEqual(design, studio_design())
        self.assertEqual(len(notices), 1)
        self.assertIn("Draft", notices[0])

    def test_arabic_approved_stamp_is_recognized_and_uses_the_project_design(self):
        self.write_design(stamp="الإصدار 2 · معتمد 2026-10-08 من مدير العيادة")
        self.assertEqual(design_stamp(self.design.read_text(encoding="utf-8").splitlines()), "approved")
        design, notices = prepare_design(self.files)
        self.assertEqual(notices, [])
        self.assertEqual(design.radius, 27)
        self.use_project_fonts(design)

    def test_stamp_ignores_front_matter_and_comment_banners(self):
        self.write_design(stamp="v2 · Draft")
        source = self.design.read_text(encoding="utf-8")
        banner = "<!-- A project document -->\n---\ntitle: The project\n---\n<!-- Its design -->\n"
        self.design.write_text(banner + source.replace("\n> ", "\n<!-- Draft status follows -->\n> "),
                               encoding="utf-8")
        design, notices = prepare_design(self.files)
        self.assertEqual(design, studio_design())
        self.assertEqual(len(notices), 1)
        self.assertIn("Draft", notices[0])

    def test_each_invalid_colour_or_missing_value_falls_back_and_is_named(self):
        for role, label in COLOR_NAMES.items():
            for invalid in ("#ABC", "#0189gg", "red", None):
                with self.subTest(role=role, invalid=invalid):
                    self.write_design(changes={f"--color-{role}": invalid})
                    design, messages = prepare_design(self.files)
                    self.assertEqual(design.colors[role], studio_design().colors[role])
                    self.assertEqual(len(messages), 1)
                    self.assertIn(label, messages[0])

    def test_hostile_values_reach_neither_snapshot_nor_messages(self):
        hostile = {"--color-card": "</style><script>unsafe()</script>", "--color-lines": "url(outside)",
                   "--radius": "expression(1)", "--font-heading": '"Instrument "Sans"',
                   "--font-text": '"Bricolage Grotesque", url(outside)'}
        self.write_design(changes=hostile)
        design, notices = prepare_design(self.files)
        self.assertEqual(design, studio_design())
        self.assertEqual(len(notices), len(hostile))
        for value in hostile.values():
            self.assertNotIn(value, str(design.snapshot))
            self.assertNotIn(value, "\n".join(notices))

    def test_radius_including_bounds_and_nonintegers(self):
        for value, expected in (("0px", 0), ("032px", 32), ("33px", 20), ("-1px", 20),
                                ("12.5px", 20), ("20", 20), (None, 20)):
            with self.subTest(value=value):
                self.write_design(changes={"--radius": value})
                design, notices = prepare_design(self.files)
                self.assertEqual(design.radius, expected)
                self.assertEqual(bool(notices), expected == 20)

    def test_bad_bold_falls_back_together_with_regular(self):
        self.write_design()
        bold = self.fonts / "InstrumentSans-Bold.ttf"
        bold.unlink()

        def assert_fallback():
            design, notices = prepare_design(self.files)
            studio = studio_design()
            for role in ("display", "title"):
                self.assertEqual(design.font_data[role], studio.font_data[role])
            for role in ("body", "bold"):
                self.assertNotEqual(design.font_data[role], studio.font_data[role])
            self.assertEqual(len(notices), 1)
            self.assertIn("Heading font", notices[0])

        assert_fallback()
        bold.write_bytes(b"broken font")
        assert_fallback()
        with bold.open("wb") as handle:
            handle.truncate(FONT_LIMIT + 1)
        assert_fallback()

    def test_refuses_links_inside_or_outside_project_and_linked_directory(self):
        self.write_design()
        bold = self.fonts / "InstrumentSans-Bold.ttf"
        real = self.fonts / "actual.ttf"
        bold.rename(real)
        try:
            bold.symlink_to(real)
        except (NotImplementedError, OSError):
            self.skipTest("File links are unavailable.")
        for target in (real, FONT_DIR / "InstrumentSans-Bold.ttf"):
            with self.subTest(target=target):
                bold.unlink()
                bold.symlink_to(target)
                design, notices = prepare_design(self.files)
                self.assertEqual(design.fonts["title"]["source"], "studio")
                self.assertIn("Heading font", notices[0])
        real_fonts = self.fonts.with_name("fonts-real")
        self.fonts.rename(real_fonts)
        self.fonts.symlink_to(real_fonts, target_is_directory=True)
        design, notices = prepare_design(self.files)
        self.assertTrue(all(details["source"] == "studio" for details in design.fonts.values()))
        self.assertEqual(len(notices), 2)

    def test_frozen_fonts_reload_without_live_design_check_digest_and_reuse_existing(self):
        self.write_design()
        design, _ = prepare_design(self.files)
        self.files.write_batch(design.assets.items())
        self.assertEqual(prepare_design(self.files)[0].assets, {})
        shutil.rmtree(self.fonts)
        self.design.unlink()
        saved = load_design(self.files, design.snapshot)
        self.assertEqual(saved.snapshot, design.snapshot)
        self.assertEqual(saved.font_data, design.font_data)
        self.assertTrue(all(is_frozen_font(self.files, relative) for relative in design.assets))
        deleted = next(iter(design.assets))
        (self.root / deleted).write_bytes(b"bad bytes")
        self.assertFalse(is_frozen_font(self.files, deleted))
        with self.assertRaisesRegex(Refusal, "Restore the saved .* font"):
            load_design(self.files, design.snapshot)
        self.assertEqual(load_design(self.files, None), studio_design())

    def test_saved_design_rejects_forged_css_digest_and_pair(self):
        studio = studio_design().snapshot
        for change in ({"radius": True}, {"main_text": "url(outside)"}, {"answer_text": "#EAE7FA"},
                       {"font_families": {"heading": 'Lora"', "text": TEXT_FAMILY}}):
            with self.subTest(change=change), self.assertRaises(Refusal):
                load_design(self.files, {**studio, **change})
        swapped = deepcopy(studio)
        swapped["fonts"]["title"]["digest"] = "0" * 64
        with self.assertRaisesRegex(Refusal, "Restore the Studio font"):
            load_design(self.files, swapped)
        swapped["fonts"]["title"]["source"] = "project"
        with self.assertRaisesRegex(Refusal, "Restore the design"):
            load_design(self.files, swapped)

    def test_checked_font_glyphs_match_selected_pair(self):
        self.write_design()
        design, _ = prepare_design(self.files)
        self.assertIn(ord("½"), font_codepoints(design.font_data["bold"]))
        self.assertNotIn(ord("½"), font_codepoints(design.font_data["title"]))

    def test_light_dark_and_opposed_colours_meet_every_pair(self):
        for background, card in (("#FFFFFF", "#F5F5F5"), ("#0C1C35", "#172035"),
                                 ("#FFFFFF", "#1F1F1F"), ("#777777", "#777777")):
            with self.subTest(background=background, card=card):
                original = {"background": background, "card": card, "text": background,
                            "quiet": background, "main": background, "error": background}
                self.write_design(changes={f"--color-{role}": value for role, value in original.items()})
                design, notices = prepare_design(self.files)
                for surface in ("background", "card"):
                    for ink in ("text", "quiet", "error", "main"):
                        minimum = 3 if ink == "main" else 4.5
                        self.assertGreaterEqual(contrast(design.colors[surface], design.colors[ink]), minimum)
                    self.assertGreaterEqual(contrast(design.colors[surface], design.main_text), 4.5)
                self.assertGreaterEqual(contrast(design.answer_text, design.answer_tint), 4.5)
                self.assertGreaterEqual(contrast(design.colors["on-main"], design.colors["main"]), 4.5)
                for role in BADGE_ROLES:
                    self.assertGreaterEqual(badge_contrast(design.colors["background"], design.badge_ink(role)), 4.5)
                    if design.badge_ink(role) != design.colors[role]:
                        self.assertIn(f"{COLOR_NAMES[role]} badge text changed from {design.colors[role]} "
                                      f"to {design.badge_ink(role)}", "\n".join(notices))
                values = {**studio_design().colors, **original}
                for role, value in design.colors.items():
                    if value != values[role]:
                        self.assertIn(f"{COLOR_NAMES[role]} changed from {values[role]} to {value}", "\n".join(notices))
                if background == "#FFFFFF" and card == "#1F1F1F":
                    self.assertNotEqual(design.colors["card"], card)
                if background == "#777777":
                    self.assertNotEqual(design.colors["background"], background)
