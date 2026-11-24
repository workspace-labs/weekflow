"""Run Arabic meetings and the redaction and recovery commands on copies."""

import json
import unittest

from test_arabic_documents import FORM, PRD, QUESTION, QUOTE
from test_screen_meetings import png
import test_weekflow as fixture
from weekflow_tool.meeting_design_fonts import FONT_DIR


class ArabicLifecycleTests(unittest.TestCase):
    command = fixture.WeekflowTests.command
    succeed = fixture.WeekflowTests.succeed
    refuse = fixture.WeekflowTests.refuse

    def setUp(self):
        fixture.WeekflowTests.setUp(self)

    def start_docs(self):
        self.form = self.project / "docs/meeting-form.md"
        self.form.write_text(FORM, encoding="utf-8")
        self.original_prd = PRD + "> الإصدار 1 · مسودة\n\n" + QUOTE.replace("{D-001}", "لم يُحسم")
        self.prd.write_text(self.original_prd, encoding="utf-8")
        self.succeed("start", "--language", "ar", "--meeting-day", "الأحد")

    def write_draft(self, **content):
        self.content_path.parent.mkdir(parents=True, exist_ok=True)
        self.content_path.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")

    def prepare_week(self, when, *options):
        self.succeed("prepare", "--date", when, "--content", str(self.content_path), *options)

    def copy_pdf(self, number, **options):
        setup = options.get("setup", "" if fixture.PDF_TEXT else fixture.TEST_PDF_RENDERER)
        result = self.command("client-copy", setup=setup)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return (self.pages / f"week-{number}.pdf").read_bytes()

    def read_week_number(self, number):
        return json.loads((self.weeks / f"week-{number}.json").read_text(encoding="utf-8"))

    def start_build(self):
        self.start_docs()
        self.approve_scope()
        self.succeed("enter-build")

    def approve_scope(self):
        self.prd.write_text(self.original_prd.replace("الإصدار 1 · مسودة",
                                                     "الإصدار 2 · معتمد 2026-11-02 من العميل")
                            + "\n\n- **المواعيد:** التسليم في 2027-03-12.\n", encoding="utf-8")

    def build_draft(self, **values):
        content = {"headline": "قائمة الخبز جاهزة.", "finished": [{"text": "تجهيز القائمة",
                                                                  "source": "app/menu.py"}]}
        self.write_draft(**dict(content, **values))

    def record_build(self, *answers):
        self.succeed("confirm")
        flags = tuple(part for answer in answers for part in ("--answer", answer)) or ("--answer",)
        self.succeed("record", *flags, "--attendee", "ريم", "--decided-by", "العميل")

    def test_docs_to_build_with_promises_signature_and_dated_notices(self):
        self.start_docs()
        self.write_draft(
            headline="استلام الطلبات", stage=3, next_week=[{"text": "عرض نموذج الاستلام"}],
            document=[{"title": "الطلبات", "sentences": [{"text": QUOTE, "source": "docs/prd.md"}]}],
            decisions=[{"id": "D-001", "question": QUESTION, "why": "نحدّد المسؤول.",
                        "options": ["المالك", "العميل"]}],
        )
        self.prepare_week("2026-11-01")
        self.succeed("confirm")
        self.succeed("record", "--answer", "D-001=المالك", "--attendee", "ريم", "--decided-by", "العميل")
        self.copy_pdf(5)
        self.succeed("lock")
        docs_week = self.read_week_number(5)
        self.assertEqual(docs_week["language"], "ar")
        self.assertEqual(docs_week["decisions_left"], 0)
        self.assertEqual(docs_week["answers"][0]["answer"], "المالك")
        self.approve_scope()
        self.succeed("enter-build")
        project_files = {name: value for name, value in fixture.snapshot(self.project).items()
                         if not name.startswith("docs/weekly/")}
        self.succeed("check-promise", "--id", "P-001", "--status", "not-finished",
                     "--note", "تأخّر عرض النموذج.")
        self.succeed("change", "--what", "إضافة وقت استلام", "--reason", "طلب العميل",
                     "--asked-by", "العميل", "--days", "2")
        self.build_draft()
        self.prepare_week("2026-11-08")
        self.record_build("C-001=yes")
        self.copy_pdf(6)
        self.succeed("sign", "--by", "العميل", "--on", "2026-11-08")
        self.succeed("lock")
        self.assertEqual(self.read_week_number(6)["end_after"], "2027-03-14")
        self.succeed("correct", "--week", "6", "--what", "تصحيح وصف النموذج",
                     "--reason", "الوصف ناقص", "--by", "المالك")
        self.succeed("no-meeting", "--date", "2026-11-15")
        self.assertEqual(self.read_week_number(7)["language"], "ar")
        self.build_draft()
        self.prepare_week("2026-11-22")
        page = (self.pages / "week-8.html").read_text(encoding="utf-8")
        self.assertIn("لم يُعقد اجتماع في 15 نوفمبر 2026.", page)
        self.assertIn("تصحيح وصف النموذج", page)
        after = {name: value for name, value in fixture.snapshot(self.project).items()
                 if not name.startswith("docs/weekly/")}
        self.assertEqual(after, project_files)

    def test_name_and_picture_removal_rebuilds_arabic_copy(self):
        self.start_build()
        self.succeed("screen", "--id", "menu", "--name", "القائمة", "--state", "finished")
        image = self.scratch / "picture.png"
        image.write_bytes(png((14, 25, 36)))
        self.succeed("screen-picture", "--id", "menu", "--file", str(image),
                     "--kind", "screenshot", "--taken-on", "2026-11-08")
        self.succeed("screen-check", "--id", "menu")
        screens = json.loads((self.weekly / "screens.json").read_text(encoding="utf-8"))
        picture = screens[0]["picture"]
        self.build_draft(headline="راجعت ريم القائمة.", app_ran=True)
        self.prepare_week("2026-11-08")
        self.record_build()
        original = self.copy_pdf(5)
        self.succeed("lock")

        def remove(operation, *args):
            setup = "" if fixture.PDF_TEXT else fixture.TEST_PDF_RENDERER
            result = self.command(operation, *args, "--what", "إزالة بيانات شخصية",
                                  "--reason", "الخصوصية", "--by", "المالك", setup=setup)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        remove("remove-name", "--name", "ريم")
        week = self.read_week_number(5)
        self.assertNotIn("ريم", str(week))
        self.assertIn("بسبب الخصوصية", week["attendees"][0])
        self.assertNotIn("ريم", (self.pages / "week-5.html").read_text(encoding="utf-8"))
        self.assertNotEqual(original, self.copy_pdf(5))
        remove("remove-picture", "--id", "menu", "--file", picture)
        self.assertFalse((self.weekly / picture).exists())
        page = (self.pages / "week-5.html").read_text(encoding="utf-8")
        self.assertIn("أُزيل في", page)
        self.assertIn("بسبب الخصوصية", page)
        self.assertNotIn("data:image/", page)
        self.copy_pdf(5)

    def test_missing_arabic_fonts_recover_from_page_then_use_studio(self):
        self.start_build()
        fonts = self.project / "docs/fonts"
        fonts.mkdir(exist_ok=True)
        for weight in ("Regular", "Bold"):
            source = FONT_DIR / f"NotoNaskhArabic-{weight}.ttf"
            (fonts / f"LocalArabic-{weight}.ttf").write_bytes(source.read_bytes())
        design = self.project / "DESIGN.md"
        design.write_text('# دليل التصميم\n> الإصدار 2 · معتمد 2026-11-23 من المالك\n\n'
                          '## القيم الجاهزة\n```css\n:root {\n--font-arabic: "Local Arabic", serif;\n}\n```\n',
                          encoding="utf-8")
        self.build_draft()
        self.prepare_week("2026-11-08")
        self.succeed("confirm")
        project_file = self.weekly / "project.json"
        project = json.loads(project_file.read_text(encoding="utf-8"))
        project_file.write_text(json.dumps(dict(project, language="en")), encoding="utf-8")
        frozen = {path: path.read_bytes() for path in (self.pages / "fonts").glob("*.ttf")}
        self.assertEqual(len(frozen), 2)
        for path in (*frozen, *fonts.glob("LocalArabic-*.ttf")):
            path.unlink()
        self.succeed("record", "--answer", "--attendee", "ريم")
        self.assertEqual({path: path.read_bytes() for path in frozen}, frozen)
        self.copy_pdf(5)
        self.succeed("lock")
        for path in (*frozen, self.pages / "week-5.html"):
            path.unlink()
        setup = "" if fixture.PDF_TEXT else fixture.TEST_PDF_RENDERER
        result = self.command("remove-name", "--name", "ريم", "--what", "إزالة اسم",
                              "--reason", "الخصوصية", "--by", "المالك", setup=setup)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Studio", result.stdout)
        self.assertIn(b"% Weekflow Studio font fallback", self.copy_pdf(5))
        self.assertNotIn("ريم", str(self.read_week_number(5)))

    def test_missing_arabic_draft_content_reports_the_location(self):
        self.start_build()
        self.build_draft(headline="The menu is ready.")
        message = self.refuse("prepare", "--date", "2026-11-08", "--content", str(self.content_path))
        self.assertIn("headline", message)
        self.assertIn("Arabic", message)
