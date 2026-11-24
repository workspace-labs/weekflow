"""Verify the Arabic font roles with disposable project designs."""

from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory
import unittest

from test_meeting_design import FONT_DIR, ProjectFiles, load_design, prepare_design, studio_design
from weekflow_tool.pdf_text import validate_pdf_text
from weekflow_tool.storage import Refusal


class ArabicDesignTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.files = ProjectFiles(self.root)

    def test_studio_arabic_checks_arabic_and_latin_runs(self):
        design = studio_design("ar")
        self.assertEqual(design.font_names["arabic"], "Noto Naskh Arabic")
        validate_pdf_text("تسليم 12 مارس إلى Dana عبر Bunnev", "headline", design=design)
        with self.assertRaisesRegex(Refusal, r"U\+1F9C1 in headline"):
            validate_pdf_text("التسليم 🧁", "headline", design=design)

    def test_arabic_ready_values_resolve_and_recover_a_project_pair(self):
        fonts = self.root / "docs/fonts"
        fonts.mkdir(parents=True)
        for weight in ("Regular", "Bold"):
            copyfile(FONT_DIR / f"NotoNaskhArabic-{weight}.ttf", fonts / f"LocalArabic-{weight}.ttf")
        source = self.root / "DESIGN.md"
        source.write_text(
            '# دليل التصميم (DESIGN.md): مخبز\n> الإصدار 2 · معتمد 2026-11-23 من المالك\n'
            '## القيم الجاهزة\n```css\n:root {\n  --radius: 25px;\n  --font-arabic: "Local Arabic", serif;\n}\n```\n',
            encoding="utf-8",
        )
        design, _ = prepare_design(self.files, "ar")
        self.assertEqual(design.radius, 25)
        self.assertEqual(design.font_names["arabic"], "Local Arabic")
        self.assertEqual(design.fonts["arabic-bold"]["source"], "project")
        self.assertEqual(len(design.assets), 2)
        from_inputs = load_design(self.files, design.snapshot, language="ar", recover_fonts=True)
        self.assertEqual(from_inputs.assets, design.assets)
        for path in fonts.iterdir():
            path.unlink()
        fallback = load_design(self.files, design.snapshot, language="ar", recover_fonts=True)
        self.assertEqual(set(fallback.missing_roles), {"arabic-regular", "arabic-bold"})
        self.assertEqual(fallback.font_data["arabic-bold"], studio_design("ar").font_data["arabic-bold"])
        self.assertEqual(fallback.snapshot, design.snapshot)

        missing, notices = prepare_design(self.files, "ar")
        self.assertEqual(missing.font_names["arabic"], "Noto Naskh Arabic")
        self.assertTrue(any("Arabic font" in notice for notice in notices))
        source.write_text(source.read_text(encoding="utf-8").replace("معتمد", "مسودة"), encoding="utf-8")
        self.assertEqual(prepare_design(self.files, "ar")[0], studio_design("ar"))
