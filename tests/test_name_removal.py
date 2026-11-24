"""Try dated name removal on disposable records and client copies."""

from base64 import b64decode
from datetime import date
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from test_docs_meetings import DECISIONS, FORM, SOURCE
from test_frozen_meeting_design import READY
from test_recorded_meeting import BLOCK_REPORTLAB, PDFTOTEXT, REPORTLAB, STUB_PDF
from test_weekflow import FIXTURE, TOOL, run_project_command, snapshot


NAME = "Sam"
NAME_WORD = re.compile(r"(?<!\w)Sam(?!\w)", re.IGNORECASE)
REASON = "Requested by the client"
TODAY = date.today()
PLAIN_TODAY = f"{TODAY.day} {TODAY:%B}"
REPLACEMENT = f"Removed on {PLAIN_TODAY} because {REASON}"
STUB_REMOVAL_PDF = STUB_PDF + """
from weekflow_tool import removal
removal.render_pdf = client_pdf.render_pdf
"""


class NameRemovalTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.scratch = Path(temporary.name)
        self.use_project("sample")

    def use_project(self, name):
        self.project = self.scratch / name
        shutil.copytree(FIXTURE, self.project)
        self.weekly = self.project / "docs/weekly"
        self.draft = self.weekly / "pages/draft.json"
        self.draft.parent.mkdir(parents=True)

    def command(self, command, *args, setup="", expected=0):
        launcher = [str(TOOL)]
        if setup:
            launcher = ["-c", f"""
import os
import runpy
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(sys.argv[1]))
{setup}
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name="__main__")
""", str(TOOL)]
        result = run_project_command(
            [sys.executable, "-B", *launcher], command, self.project, *args,
            cwd=self.scratch, capture_output=True, text=True, timeout=30,
        )
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, expected, output)
        return output

    def read(self, path):
        return json.loads((self.weekly / path).read_text(encoding="utf-8"))

    def prepare(self, meeting_date="2026-02-25", *, source="app/menu.py", needs=(), confirm=True,
                next_week=(), headline="Working pickup form"):
        value = {
            "headline": headline,
            "finished": [{"text": "Ready for Sambunwick", "source": source}],
            "needs": list(needs),
            "next_week": [{"text": item} for item in next_week],
        }
        self.draft.write_text(json.dumps(value), encoding="utf-8")
        self.command("prepare", "--date", meeting_date, "--content", str(self.draft))
        if confirm:
            self.command("confirm")

    def start(self, *, attendee="the owner"):
        self.command("start", "--language", "en", "--meeting-day", "Thursday",
                     "--planned-end", "2026-03-12", "--attendee", attendee)

    def remove(self, *, name=NAME, reason=REASON, what="Remove a personal name", by="the owner", **run):
        return self.command("remove-name", "--name", name, "--what", what, "--reason", reason,
                            "--by", by, **run)

    def assert_redacted(self):
        self.assertFalse([path for path in self.weekly.rglob("*") if path.is_file()
                          and re.search(rb"(?<!\w)Sam(?!\w)", path.read_bytes(), re.IGNORECASE)])
        self.assertFalse(list(self.weekly.rglob(".weekflow-*")))

    def test_an_unrecorded_draft_is_scrubbed_unconfirmed_and_retired(self):
        self.start(attendee="SAM")
        self.prepare(headline="sam helps Sambunwick", needs=({"text": "Send Sam’s form"},))
        self.command("client-copy", setup="" if REPORTLAB else STUB_PDF)
        output = self.remove()
        self.assertIsNone(NAME_WORD.search(output), output)
        self.assertIn("3", output)
        self.assertIn("replace", output.casefold())
        self.assertIn("git", output.casefold())
        week = self.read("weeks/week-3.json")
        content = self.read("pages/week-3-content.json")
        self.assertFalse(week["owner_confirmed_on"])
        self.assertEqual(self.read("project.json")["attendees"], [REPLACEMENT])
        self.assertEqual(content["headline"], f"{REPLACEMENT} helps Sambunwick")
        self.assertEqual(content["needs"], [{"text": f"Send {REPLACEMENT}’s form"}])
        self.assertTrue(content["corrections_frozen"])
        self.assertEqual(self.read("pages/draft.json")["headline"], content["headline"])
        self.assertFalse((self.weekly / "pages/week-3.html").exists())
        self.assertFalse((self.weekly / "pages/week-3.pdf").exists())
        self.assertFalse((self.weekly / "corrections.json").exists())
        self.assert_redacted()
        self.command("prepare", "--date", "2026-02-25", "--content", str(self.draft))
        self.assert_redacted()

    def test_unsafe_removal_details_and_source_paths_leave_every_file_alone(self):
        self.start()
        source = self.project / "app/sAm-menu.py"
        source.write_text("# fixture evidence\n", encoding="utf-8")
        self.prepare(source="app/sAm-menu.py")
        original = snapshot(self.scratch)
        for options in ({"what": "Sam asked to remove the name"}, {"reason": "At SAM's request"},
                        {"by": "sAM"}, {}):
            with self.subTest(options=options):
                output = self.remove(**options, expected=2)
                self.assertIsNone(NAME_WORD.search(output), output)
                self.assertEqual(snapshot(self.scratch), original)
        self.assertIn("finished", output.casefold())
        self.assertIn("3", output)

    def test_recorded_unlocked_week_must_be_locked_first(self):
        self.start()
        self.command("change", "--what", "Enable pickup", "--reason", "The shop asked",
                     "--asked-by", "the client", "--days", "0")
        self.prepare()
        self.command("record", "--answer", "C-001=yes", "--attendee", "the owner", "--decided-by", "sAm")
        original = snapshot(self.scratch)
        output = self.remove(expected=2)
        self.assertIn("lock", output.casefold())
        self.assertIsNone(NAME_WORD.search(output), output)
        self.assertEqual(snapshot(self.scratch), original)

    def test_a_legacy_staging_file_containing_the_name_blocks_a_partial_removal(self):
        self.start(attendee="Sam")
        leftover = self.weekly / ".weekflow-interrupted"
        leftover.write_text('{"attendees": ["\\u0053am"]}', encoding="utf-8")
        original = snapshot(self.scratch)
        output = self.remove(expected=2)
        self.assertIn("weekly", output.casefold())
        self.assertIsNone(NAME_WORD.search(output), output)
        self.assertEqual(snapshot(self.scratch), original)

    def test_a_name_in_an_unmatched_artifact_does_not_survive_a_reported_success(self):
        self.start()
        self.prepare()
        page = self.weekly / "pages/week-3.html"
        with page.open("ab") as old_page:
            old_page.write(b"<!-- Scrub S&#97;m here too. -->")
        original = snapshot(self.scratch)
        output = self.remove(expected=2)
        self.assertIn("weekly", output.casefold())
        self.assertIsNone(NAME_WORD.search(output), output)
        self.assertEqual(snapshot(self.scratch), original)

    def test_missing_pdf_library_refuses_before_writing_anything(self):
        self.start(attendee="Sam")
        self.prepare()
        self.command("record", "--answer", "--attendee", "the owner")
        self.command("client-copy", setup=STUB_PDF)
        self.command("lock")
        original = snapshot(self.scratch)
        output = self.remove(setup=BLOCK_REPORTLAB, expected=2)
        self.assertIn("reportlab", output.casefold())
        self.assertIsNone(NAME_WORD.search(output), output)
        self.assertEqual(snapshot(self.scratch), original)

    def lock_named_week(self, name, meeting_date):
        self.start(attendee=name)
        self.command("change", "--what", "Enable pickup", "--reason", "The shop asked",
                     "--asked-by", name, "--days", "2")
        self.prepare(meeting_date, headline=f"Pickup with {name}")
        self.command("record", "--answer", "C-001=yes", "--attendee", name, "--decided-by", name)
        self.command("client-copy", setup="" if REPORTLAB else STUB_PDF)
        self.command("sign", "--by", name, "--on", meeting_date)
        self.command("lock")

    def lock_week_with_project_fonts(self, *, prepare_next=False):
        (self.project / "DESIGN.md").write_text(READY, encoding="utf-8")
        fonts = self.project / "docs/fonts"
        fonts.mkdir()
        for path in (TOOL.parent.parent / "assets/fonts").glob("*.ttf"):
            shutil.copyfile(path, fonts / path.name)
        self.lock_named_week(NAME, "2026-02-25")
        if prepare_next:
            self.prepare("2026-03-04", headline=f"Review with {NAME}", confirm=False)
        fonts.rename(self.scratch / "old-project-fonts")
        (self.weekly / "pages/fonts").rename(self.scratch / "old-frozen-fonts")
        return self.weekly / "pages/week-3.html"

    def test_removal_rebuilds_from_fonts_in_the_confirmed_page(self):
        page = self.lock_week_with_project_fonts()
        pdf = page.with_suffix(".pdf")
        old_pdf = pdf.read_bytes()
        original_design = self.read("pages/week-3-content.json")["design"]

        output = self.remove(setup="" if REPORTLAB else STUB_REMOVAL_PDF)

        self.assertIn("Changed weeks 3.", output)
        self.assertNotIn("could not be rebuilt", output)
        self.assertEqual(self.read("weeks/week-3.json")["signed_by"], REPLACEMENT)
        self.assertEqual(self.read("pages/week-3-content.json")["design"], original_design)
        for font in (self.scratch / "old-frozen-fonts").glob("*.ttf"):
            self.assertEqual((page.parent / "fonts" / font.name).read_bytes(), font.read_bytes())
        self.assertIn(REPLACEMENT, page.read_text(encoding="utf-8"))
        self.assertNotEqual(pdf.read_bytes(), old_pdf)
        self.assert_redacted()
        if REPORTLAB and PDFTOTEXT:
            copy_text = subprocess.check_output([PDFTOTEXT, str(pdf), "-"], text=True, timeout=15)
            self.assertIsNone(NAME_WORD.search(copy_text), copy_text)

    def test_removal_scrubs_the_page_when_a_font_cannot_be_recovered(self):
        page = self.lock_week_with_project_fonts()
        damaged, count = re.subn(rb"(data:font/ttf;base64,)[A-Za-z0-9+/=]+", rb"\1AAAA",
                                 page.read_bytes(), count=1)
        self.assertEqual(count, 1)
        page.write_bytes(damaged)
        pdf = page.with_suffix(".pdf")
        old_pdf = pdf.read_bytes()

        output = self.remove(setup="" if REPORTLAB else STUB_REMOVAL_PDF)

        self.assertIn("Changed weeks 3.", output)
        self.assertIn("The PDF uses the Studio fonts", output)
        self.assertNotIn("copy (PDF) could not be rebuilt", output)
        rebuilt = pdf.read_bytes()
        self.assertNotEqual(rebuilt, old_pdf)
        self.assertIn(b"% Weekflow Studio font fallback", rebuilt)
        markup = page.read_text(encoding="utf-8")
        self.assertIn(f"Pickup with {REPLACEMENT}", markup)
        self.assertNotIn(f"Pickup with {NAME}", markup)
        self.assertNotIn('data:font/ttf;base64,AAAA"', markup)
        self.assertIn("Studio font fallback", markup)

        (self.scratch / "old-project-fonts").rename(self.project / "docs/fonts")
        self.assertIn("No weeks changed.", self.remove(setup=BLOCK_REPORTLAB))
        self.command("client-copy", setup=BLOCK_REPORTLAB)
        self.assertEqual(pdf.read_bytes(), rebuilt)
        self.assertNotIn("Studio font fallback", page.read_text(encoding="utf-8"))

    @unittest.skipUnless(REPORTLAB and PDFTOTEXT, "ReportLab and pdftotext are required for PDF text checks.")
    def test_removal_rebuilds_the_pdf_when_no_frozen_font_can_be_recovered(self):
        page = self.lock_week_with_project_fonts(prepare_next=True)
        page.unlink()
        page.with_name("week-4.html").unlink()
        pdf = page.with_suffix(".pdf")
        old_pdf = pdf.read_bytes()
        before = subprocess.check_output([PDFTOTEXT, str(pdf), "-"], text=True, timeout=15)
        self.assertIsNotNone(NAME_WORD.search(before), before)

        output = self.remove()

        self.assertIn("Changed weeks 3, 4.", output)
        self.assertIn("The PDF uses the Studio fonts", output)
        self.assertNotIn("copy (PDF) could not be rebuilt", output)
        self.assertEqual(self.read("weeks/week-3.json")["signed_by"], REPLACEMENT)
        self.assertEqual(self.read("pages/week-3-content.json")["headline"], f"Pickup with {REPLACEMENT}")
        self.assertEqual(self.read("pages/week-4-content.json")["headline"], f"Review with {REPLACEMENT}")
        self.assertEqual(self.read("pages/draft.json")["headline"], f"Review with {REPLACEMENT}")
        fallback_pdf = pdf.read_bytes()
        self.assertNotEqual(fallback_pdf, old_pdf)
        rendered = subprocess.check_output([PDFTOTEXT, str(pdf), "-"], text=True, timeout=15)
        self.assertIsNone(NAME_WORD.search(rendered), rendered)
        self.assertIn(REPLACEMENT, " ".join(rendered.split()))
        completed = snapshot(self.weekly)
        self.assertIn("No weeks changed.", self.remove(setup=BLOCK_REPORTLAB))
        self.assertEqual(snapshot(self.weekly), completed)

        pdf.write_bytes(fallback_pdf + b"changed")
        changed = snapshot(self.weekly)
        output = self.remove(setup=BLOCK_REPORTLAB, expected=2)
        self.assertIn("Make the current PDF", output)
        self.assertEqual(snapshot(self.weekly), changed)

    def test_removal_retry_repairs_a_stale_pdf_left_by_an_older_removal(self):
        page = self.lock_week_with_project_fonts()
        pdf = page.with_suffix(".pdf")
        original_pdf = pdf.read_bytes()
        page.unlink()
        first = self.remove(setup=BLOCK_REPORTLAB)
        self.assertIn("Changed weeks 3.", first)
        self.assertIn("may still hold the name. The reportlab package is required.", first)
        self.assertEqual(pdf.read_bytes(), original_pdf)
        week = self.read("weeks/week-3.json")
        self.assertEqual(week["signed_by"], REPLACEMENT)
        corrections = self.read("corrections.json")

        output = self.remove(setup="" if REPORTLAB else STUB_REMOVAL_PDF)

        self.assertIn("No weeks changed.", output)
        self.assertIn("Rebuilt the PDF for week 3 from its redacted record.", output)
        self.assertIn("The PDF uses the Studio fonts", output)
        self.assertNotEqual(pdf.read_bytes(), original_pdf)
        self.assertEqual(self.read("weeks/week-3.json"), week)
        self.assertEqual(self.read("corrections.json"), corrections)
        self.command("client-copy", setup=BLOCK_REPORTLAB)

    def test_common_names_are_removed_even_when_fixed_markup_or_dates_match(self):
        for name, meeting_date in (("Max", "2026-03-02"), ("May", "2026-05-02"),
                                   ("June", "2026-06-02"), ("April", "2026-04-02"),
                                   ("August", "2026-08-02"), ("Text", "2026-03-02")):
            with self.subTest(name=name):
                self.use_project(name)
                self.lock_named_week(name, meeting_date)
                week = self.read("weeks/week-3.json")
                change = self.read("changes.json")[0]
                output = self.remove(name=name, setup="" if REPORTLAB else STUB_REMOVAL_PDF)
                self.assertIn("Changed weeks 3.", output)
                self.assertEqual(self.read("weeks/week-3.json"),
                                 dict(week, attendees=[REPLACEMENT], signed_by=REPLACEMENT))
                self.assertEqual(self.read("changes.json")[0],
                                 dict(change, asked_by=REPLACEMENT, decided_by=REPLACEMENT))
                self.assertEqual(self.read("pages/draft.json")["headline"], f"Pickup with {REPLACEMENT}")
                self.assertEqual(self.read("pages/week-3-content.json")["headline"],
                                 f"Pickup with {REPLACEMENT}")
                html = (self.weekly / "pages/week-3.html").read_text(encoding="utf-8")
                self.assertIn("max-width", html)
                self.assertNotIn(f"Pickup with {name}<", html)
                self.assertIn(f'<time datetime="{meeting_date}">2 {date.fromisoformat(meeting_date):%B}</time>',
                              html)
                if REPORTLAB and PDFTOTEXT:
                    pdf = self.weekly / "pages/week-3.pdf"
                    result = subprocess.run([PDFTOTEXT, str(pdf), "-"], check=True, capture_output=True,
                                            text=True, timeout=15)
                    self.assertNotIn(f"Pickup with {name}", result.stdout)
                    self.assertIn(f"2 {date.fromisoformat(meeting_date):%B}", result.stdout)

    def test_removal_reaches_git_records_without_any_copies(self):
        self.lock_named_week(NAME, "2026-02-25")
        shutil.rmtree(self.weekly / "pages")
        output = self.remove(setup=BLOCK_REPORTLAB)
        self.assertIn("Changed weeks 3.", output)
        self.assertIn("could not be rebuilt", output)
        self.assertFalse((self.weekly / "pages").exists())
        self.assertEqual(self.read("weeks/week-3.json")["signed_by"], REPLACEMENT)
        self.assertEqual(self.read("changes.json")[0]["asked_by"], REPLACEMENT)
        self.assertEqual(self.read("corrections.json")[0]["date"], TODAY.isoformat())
        self.assert_redacted()

    def prepare_docs_decisions(self):
        (self.project / "docs/prd.md").write_text(
            "# PRD: Corner Bakery\n> v1 · Draft\n\n" + SOURCE, encoding="utf-8",
        )
        (self.project / "docs/meeting-form.md").write_text(FORM, encoding="utf-8")
        self.command("start", "--language", "en", "--meeting-day", "Saturday")
        self.draft.write_text(json.dumps({
            "headline": "Pickup orders", "stage": 3, "decisions": DECISIONS,
            "document": [{"title": "How orders run", "sentences": [
                {"text": sentence, "source": "docs/prd.md"} for sentence in (
                    "The shop will confirm {D-001} pickup.",
                    "Orders wait in a basket {D-002}.",
                    "The client packs the bread {D-003}.",
                )
            ]}],
            "next_week": [], "needs": [],
        }), encoding="utf-8")
        self.command("prepare", "--date", "2026-08-15", "--content", str(self.draft))
        self.command("confirm")

    def test_docs_decider_is_recorded_and_removable_when_pages_are_missing(self):
        self.prepare_docs_decisions()
        self.command("record", "--answer", "D-001=the manager", "--answer", "D-002=later",
                     "--attendee", "the owner", "--decided-by", NAME)
        self.command("client-copy", setup=STUB_PDF)
        self.command("lock")
        before = self.read("weeks/week-3.json")
        answered = {"id": "D-001", "answer": "the manager", "days": 0, "decided_by": NAME}
        deferred = {"id": "D-002", "answer": "later", "days": 0}
        self.assertEqual(before["answers"], [answered, deferred])

        shutil.rmtree(self.weekly / "pages")
        output = self.remove(setup=BLOCK_REPORTLAB)
        self.assertIn("Changed weeks 3.", output)
        self.assertIn("could not be rebuilt", output)
        self.assertFalse((self.weekly / "pages").exists())
        self.assertEqual(self.read("weeks/week-3.json"),
                         dict(before, answers=[dict(answered, decided_by=REPLACEMENT), deferred]))
        correction, = self.read("corrections.json")
        self.assertEqual((correction["week"], correction["kind"], correction["date"]),
                         (3, "removal", TODAY.isoformat()))
        self.assert_redacted()

    def test_docs_only_deferrals_need_no_decider_but_selected_options_do(self):
        self.prepare_docs_decisions()
        output = self.command("record", "--answer", "D-001=the manager", "--attendee", "the owner",
                              expected=2)
        self.assertIn("--decided-by", output)
        self.command("record", "--answer", "D-001=later", "--attendee", "the owner")
        self.command("client-copy", setup=STUB_PDF)
        self.command("lock")
        week = self.read("weeks/week-3.json")
        self.assertEqual(week["answers"], [{"id": "D-001", "answer": "later", "days": 0}])
        self.assertEqual(week["decisions_left"], 3)

    def test_legacy_docs_answers_without_decider_can_still_close(self):
        self.prepare_docs_decisions()
        self.command("record", "--answer", "D-001=the manager", "--attendee", "the owner",
                     "--decided-by", NAME)
        week = self.read("weeks/week-3.json")
        week["answers"][0].pop("decided_by", None)
        (self.weekly / "weeks/week-3.json").write_text(json.dumps(week), encoding="utf-8")
        self.command("client-copy", setup=STUB_PDF)
        self.command("lock")
        self.assertEqual(self.read("weeks/week-3.json")["answers"], week["answers"])

    @unittest.skipUnless(REPORTLAB and PDFTOTEXT, "ReportLab and pdftotext are required for PDF text checks.")
    def test_docs_pdf_shows_decider_and_redacts_it_without_changing_the_answer(self):
        self.prepare_docs_decisions()
        self.command("record", "--answer", "D-001=the manager", "--answer", "D-002=later",
                     "--attendee", "the owner", "--decided-by", NAME)
        self.command("client-copy")
        self.command("lock")
        pdf = self.weekly / "pages/week-3.pdf"

        def copy_text():
            output = subprocess.check_output([PDFTOTEXT, str(pdf), "-"], text=True, timeout=15)
            return " ".join(output.split())

        before = copy_text()
        self.assertIn(f"Decided by {NAME}", before)
        self.assertEqual(before.count("Decided by"), 1)
        self.assertNotIn(NAME, pdf.with_suffix(".html").read_text(encoding="utf-8"))
        self.remove()
        after = copy_text()
        self.assertIsNone(NAME_WORD.search(after), after)
        self.assertIn(f"Decided by {REPLACEMENT}", after)
        self.assertIn("the manager", after)
        self.assertIn("Decide next week", after)
        revised = pdf.read_bytes()
        self.command("client-copy")
        self.assertEqual(pdf.read_bytes(), revised)

    def test_removal_ignores_css_in_an_older_draft_after_a_new_change_is_logged(self):
        self.start()
        self.prepare(confirm=False)
        page = self.weekly / "pages/week-3.html"
        original = page.read_bytes()
        self.command("change", "--what", "Enable pickup", "--reason", "The shop asked",
                     "--asked-by", "Max", "--days", "2")

        self.remove(name="Max", setup=BLOCK_REPORTLAB)

        self.assertEqual(self.read("changes.json")[0]["asked_by"], REPLACEMENT)
        self.assertEqual(page.read_bytes(), original)
        self.assertIn(b"max-width", original)

    def test_removal_rebuilds_a_pdf_when_only_its_older_page_is_missing(self):
        self.lock_named_week(NAME, "2026-02-25")
        self.prepare("2026-03-04")
        self.command("record", "--answer", "--attendee", "the manager")
        self.command("client-copy", setup="" if REPORTLAB else STUB_PDF)
        self.command("lock")
        page = self.weekly / "pages/week-3.html"
        pdf = page.with_suffix(".pdf")
        original = pdf.read_bytes()
        page.unlink()

        output = self.remove(setup="" if REPORTLAB else STUB_REMOVAL_PDF)
        self.assertRegex(output, r"(?i)week\s+3.*(?:could not be rebuilt|missing)")
        self.assertFalse(page.exists())
        self.assertNotEqual(pdf.read_bytes(), original)
        self.assert_redacted()

    def test_removal_does_not_restore_a_missing_pdf(self):
        self.lock_named_week(NAME, "2026-02-25")
        pdf = self.weekly / "pages/week-3.pdf"
        pdf.unlink()
        output = self.remove(setup=BLOCK_REPORTLAB)
        self.assertRegex(output, r"(?i)week\s+3.*(?:could not be rebuilt|missing)")
        self.assertFalse(pdf.exists())
        self.assertIn(REPLACEMENT, (self.weekly / "pages/week-3.html").read_text(encoding="utf-8"))
        self.assert_redacted()

    def copies_without_content(self, extensions):
        (self.weekly / "pages/week-3-content.json").unlink()
        copies = {}
        for extension in ("html", "pdf"):
            path = self.weekly / f"pages/week-3.{extension}"
            if extension in extensions:
                copies[path] = path.read_bytes()
            else:
                path.unlink()
        return copies

    def assert_unchecked_copy_warning(self, output):
        self.assertRegex(output, r"(?i)week\s+3[^\n]*could not be checked")
        self.assertRegex(output, r"(?i)may still (?:hold|contain) the name")

    def test_unknown_name_keeps_locked_copies_without_content(self):
        for extensions in (("html",), ("pdf",), ("html", "pdf")):
            with self.subTest(surviving=extensions):
                self.use_project("unknown-" + "-".join(extensions))
                self.lock_named_week("Sara Khan", "2026-02-25")
                copies = self.copies_without_content(extensions)
                before = snapshot(self.weekly)

                output = self.remove(name="Sara Kahn", setup=BLOCK_REPORTLAB)

                for path, original in copies.items():
                    self.assertTrue(path.is_file(), f"Locked copy was removed: {path.name}")
                    self.assertEqual(path.read_bytes(), original)
                self.assertEqual(snapshot(self.weekly), before)
                self.assert_unchecked_copy_warning(output)

    def lock_two_named_weeks(self, name):
        self.lock_named_week(name, "2026-02-25")
        self.prepare("2026-03-04", headline=f"Confirm pickup with {name}")
        self.command("record", "--answer", "--attendee", name)
        self.command("client-copy", setup="" if REPORTLAB else STUB_PDF)
        self.command("lock")

    def test_real_name_keeps_unchecked_locked_copies_and_scrubs_other_files(self):
        name = "Sara Khan"
        for extensions in (("html",), ("pdf",), ("html", "pdf")):
            with self.subTest(surviving=extensions):
                self.use_project("real-" + "-".join(extensions))
                self.lock_two_named_weeks(name)
                copies = self.copies_without_content(extensions)
                next_page = self.weekly / "pages/week-4.html"
                next_pdf = next_page.with_suffix(".pdf")
                old_pdf = next_pdf.read_bytes()

                output = self.remove(name=name, setup="" if REPORTLAB else STUB_REMOVAL_PDF)

                for path, original in copies.items():
                    self.assertTrue(path.is_file(), f"Locked copy was removed: {path.name}")
                    self.assertEqual(path.read_bytes(), original)
                self.assert_unchecked_copy_warning(output)
                self.assertEqual(self.read("weeks/week-3.json")["signed_by"], REPLACEMENT)
                self.assertEqual(self.read("changes.json")[0]["asked_by"], REPLACEMENT)
                self.assertEqual(self.read("pages/week-4-content.json")["headline"],
                                 f"Confirm pickup with {REPLACEMENT}")
                self.assertNotIn(name, next_page.read_text(encoding="utf-8"))
                rebuilt_pdf = next_pdf.read_bytes()
                self.assertNotEqual(rebuilt_pdf, old_pdf)
                self.command("client-copy", setup="" if REPORTLAB else STUB_PDF)
                self.assertEqual(next_pdf.read_bytes(), rebuilt_pdf)

    def test_interrupted_removal_does_not_schedule_unchecked_locked_copies(self):
        name = "Sara Khan"
        self.lock_two_named_weeks(name)
        copies = self.copies_without_content(("html", "pdf"))
        renderer = "" if REPORTLAB else STUB_REMOVAL_PDF
        interrupt = """
from weekflow_tool import lock_transaction
publish = lock_transaction.publish_redaction_entry

def stop_after_first_publication(files, relative, data):
    publish(files, relative, data)
    os._exit(72)

lock_transaction.publish_redaction_entry = stop_after_first_publication
"""
        self.remove(name=name, setup=renderer + interrupt, expected=72)
        journal = self.read(".weekflow-removal.json")
        scheduled = {self.project / row["path"] for row in journal["entries"]}
        self.assertFalse(scheduled.intersection(copies))

        output = self.remove(name=name, setup=renderer)

        self.assertIn("Recovered removal changed weeks 3, 4.", output)
        self.assert_unchecked_copy_warning(output)
        for path, original in copies.items():
            self.assertEqual(path.read_bytes(), original)
        self.assertEqual(self.read("weeks/week-3.json")["signed_by"], REPLACEMENT)
        page = self.weekly / "pages/week-4.html"
        self.assertNotIn(name, page.read_text(encoding="utf-8"))
        self.assertFalse(list(self.weekly.rglob(".weekflow-*")))

    def test_a_name_matching_the_removal_month_does_not_repeat_on_retry(self):
        self.start(attendee="May")
        self.prepare(headline="May reviews the pickup form", confirm=False)
        frozen_date = """
from datetime import date
from weekflow_tool import removal

class MayDate(date):
    @classmethod
    def today(cls):
        return cls(2026, 5, 7)

removal.date = MayDate
"""
        self.remove(name="May", setup=frozen_date)
        replacement = f"Removed on 7 May because {REASON}"
        self.assertEqual(self.read("project.json")["attendees"], [replacement])
        self.assertEqual(self.read("pages/draft.json")["headline"], f"{replacement} reviews the pickup form")
        completed = snapshot(self.weekly)
        self.remove(name="May", reason="Checked by the owner",
                    setup=frozen_date.replace("cls(2026, 5, 7)", "cls(2026, 6, 1)"))
        self.assertEqual(snapshot(self.weekly), completed)

    def test_a_name_matching_the_notice_wording_uses_alternate_wording(self):
        self.start(attendee="Removed")
        self.prepare(headline="Removed reviews the pickup form", confirm=False)
        self.remove(name="Removed")
        replacement = f"Withheld · {PLAIN_TODAY} · {REASON}"
        self.assertEqual(self.read("project.json")["attendees"], [replacement])
        self.assertEqual(self.read("pages/week-3-content.json")["headline"],
                         f"{replacement} reviews the pickup form")

    def test_text_in_an_earlier_removal_reason_can_still_be_removed(self):
        self.start(attendee="Sam")
        self.remove(reason="Requested by Alex")
        self.remove(name="Alex")
        self.assertEqual(self.read("project.json")["attendees"],
                         [f"Removed on {PLAIN_TODAY} because Requested by {REPLACEMENT}"])

    def test_replacement_reason_must_fit_the_headline_font(self):
        self.start()
        self.prepare(headline="Reason reviews the pickup form", confirm=False)
        original = snapshot(self.weekly)
        output = self.remove(name="Reason", reason="Use a single mark ↔", setup=BLOCK_REPORTLAB, expected=2)
        self.assertIn("removal reason", output)
        self.assertEqual(snapshot(self.weekly), original)

    def test_removal_can_target_a_legacy_name_the_font_cannot_draw(self):
        self.start()
        project_path = self.weekly / "project.json"
        project_path.write_text(json.dumps(dict(self.read("project.json"), attendees=["محمد"])),
                                encoding="utf-8")
        self.remove(name="محمد", setup=BLOCK_REPORTLAB)
        self.assertEqual(self.read("project.json")["attendees"], [REPLACEMENT])

    @unittest.skipUnless(REPORTLAB, "reportlab is unavailable")
    @unittest.skipUnless(PDFTOTEXT, "pdftotext is unavailable")
    def test_locked_pages_and_pdf_copies_remain_valid_after_redaction(self):
        self.start(attendee="sAM")
        self.command("change", "--what", "Enable Sambunwick pickup", "--reason", "The shop asked",
                     "--asked-by", "Sam", "--days", "2")
        self.prepare(next_week=("Show Sam’s pickup notes",), headline="sAm can test Sambunwick")
        self.command("record", "--answer", "C-001=yes", "--attendee", "SAM", "--decided-by", "sAm")
        self.command("client-copy")
        self.command("sign", "--by", "Sam", "--on", "2026-02-25")
        self.command("lock")

        self.command("check-promise", "--id", "P-001", "--status", "not-finished",
                     "--note", "Ask Sam to check Sambunwick")
        self.prepare("2026-03-04")
        self.command("record", "--answer", "--attendee", "the manager")
        self.command("client-copy")
        self.command("lock")
        self.command("correct", "--week", "3", "--what", "Note the pickup form", "--reason",
                     "For the next meeting", "--by", "Sam")
        before = self.read("weeks/week-3.json")
        digests = self.read("pages/week-3-content.json")["source_digests"]

        reason = 'Requested <img src="local"> & checked'
        replacement = f"Removed on {PLAIN_TODAY} because {reason}"
        output = self.remove(reason=reason)
        self.assertIsNone(NAME_WORD.search(output), output)
        self.assertRegex(output, r"3\D+4")
        self.assert_redacted()
        self.assertEqual(self.read("weeks/week-3.json"),
                         dict(before, attendees=[replacement], signed_by=replacement))
        self.assertEqual(self.read("pages/week-3-content.json")["source_digests"], digests)
        self.assertEqual(self.read("changes.json")[0]["what"], "Enable Sambunwick pickup")
        self.assertEqual(self.read("changes.json")[0]["decided_by"], replacement)
        self.assertIn(replacement, self.read("promises.json")[0]["note"])
        self.assertEqual([(row["kind"], row["week"]) for row in self.read("corrections.json")],
                         [("correction", 3), ("removal", 3), ("removal", 4)])

        for number in (4, 3):
            with self.subTest(week=number):
                page = self.weekly / f"pages/week-{number}.html"
                self.assertNotIn("<img src=", page.read_text(encoding="utf-8"))
                self.assertIn("&lt;img src=", page.read_text(encoding="utf-8"))
                path = page.with_suffix(".pdf")
                copy_before = path.read_bytes()
                self.command("client-copy")
                self.assertEqual(path.read_bytes(), copy_before)
                result = subprocess.run([PDFTOTEXT, str(path), "-"], check=True, capture_output=True,
                                        text=True, timeout=15)
                self.assertIsNone(NAME_WORD.search(result.stdout), result.stdout)
                self.assertIn("Sambunwick", result.stdout)
                # Use the same command to check the older copy after removing only the later
                # Week from this throwaway project. The command addresses the newest record.
                if number == 4:
                    (self.weekly / "weeks/week-4.json").unlink()

    def test_every_published_replacement_and_retirement_can_be_interrupted(self):
        self.start(attendee="sam")
        self.command("change", "--what", "Schedule Sambunwick pickup", "--reason", "The shop asked",
                     "--asked-by", "Sam", "--days", "0")
        self.prepare(headline="Review Sam’s pickup form")
        self.command("record", "--answer", "C-001=yes", "--attendee", "Sam", "--decided-by", "Sam")
        self.command("client-copy", setup="" if REPORTLAB else STUB_PDF)
        self.command("lock")
        self.prepare("2026-03-04", headline="Check Sambunwick with Sam")
        self.command("client-copy", setup="" if REPORTLAB else STUB_PDF)
        seed = self.scratch / "before-removal"
        shutil.copytree(self.project, seed)

        trace = """
from weekflow_tool import lock_transaction
publish = lock_transaction.publish_redaction_entry

def record_step(files, relative, data):
    print('Publication', flush=True)
    publish(files, relative, data)

lock_transaction.publish_redaction_entry = record_step
"""
        renderer = "" if REPORTLAB else STUB_REMOVAL_PDF
        result = self.remove(setup=renderer + trace)
        count = result.splitlines().count("Publication")
        self.assertGreaterEqual(count, 9)
        completed = snapshot(self.weekly)

        for cut in range(count + 1):
            with self.subTest(after_publications=cut):
                self.project = self.scratch / f"interrupted-{cut}"
                shutil.copytree(seed, self.project)
                self.weekly = self.project / "docs/weekly"
                interrupt = f"""
from weekflow_tool import lock_transaction
publish = lock_transaction.publish_redaction_entry
count = 0

def interrupt_publish(files, relative, data):
    global count
    if {cut} == 0:
        os._exit(70)
    publish(files, relative, data)
    count += 1
    if count == {cut}:
        os._exit(70)

lock_transaction.publish_redaction_entry = interrupt_publish
"""
                self.remove(setup=renderer + interrupt, expected=70)
                journal = self.read(".weekflow-removal.json")
                self.assertEqual(journal["weeks"], [3, 4])
                for row in journal["entries"]:
                    if row["data"] is not None:
                        self.assertIsNone(re.search(rb"(?<!\w)Sam(?!\w)", b64decode(row["data"]), re.IGNORECASE))
                output = self.remove(setup=renderer)
                self.assertIn("Recovered removal changed weeks 3, 4.", output)
                self.assertEqual(snapshot(self.weekly), completed)
                self.assert_redacted()

        self.project = self.scratch / "interrupted-before-pdf-replace"
        shutil.copytree(seed, self.project)
        self.weekly = self.project / "docs/weekly"
        interrupt = """
replace = os.replace

def stop_before_pdf(source, destination):
    if os.path.basename(destination) == 'week-3.pdf':
        with open(source, 'rb') as staged:
            assert staged.read(5) == b'%PDF-'
        os._exit(71)
    replace(source, destination)

os.replace = stop_before_pdf
"""
        self.remove(setup=renderer + interrupt, expected=71)
        staging = [path for path in self.weekly.rglob(".weekflow-*")
                   if path.name != ".weekflow-removal.json"]
        self.assertTrue(staging)
        for path in staging:
            self.assertIsNone(re.search(rb"(?<!\w)Sam(?!\w)", path.read_bytes(), re.IGNORECASE))
        output = self.remove(setup=renderer)
        self.assertIn("Recovered removal changed weeks 3, 4.", output)
        self.assertEqual(snapshot(self.weekly), completed)
        self.assert_redacted()
