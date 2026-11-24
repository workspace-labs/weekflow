"""Exercise the design snapshot through the public meeting commands."""

from hashlib import sha256
import re
import shutil
import unittest

from test_recorded_meeting import BLOCK_REPORTLAB, PDFTOTEXT, REPORTLAB, STUB_PDF, RecordedMeetingFixture
from test_weekflow import ORIGINAL_PAGE_PREPARE, TOOL


READY = """# Design
> v1 · Approved 2026-02-20

## Ready values
```css
:root {
  --color-background: #FAF6EE;
  --color-card: #F3E7D3;
  --color-text: #21150C;
  --color-quiet: #624632;
  --color-main: #734225;
  --color-on-main: #FFFFFF;
  --color-lines: #CBBBA8;
  --color-error: #9B241A;
  --font-heading: "Instrument Sans", serif;
  --font-text: "Bricolage Grotesque", system-ui, sans-serif;
  --radius: 8px;
}
```
"""


class FrozenDesignTests(RecordedMeetingFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.design = self.project / "DESIGN.md"
        self.live_fonts = self.project / "docs/fonts"
        self.frozen_fonts = self.page.parent / "fonts"

    def write_design(self):
        self.design.write_text(READY, encoding="utf-8")
        self.live_fonts.mkdir()
        for font in (TOOL.parent.parent / "assets/fonts").glob("*.ttf"):
            shutil.copyfile(font, self.live_fonts / font.name)

    def remove_name(self):
        return self.command("remove-name", "--name", "the manager", "--what", "Personal detail",
                            "--reason", "Asked for removal", "--by", "the owner",
                            setup="" if REPORTLAB else STUB_PDF)

    def test_live_design_can_change_or_disappear_while_a_frozen_meeting_closes(self):
        self.write_design()
        self.start()
        self.add_change()
        self.prepare(confirm=False)
        markup = self.page.read_bytes()
        frozen = self.read_json(self.content)["design"]
        self.assertEqual(frozen["radius"], 8)
        self.assertEqual(frozen["colors"]["card"], "#F3E7D3")
        self.assertEqual(len(list(self.frozen_fonts.glob("*.ttf"))), 4)
        for path in self.frozen_fonts.glob("*.ttf"):
            self.assertEqual(path.stem, sha256(path.read_bytes()).hexdigest())

        self.design.write_text(READY.replace("8px", "32px"), encoding="utf-8")
        self.command("confirm")
        self.design.unlink()
        self.live_fonts.rename(self.scratch / "old-fonts")
        self.record_saved({"C-001": "no"})
        original_pdf = self.client_copy()
        self.command("lock")
        self.pdf.unlink()
        self.assertEqual(self.client_copy(), original_pdf)
        self.assertEqual(self.page.read_bytes(), markup)

        self.remove_name()
        self.assertEqual(self.read_json(self.content)["design"], frozen)
        self.assertNotIn(b"the manager", self.page.read_bytes())
        self.assertEqual(self.client_copy(), self.pdf.read_bytes())

    def test_each_warning_is_printed_once_per_draft(self):
        self.design.write_text(READY.replace("Approved", "Draft"), encoding="utf-8")
        self.start()
        args = ("--date", self.meeting_date, "--content", str(self.draft))
        first = self.command("prepare", *args)
        self.assertIn("design.md", first.casefold())
        self.assertIn("draft", first.casefold())
        self.assertNotIn("design.md", self.command("prepare", *args).casefold())
        self.content.unlink()
        self.assertIn("design.md", self.command("prepare", *args).casefold())

    def test_a_lost_pages_directory_uses_the_live_design_on_next_prepare(self):
        self.write_design()
        self.start()
        self.prepare()
        self.record_manual()
        self.client_copy()
        self.command("lock")
        self.command("check-promise", "--id", "P-001", "--status", "done")
        self.page.parent.rename(self.scratch / "lost-pages")
        self.draft.parent.mkdir()
        self.draft.write_bytes((self.scratch / "lost-pages" / self.draft.name).read_bytes())
        self.design.write_text(READY.replace("8px", "32px"), encoding="utf-8")
        self.command("prepare", "--date", "2026-03-05", "--content", str(self.draft))
        later = self.read_json(self.page.with_name("week-4-content.json"))
        self.assertEqual(later["design"]["radius"], 32)

    def test_a_project_face_can_refuse_a_character_studio_could_draw(self):
        self.write_design()
        self.start()
        draft = self.read_json(self.draft)
        self.write_json(self.draft, dict(draft, headline="Ready ½"))
        message = self.refuse("prepare", "--date", self.meeting_date, "--content", str(self.draft))
        self.assertIn("u+00bd in headline", message)

    def test_removal_reason_is_checked_in_the_saved_headline_face(self):
        self.write_design()
        self.start()
        self.write_json(self.draft, dict(self.read_json(self.draft), headline="The manager checks pickup."))
        self.prepare()
        self.record_manual()
        self.client_copy()
        self.command("lock")
        self.design.unlink()
        output = self.refuse("remove-name", "--name", "the manager", "--what", "Personal detail",
                             "--reason", "Keep ½ of the note", "--by", "the owner",
                             setup="" if REPORTLAB else STUB_PDF)
        self.assertIn("u+00bd in removal reason", output)

    def test_pre_step_content_and_old_build_page_can_still_close(self):
        self.start()
        self.add_change()
        self.command("prepare", "--date", self.meeting_date, "--content", str(self.draft),
                     setup=ORIGINAL_PAGE_PREPARE)
        old = self.read_json(self.content)
        del old["design"]
        self.write_json(self.content, old)
        self.command("confirm", setup="""
sys.path.insert(0, os.path.dirname(sys.argv[1]))
from pathlib import Path
from weekflow_tool import meetings

render = meetings.render_html
def with_old_page(files, *args, **kwargs):
    view = original(files, *args, allow_missing_page=True, **kwargs)
    page = files.path(meetings.page_file(view.week['number']))
    page.write_text(render(view, legacy_build_fonts=True), encoding='utf-8')
    return original(files, *args, **kwargs)

original = meetings.fresh_view
meetings.fresh_view = with_old_page
""")
        self.record_saved({"C-001": "no"})
        self.client_copy()
        self.command("lock")
        self.assertNotIn("design", self.read_json(self.content))

    def test_altered_frozen_font_refuses_confirmation_without_writes(self):
        self.write_design()
        self.start()
        self.prepare(confirm=False)
        selected = next(self.frozen_fonts.glob("*.ttf"))
        selected.write_bytes(selected.read_bytes() + b"changed")
        self.assertIn("font", self.refuse("confirm"))

    def recorded_with_project_fonts(self):
        self.write_design()
        self.start()
        self.prepare()
        self.record_manual()
        return {path.name: path.read_bytes() for path in self.frozen_fonts.glob("*.ttf")}

    def lose_font_sources(self, *, live=True, page=True):
        self.frozen_fonts.rename(self.scratch / "lost-frozen-fonts")
        if live:
            self.live_fonts.rename(self.scratch / "lost-live-fonts")
        if page:
            # Leave the confirmed facts in place, but remove the embedded font bytes.
            self.page.write_bytes(re.sub(rb'(data:font/ttf;base64,)[A-Za-z0-9+/=]+', rb'\1',
                                         self.page.read_bytes()))

    def assert_restored_fonts(self, expected):
        self.assertEqual({path.name: path.read_bytes() for path in self.frozen_fonts.glob("*.ttf")},
                         expected)

    def test_first_record_recovers_deleted_frozen_fonts_with_project_files(self):
        self.write_design()
        self.start()
        self.add_change()
        self.prepare()
        self.lose_font_sources(live=False, page=False)

        self.record_saved({"C-001": "no"})

        original = self.scratch / "lost-frozen-fonts"
        self.assert_restored_fonts({path.name: path.read_bytes() for path in original.iterdir()})
        self.assertEqual(self.read_json(self.week)["answers"][0]["answer"], "no")
        self.client_copy()
        self.command("lock")

    def test_changed_answer_recovers_deleted_frozen_fonts_and_retires_old_copy(self):
        self.write_design()
        self.start()
        self.add_change()
        self.prepare()
        self.record_saved({"C-001": "yes"})
        self.client_copy()
        self.command("sign", "--by", "the client", "--on", self.meeting_date)
        self.lose_font_sources(page=False)

        self.record_saved({"C-001": "no"})

        original = self.scratch / "lost-frozen-fonts"
        self.assert_restored_fonts({path.name: path.read_bytes() for path in original.iterdir()})
        week = self.read_json(self.week)
        self.assertEqual(week["answers"], [{"id": "C-001", "answer": "no", "days": 0}])
        self.assertEqual(week["end_after"], week["end_before"])
        self.assertNotIn("signed_on", week)
        self.assertFalse(self.pdf.exists())
        self.client_copy()
        self.command("lock")

    def test_record_without_any_saved_font_copy_accepts_original_answers_and_closes(self):
        self.write_design()
        self.start()
        self.add_change()
        draft = dict(self.read_json(self.draft), needs=[{"text": "Pickup letter Ĩ"}])
        self.write_json(self.draft, draft)
        self.prepare()
        saved = self.content.read_bytes()
        answers = self.answer_file({"C-001": "no"})
        self.lose_font_sources(page=False)
        self.page.unlink()
        self.design.unlink()
        self.write_json(self.answers_path, dict(answers, fingerprint="0" * 64))
        self.assertIn("confirmed meeting page", self.refuse("record", "--answers", str(self.answers_path),
                                                            "--attendee", "the owner",
                                                            "--decided-by", "the client"))
        self.write_json(self.answers_path, answers)

        output = self.record_download()

        self.assertIn("Studio", output)
        self.assertIn("Unicode codes", output)
        self.assertEqual(self.read_json(self.week)["answers"][0]["answer"], "no")
        self.assertEqual(self.content.read_bytes(), saved)
        self.assertFalse(self.frozen_fonts.exists())
        self.command("lock", setup="" if REPORTLAB else STUB_PDF)
        self.assertTrue(self.read_json(self.week)["locked_on"])
        if REPORTLAB and PDFTOTEXT:
            self.assertIn("U+0128", self.extract_pdf())
        self.assertEqual(self.client_copy(), self.pdf.read_bytes())

    def test_lock_restores_the_exact_fonts_from_project_files(self):
        frozen = self.recorded_with_project_fonts()
        original_pdf = self.client_copy()
        original_page = self.page.read_bytes()
        self.lose_font_sources(live=False)
        project_face = self.live_fonts / "InstrumentSans-Regular.ttf"
        project_face.rename(self.live_fonts / "renamed.ttf")

        self.command("lock", setup=BLOCK_REPORTLAB)

        self.assertTrue(self.read_json(self.week)["locked_on"])
        self.assert_restored_fonts(frozen)
        self.assertEqual(self.pdf.read_bytes(), original_pdf)
        self.assertEqual(self.page.read_bytes(), original_page)

    def test_client_copy_restores_the_exact_fonts_from_the_confirmed_page(self):
        frozen = self.recorded_with_project_fonts()
        original_pdf = self.client_copy()
        original_page = self.page.read_bytes()
        self.pdf.unlink()
        self.lose_font_sources(page=False)

        self.assertEqual(self.client_copy(), original_pdf)
        self.assert_restored_fonts(frozen)
        self.assertEqual(self.page.read_bytes(), original_page)
        self.command("lock")

    def test_lost_fonts_keep_a_current_pdf_and_allow_lock_without_reportlab(self):
        self.recorded_with_project_fonts()
        original = self.client_copy()
        self.lose_font_sources()

        self.command("client-copy", setup=BLOCK_REPORTLAB)
        self.command("lock", setup=BLOCK_REPORTLAB)
        self.command("client-copy", setup=BLOCK_REPORTLAB)

        self.assertEqual(self.pdf.read_bytes(), original)
        self.assertTrue(self.read_json(self.week)["locked_on"])
        self.assertFalse(self.frozen_fonts.exists())

    def test_lost_fonts_and_page_use_studio_faces_to_make_a_pdf_and_lock(self):
        self.recorded_with_project_fonts()
        saved = self.content.read_bytes()
        self.lose_font_sources(page=False)
        self.page.unlink()

        output = self.command("lock", setup="" if REPORTLAB else STUB_PDF)

        self.assertIn("Studio", output)
        self.assertIn("font", output)
        self.assertTrue(self.read_json(self.week)["locked_on"])
        self.assertEqual(self.content.read_bytes(), saved)
        fallback_pdf = self.pdf.read_bytes()
        self.pdf.unlink()
        self.assertEqual(self.client_copy(), fallback_pdf)

    def test_missing_fonts_do_not_excuse_other_edits_to_a_confirmed_page(self):
        self.recorded_with_project_fonts()
        self.lose_font_sources()
        self.page.write_bytes(self.page.read_bytes() + b"<!-- changed -->")
        self.assertIn("does not match", self.refuse("lock"))

    def test_fallback_replaces_an_invalid_pdf_and_repairs_only_recovered_font_payloads(self):
        self.recorded_with_project_fonts()
        roles = self.read_json(self.content)["design"]["fonts"]
        self.lose_font_sources()
        self.live_fonts.mkdir()
        source = self.scratch / "lost-live-fonts" / "InstrumentSans-Regular.ttf"
        shutil.copyfile(source, self.live_fonts / source.name)
        self.pdf.write_bytes(b"damaged PDF")

        output = self.command("client-copy", setup="" if REPORTLAB else STUB_PDF)

        self.assertIn("Studio", output)
        self.assertNotIn("display", output)
        display = self.frozen_fonts / (roles["display"]["digest"] + ".ttf")
        self.assertEqual(display.read_bytes(), source.read_bytes())
        self.assertTrue(self.pdf.read_bytes().startswith(b"%PDF-"))
        self.command("lock", setup=BLOCK_REPORTLAB)

    @unittest.skipUnless(REPORTLAB and PDFTOTEXT, "reportlab or pdftotext is unavailable")
    def test_fallback_pdf_identifies_a_character_the_studio_face_cannot_draw(self):
        self.write_design()
        self.start()
        content = dict(self.read_json(self.draft), needs=[{"text": "Pickup letter Ĩ"}])
        self.write_json(self.draft, content)
        self.prepare()
        self.record_manual()
        self.lose_font_sources()

        message = self.command("client-copy")

        self.assertIn("Unicode", message)
        self.assertIn("U+0128", self.extract_pdf())
        self.assertEqual(self.read_json(self.content)["needs"], content["needs"])
        self.command("lock")

    def test_next_prepare_repairs_a_damaged_frozen_font(self):
        frozen = self.recorded_with_project_fonts()
        self.client_copy()
        self.command("lock")
        self.command("check-promise", "--id", "P-001", "--status", "done")
        selected = next(self.frozen_fonts.glob("*.ttf"))
        selected.write_bytes(b"damaged")

        self.command("prepare", "--date", "2026-03-05", "--content", str(self.draft))

        self.assert_restored_fonts(frozen)
        self.command("confirm")

    def test_interrupted_prepare_recovers_week_while_retaining_a_verified_font_repair(self):
        frozen = self.recorded_with_project_fonts()
        self.client_copy()
        self.command("lock")
        self.command("check-promise", "--id", "P-001", "--status", "done")
        selected = next(self.frozen_fonts.glob("*.ttf"))
        selected.write_bytes(b"damaged")
        # Fail after the font repair and after publishing some of the next meeting.
        output = self.command("prepare", "--date", "2026-03-05", "--content", str(self.draft),
                              expected=2, setup="""
sys.path.insert(0, os.path.dirname(sys.argv[1]))
from weekflow_tool import lock_transaction

publish = lock_transaction.publish_entry
def interrupt(files, relative, data):
    if relative.name == 'week-4.html' and data is not None:
        raise OSError('Test page write failure')
    publish(files, relative, data)

lock_transaction.publish_entry = interrupt
""")
        self.assertIn("project files and paths", output)
        self.assert_restored_fonts(frozen)
        self.assertFalse(self.week.with_name("week-4.json").exists())
        self.assertFalse((self.week.parent.parent / ".weekflow-undo.json").exists())
        self.command("prepare", "--date", "2026-03-05", "--content", str(self.draft))
        self.command("confirm")

    def test_prepare_refuses_a_link_at_a_frozen_font_path(self):
        self.write_design()
        self.start()
        self.prepare(confirm=False)
        selected = next(self.frozen_fonts.glob("*.ttf"))
        outside = self.scratch / "other-font.ttf"
        selected.rename(outside)
        selected.symlink_to(outside)

        self.assertIn("font", self.refuse("prepare", "--date", self.meeting_date,
                                         "--content", str(self.draft)))

    def test_prepare_rolls_back_font_copies_if_page_publication_fails(self):
        self.start()
        self.prepare(confirm=False)
        self.write_design()
        self.refuse("prepare", "--date", self.meeting_date, "--content", str(self.draft), setup="""
sys.path.insert(0, os.path.dirname(sys.argv[1]))
from weekflow_tool import lock_transaction

original = lock_transaction.publish_entry
tripped = False
def interrupt(files, relative, data):
    global tripped
    if not tripped and relative.suffix == '.html':
        tripped = True
        raise OSError('Test page write failure')
    original(files, relative, data)

lock_transaction.publish_entry = interrupt
""")
        self.assertEqual(list(self.frozen_fonts.glob("*.ttf")), [])
        self.command("confirm")
