"""Run the command line on disposable copies of the bakery."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
import re
import shutil
from pdftotext_file import poppler_pdftotext
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from hashlib import sha256
from html.parser import HTMLParser
from importlib.util import find_spec
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "skills/weekflow/scripts/weekflow.py"
FIXTURE = ROOT / "tests/fixtures/corner-bakery"
PROJECT_FIELDS = {
    "project", "client", "meeting_day", "language", "attendees", "mode",
    "scope_approved_on", "planned_end",
}
CHANGE_FIELDS = {
    "id", "date", "what", "reason", "asked_by", "days_added", "status",
    "decided_week", "decided_by",
}
WEEK_FIELDS = {
    "number", "meeting_date", "held", "attendees", "mode", "answers",
    "end_before", "end_after", "decisions_left", "owner_confirmed_on",
    "signed_by", "signed_on", "locked_on",
}
SECTIONS = ["where we are", "see it", "your decisions", "next week", "what we agreed"]
PDF_TEXT = find_spec("reportlab") is not None and poppler_pdftotext()
TEST_PDF_RENDERER = """
from weekflow_tool import client_pdf

def render_pdf(view):
    return ("%PDF-1.4\\n" + view.fingerprint + "\\n%%EOF\\n").encode("ascii")

client_pdf.render_pdf = render_pdf
"""
ORIGINAL_PAGE_PREPARE = """
sys.path.insert(0, os.path.dirname(sys.argv[1]))
from weekflow_tool import meetings

meetings.PAGE_LAYOUT_A = None
"""


def cli_date_setup(day):
    """Give one fixture's CLI subprocess a fixed date."""
    return f"""
import datetime

class FixtureDate(datetime.date):
    @classmethod
    def today(cls):
        return cls.fromisoformat({day!r})

datetime.date = FixtureDate
"""


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.headings = []
        self.current_heading = None

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, attrs))
        if re.fullmatch(r"h[1-6]", tag):
            self.current_heading = []

    def handle_data(self, data):
        if self.current_heading is not None:
            self.current_heading.append(data)

    def handle_endtag(self, tag):
        if re.fullmatch(r"h[1-6]", tag) and self.current_heading is not None:
            self.headings.append("".join(self.current_heading).strip().casefold())
            self.current_heading = None


def snapshot(root):
    entries = {}
    for path in root.rglob("*"):
        data = None
        if path.is_symlink():
            data = path.readlink()
        elif path.is_file():
            data = path.read_bytes()
        entries[path.relative_to(root).as_posix()] = data
    return entries


def run_project_command(launcher, command, project, *options, **kwargs):
    """Let existing fixture tests explicitly accept standard colours when prompted."""
    invocation = [*launcher, command, str(project), *options]
    result = subprocess.run(invocation, **kwargs)
    if (command == "prepare" and result.returncode == 2
            and "Use --colors standard or --main-color" in result.stderr):
        return subprocess.run([*invocation, "--colors", "standard"], **kwargs)
    return result


class WeekflowTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.scratch = Path(scratch.name)
        self.project = self.scratch / "bakery"
        shutil.copytree(FIXTURE, self.project)
        self.weekly = self.project / "docs/weekly"
        self.pages = self.weekly / "pages"
        self.weeks = self.weekly / "weeks"
        self.plan_date = "2027-03-12"
        self.meeting_date = "2027-02-26"
        self.prd = self.project / "docs/prd.md"
        self.content_path = self.pages / "draft.json"
        self.page = self.pages / "week-3.html"
        self.client_page = self.pages / "week-3.pdf"
        self.week = self.weeks / "week-3.json"

    def command(self, command, *options, setup=""):
        loader = []
        if setup:
            loader = ["-c", f"""
import os
import runpy
import sys

sys.path.insert(0, os.path.dirname(sys.argv[1]))
{setup}

sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name="__main__")
"""]
        return run_project_command(
            [sys.executable, *loader, str(TOOL)], command, self.project, *options,
            cwd=self.scratch, capture_output=True, text=True, encoding="utf-8", timeout=15,
        )

    def succeed(self, command, *options):
        result = self.command(command, *options)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout + result.stderr

    def make_test_pdf(self):
        result = self.command("client-copy", setup=TEST_PDF_RENDERER)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return self.client_page.read_bytes()

    def pdf_text(self):
        self.succeed("client-copy")
        return subprocess.check_output(["pdftotext", "-enc", "UTF-8", str(self.client_page), "-"], text=True, encoding="utf-8")

    def refuse(self, command, *options):
        original = snapshot(self.scratch)
        result = self.command(command, *options)
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 2, output)
        lines = output.strip().splitlines()
        self.assertTrue(lines)
        for number, line in enumerate(lines, 1):
            self.assertRegex(line, rf"^{number}\. .+")
        self.assertEqual(snapshot(self.scratch), original)
        return output

    def start(self, *options):
        return self.succeed("start", "--meeting-day", "Friday", "--language", "en", *options)

    def change(self, *options):
        return self.succeed(
            "change", "--what", "Offer a later pickup slot",
            "--reason", "The shop stays open longer", "--asked-by", "the client", *options,
        )

    def write_content(self, **overrides):
        content = {
            "headline": "The bread menu is ready.",
            "finished": [{"text": "Oat bread and spice buns", "source": "app/menu.py"}],
            "next_week": [{"text": "Show the pickup form"}],
            "needs": [{"text": "Pickup times", "by": "2027-03-01"}],
        }
        content.update(overrides)
        self.pages.mkdir(parents=True, exist_ok=True)
        self.content_path.write_text(json.dumps(content), encoding="utf-8")
        return content

    def prepare(self, meeting_date=None):
        return self.succeed(
            "prepare", "--content", str(self.content_path),
            "--date", meeting_date or self.meeting_date,
        )

    def refuse_prepare(self):
        return self.refuse("prepare", "--content", str(self.content_path), "--date", self.meeting_date)

    def read_json(self, path):
        return json.loads(path.read_text(encoding="utf-8"))

    def test_start_lists_only_missing_options_and_reads_the_project_files(self):
        output = self.refuse("start").casefold()
        self.assertEqual(len(output.strip().splitlines()), 2)
        for name in ("meeting_day", "language"):
            self.assertIn(name, output)
        output = self.start()
        self.assertIn("docs/prd.md", output)
        self.assertIn(f"- **Dates:** Ready for pickup orders by {self.plan_date}.", output)
        row = self.read_json(self.weekly / "project.json")
        self.assertEqual(set(row), PROJECT_FIELDS)
        self.assertEqual(row, {
            "project": "Corner Bakery", "client": "Corner Bakery shop",
            "meeting_day": "Friday", "language": "en", "attendees": ["the owner", "the client"],
            "mode": "build", "scope_approved_on": "2027-02-08", "planned_end": self.plan_date,
        })
        self.refuse("start", "--meeting-day", "Monday", "--language", "en")

    def test_start_uses_docs_mode_with_a_draft_prd(self):
        original = self.prd.read_text(encoding="utf-8")
        self.prd.write_text(original.replace("Approved 2027-02-08 by the client", "Draft"), encoding="utf-8")
        self.start()
        row = self.read_json(self.weekly / "project.json")
        self.assertEqual(set(row), PROJECT_FIELDS)
        self.assertEqual(row["project"], "Corner Bakery")
        self.assertEqual((row["mode"], row["scope_approved_on"], row["planned_end"]), ("docs", "", ""))

    def test_start_lists_client_and_attendees_as_optional_without_a_form(self):
        (self.project / "docs/meeting-form.md").unlink()
        output = self.start().lower()
        for phrase in ("client", "attendees", "optional", "once"):
            self.assertIn(phrase, output)
        row = self.read_json(self.weekly / "project.json")
        self.assertEqual((row["client"], row["attendees"]), ("", []))

    def test_start_requires_one_planned_end_or_an_owner_override(self):
        original = self.prd.read_text(encoding="utf-8")
        for value in ("before spring", "between 2027-03-11 and 2027-03-12"):
            with self.subTest(dates=value):
                amended = original.replace(f"Ready for pickup orders by {self.plan_date}.", value)
                self.prd.write_text(amended, encoding="utf-8")
                output = self.refuse("start", "--meeting-day", "Friday", "--language", "en")
                self.assertIn("planned_end", output.casefold())
        self.start("--planned-end", "2027-03-20", "--client", "the client", "--attendee", "the owner")
        row = self.read_json(self.weekly / "project.json")
        self.assertEqual(row["planned_end"], "2027-03-20")
        self.assertEqual(row["client"], "the client")
        self.assertEqual(row["attendees"], ["the owner"])

    def set_prd_dates(self, dates):
        original = self.prd.read_text(encoding="utf-8")
        line = f"- **Dates:** Ready for pickup orders by {self.plan_date}."
        self.assertIn(line, original)
        self.prd.write_text(original.replace(line, dates), encoding="utf-8")

    def test_start_reads_latest_prd_date_change_and_shows_the_source(self):
        current = "- Changed 2027-02-20: 2027-03-28 → 2027-04-15, because the launch moved."
        self.set_prd_dates(
            f"- **Dates:** Ready for pickup orders by {self.plan_date}.\n"
            "  - Changed 2027-02-15: 2027-03-12 → 2027-03-28, because of a late fixture.\n"
            f"  {current}"
        )
        output = self.start()
        self.assertEqual(self.read_json(self.weekly / "project.json")["planned_end"], "2027-04-15")
        self.assertIn("docs/prd.md", output)
        self.assertIn(current, output)

    def test_start_does_not_use_date_in_an_unresolved_prd_dates_line(self):
        self.set_prd_dates("- **Dates:** TBD: the launch date. Decided at a meeting on 2027-03-01.")
        output = self.refuse("start", "--meeting-day", "Friday", "--language", "en")
        self.assertIn("planned_end", output.casefold())

    def test_start_does_not_use_a_start_date_when_there_is_no_end(self):
        self.set_prd_dates("- **Dates:** work starts 2027-02-08; no end date yet.")
        output = self.refuse("start", "--meeting-day", "Friday", "--language", "en")
        self.assertIn("planned_end", output.casefold())

    def test_start_does_not_fall_back_to_a_date_superseded_by_tbd(self):
        self.set_prd_dates(
            f"- **Dates:** Ready for pickup orders by {self.plan_date}.\n"
            "  - Changed 2027-02-15: 2027-03-12 → 2027-03-28, because of a late fixture.\n"
            "  - Changed 2027-02-20: 2027-03-28 → TBD, because of the meeting on 2027-03-01."
        )
        output = self.refuse("start", "--meeting-day", "Friday", "--language", "en")
        self.assertIn("planned_end", output.casefold())

    def test_start_does_not_fall_back_when_the_latest_date_is_ambiguous(self):
        self.set_prd_dates(
            f"- **Dates:** Ready for pickup orders by {self.plan_date}.\n"
            "  - Changed 2027-02-15: 2027-03-12 → 2027-03-28, because of a late fixture.\n"
            "  - Changed 2027-02-20: 2027-03-28 → 2027-04-02 or 2027-04-03, because space is limited."
        )
        output = self.refuse("start", "--meeting-day", "Friday", "--language", "en")
        self.assertIn("planned_end", output.casefold())

    def test_correct_date_replaces_an_inferred_kickoff_date_before_the_first_week(self):
        dates = "- **Dates:** Kickoff on 2027-02-08."
        self.set_prd_dates(dates)
        output = self.start()
        self.assertIn(dates, output)
        record = self.weekly / "project.json"
        original = self.read_json(record)
        self.assertEqual(original["planned_end"], "2027-02-08")
        self.refuse("start", "--planned-end", "2027-03-28", "--meeting-day", "Thursday", "--language", "en")

        before = snapshot(self.scratch)
        self.succeed("correct-date", "--planned-end", "2027-03-28")
        self.assertEqual(self.read_json(record), dict(original, planned_end="2027-03-28"))
        before[record.relative_to(self.scratch).as_posix()] = record.read_bytes()
        self.assertEqual(snapshot(self.scratch), before)

        self.write_content()
        self.prepare()
        self.assertEqual(self.read_json(self.week)["end_before"], "2027-03-28")
        self.assertIn("2027-03-28", self.page.read_text(encoding="utf-8"))

    def test_correct_date_refuses_invalid_dates_without_a_write(self):
        self.start()
        for invalid in ("2027-02-29", "2027-3-28"):
            with self.subTest(invalid=invalid):
                output = self.refuse("correct-date", "--planned-end", invalid)
                self.assertIn("planned_end", output.casefold())

    def test_correct_date_refuses_after_a_week_record_exists_without_a_write(self):
        self.start()
        self.write_content()
        self.prepare()
        output = self.refuse("correct-date", "--planned-end", "2027-03-28").casefold()
        self.assertRegex(output, r"\b(?:week|meeting)\b")
        self.assertRegex(output, r"\b(?:already|exists|prepared|record)\b")

    def test_correct_date_requires_existing_setup_without_a_write(self):
        output = self.refuse("correct-date", "--planned-end", "2027-03-28").casefold()
        self.assertRegex(output, r"\b(?:run start|set up|setup)\b")

    def test_start_creates_once_when_hard_links_are_unavailable(self):
        setup = """
import errno

def unavailable(*args, **kwargs):
    raise OSError(errno.ENOTSUP, "Hard links are unavailable.")

os.link = unavailable
"""
        args = ("start", "--meeting-day", "Friday", "--language", "en")
        created = self.command(*args, setup=setup)
        self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
        record = self.weekly / "project.json"
        self.assertEqual(self.read_json(record)["planned_end"], self.plan_date)
        before = snapshot(self.scratch)
        repeated = self.command(*args, "--client", "another client", setup=setup)
        self.assertEqual(repeated.returncode, 2, repeated.stdout + repeated.stderr)
        self.assertEqual(snapshot(self.scratch), before)

    def test_change_keeps_missing_days_and_prevents_prepare_until_filled(self):
        self.start()
        self.write_content()
        output = self.change()
        self.assertIn("days", output.lower())
        path = self.weekly / "changes.json"
        row, = self.read_json(path)
        self.assertEqual(set(row), CHANGE_FIELDS)
        self.assertEqual(row["id"], "C-001")
        self.assertEqual(row["date"], date.today().isoformat())
        self.assertEqual(row["status"], "waiting")
        self.assertIsNone(row["days_added"])
        output = self.refuse_prepare()
        self.assertTrue("C-001" in output or "Offer a later pickup slot" in output)
        self.succeed("change", "--id", "C-001", "--days", "0")
        self.assertEqual(self.read_json(path), [dict(row, days_added=0)])
        self.prepare()
        self.change("--days", "2")
        self.assertEqual([row["id"] for row in self.read_json(path)], ["C-001", "C-002"])

    def test_days_reject_negative_or_fractional_numbers(self):
        self.start()
        for value in ("-1", "1.5"):
            with self.subTest(days=value):
                self.refuse("change", "--what", "New slot", "--reason", "More orders",
                            "--asked-by", "the client", "--days", value)

    @unittest.skipUnless(os.name == "posix", "This check uses the POSIX project lock.")
    def test_overlapping_changes_keep_every_row_and_generate_unique_ids(self):
        self.start()

        def add(index):
            return self.command(
                "change", "--what", f"Pickup idea {index}", "--reason", "More orders",
                "--asked-by", "the client", "--days", "1",
            )

        with ThreadPoolExecutor(max_workers=4) as pool:
            for result in pool.map(add, range(8)):
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        rows = self.read_json(self.weekly / "changes.json")
        self.assertEqual([row["id"] for row in rows], [f"C-{index:03d}" for index in range(1, 9)])
        self.assertEqual({row["what"] for row in rows}, {f"Pickup idea {index}" for index in range(8)})

    def test_prepare_refuses_a_broken_draft_and_a_bad_date(self):
        self.start()
        self.pages.mkdir()
        self.content_path.write_text("{", encoding="utf-8")
        self.refuse_prepare()
        self.write_content(headline="Broken \ud800 text")
        self.refuse_prepare()
        self.write_content()
        self.refuse("prepare", "--content", str(self.content_path))
        self.refuse("prepare", "--content", str(self.content_path), "--date", "2027-02-30")

    def test_prepare_refuses_drafts_outside_the_weekly_pages_folder(self):
        self.start()
        outside = self.project / "old-draft.json"
        outside.write_text(json.dumps({"headline": "An old draft with a removed name."}), encoding="utf-8")
        for draft in (str(outside), "old-draft.json"):
            with self.subTest(draft=draft):
                message = self.refuse("prepare", "--content", draft, "--date", self.meeting_date)
                self.assertIn("docs/weekly/pages/", message)

    def test_prepare_refuses_a_draft_link_to_a_file_elsewhere_in_the_project(self):
        self.start()
        draft = self.project / "old-draft.json"
        draft.write_text('{"headline": "An old draft with a removed name."}', encoding="utf-8")
        self.pages.mkdir()
        try:
            self.content_path.symlink_to(draft)
        except (OSError, NotImplementedError):
            self.skipTest("This system does not allow test symlinks.")
        self.refuse_prepare()
        relative = self.content_path.relative_to(self.project).as_posix()
        self.assertIn("Replace links", self.refuse("prepare", "--content", relative, "--date", self.meeting_date))

    def test_prepare_refuses_missing_traversal_absolute_and_directory_sources(self):
        self.start()
        for source in ("app/missing.py", "app/../app/menu.py", str(self.project / "app/menu.py"), "app"):
            with self.subTest(source=source):
                self.write_content(finished=[{"text": "Missing proof", "source": source}])
                self.assertIn("Missing proof", self.refuse_prepare())
        self.assertFalse(self.page.exists())

    def test_prepare_refuses_source_and_content_symlinks_outside_the_project(self):
        self.start()
        outside = self.scratch / "outside.txt"
        outside.write_text("Outside the project.", encoding="utf-8")
        link = self.project / "app/external.txt"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("This system does not allow test symlinks.")
        self.write_content(finished=[{"text": "Outside proof", "source": "app/external.txt"}])
        self.assertIn("Outside proof", self.refuse_prepare())
        self.write_content()
        outside.write_bytes(self.content_path.read_bytes())
        escape = self.pages / "outside.json"
        escape.symlink_to(outside)
        self.refuse("prepare", "--content", str(escape), "--date", self.meeting_date)

    def test_prepare_refuses_weekly_outputs_as_finished_sources(self):
        self.start()
        upper = self.project / "DOCS/WEEKLY/PROJECT.JSON"
        if not upper.exists():
            upper.parent.mkdir(parents=True, exist_ok=True)
            upper.write_text("{}", encoding="utf-8")
        for source in ("docs/weekly/project.json", "DOCS/WEEKLY/PROJECT.JSON",
                       "./docs/./weekly/project.json", r"docs\weekly\project.json"):
            with self.subTest(source=source):
                self.write_content(finished=[{"text": "Weekly output", "source": source}])
                self.assertIn("Weekly output", self.refuse_prepare())

    def test_prepare_refuses_a_source_link_into_weekly_outputs(self):
        self.start()
        link = self.project / "app/weekly-record.json"
        try:
            link.symlink_to(self.weekly / "project.json")
        except (OSError, NotImplementedError):
            self.skipTest("This system does not allow test symlinks.")
        self.write_content(finished=[{"text": "Weekly output", "source": "app/weekly-record.json"}])
        self.assertIn("Weekly output", self.refuse_prepare())

    def test_prepare_keeps_records_and_facts_in_the_five_escaped_sections(self):
        self.start()
        content = self.write_content()
        change = "<script>Later pickup</script> & bread"
        self.succeed("change", "--what", change, "--reason", "More pickup slots",
                     "--asked-by", "the client", "--days", "1")
        self.succeed("prepare", "--content", "docs/weekly/pages/draft.json", "--date", self.meeting_date)
        saved_content = self.read_json(self.pages / "week-3-content.json")
        self.assertEqual([decision["id"] for decision in saved_content.pop("meeting_changes")], ["C-001"])
        self.assertEqual(saved_content.pop("source_digests"),
                         [sha256((self.project / "app/menu.py").read_bytes()).hexdigest()])
        self.assertEqual(saved_content.pop("design")["radius"], 20)
        self.assertEqual(saved_content, content)
        row = self.read_json(self.week)
        self.assertLessEqual(set(row), WEEK_FIELDS)
        for field, expected in {
            "number": 3, "meeting_date": self.meeting_date, "held": False,
            "mode": "build", "end_before": self.plan_date,
        }.items():
            self.assertEqual(row[field], expected)
        self.assertFalse(row["owner_confirmed_on"])
        html = self.page.read_text(encoding="utf-8")
        page = PageParser()
        page.feed(html)
        self.assertEqual([label for label in page.headings if label in SECTIONS], SECTIONS)
        self.assertEqual([attrs for tag, attrs in page.tags if tag == "script"], [[]])
        self.assertFalse({"iframe", "link"} & {tag for tag, _ in page.tags})
        allowed_links = {f"#panel-{number}" for number in range(1, 6)}
        for tag, attributes in page.tags:
            if tag == "a":
                self.assertIn(dict(attributes).get("href"), allowed_links)
        for line in ("The bread menu is ready.", "Oat bread and spice buns", "Show the pickup form",
                     "Pickup times", "More pickup slots", "&lt;script&gt;Later pickup&lt;/script&gt; &amp; bread"):
            self.assertIn(line, html)
        self.assertNotIn("When will the shop decide the pickup window?", html)

    def test_content_cannot_add_a_decision(self):
        self.start()
        self.write_content(decisions=[{"text": "Make up a fake decision"}])
        original = snapshot(self.scratch)
        result = self.command("prepare", "--content", str(self.content_path), "--date", self.meeting_date)
        self.assertIn(result.returncode, (0, 2), result.stdout + result.stderr)
        if result.returncode == 0:
            self.assertNotIn("Make up a fake decision", self.page.read_text(encoding="utf-8"))
        else:
            self.assertEqual(snapshot(self.scratch), original)

    def test_same_or_different_date_reprepares_the_unlocked_week(self):
        self.start()
        self.write_content()
        self.prepare()
        for meeting_date in (self.meeting_date, "2027-03-01"):
            with self.subTest(meeting_date=meeting_date):
                self.succeed("confirm")
                self.assertTrue(self.read_json(self.week)["owner_confirmed_on"])
                self.write_content(headline=f"The menu is ready for {meeting_date}.")
                self.prepare(meeting_date)
                self.assertEqual(list(self.weeks.glob("week-*.json")), [self.week])
                self.assertEqual(self.read_json(self.week)["meeting_date"], meeting_date)
                self.assertFalse(self.read_json(self.week)["owner_confirmed_on"])
                self.assertIn(meeting_date, self.page.read_text(encoding="utf-8"))

    def test_prepare_advances_only_after_a_locked_week_and_preserves_it(self):
        self.start()
        self.write_content()
        self.prepare()
        locked = dict(self.read_json(self.week), locked_on="2027-02-27")
        self.week.write_text(json.dumps(locked), encoding="utf-8")
        original = self.week.read_bytes(), self.page.read_bytes()
        self.prepare("2027-03-03")
        self.assertEqual((self.week.read_bytes(), self.page.read_bytes()), original)
        self.assertEqual(self.read_json(self.weeks / "week-4.json")["number"], 4)
        self.assertTrue((self.pages / "week-4.html").is_file())

    def test_client_copy_requires_confirmation_and_fresh_changes(self):
        self.start()
        self.write_content()
        self.prepare()
        self.refuse("client-copy")
        self.assertFalse(self.client_page.exists())
        self.succeed("confirm")
        self.assertEqual(self.read_json(self.week)["owner_confirmed_on"], date.today().isoformat())
        legacy = self.pages / "week-3-client.txt"
        legacy.write_text("Previous local copy.", encoding="utf-8")
        copy = self.make_test_pdf()
        self.assertFalse(legacy.exists())
        self.change("--days", "2")
        self.assertIn("prepare", self.refuse("client-copy").lower())
        self.assertIn("prepare", self.refuse("confirm").lower())
        self.prepare()
        self.assertFalse(self.client_page.exists())
        self.refuse("client-copy")
        self.succeed("confirm")
        self.assertNotEqual(self.make_test_pdf(), copy)

    def test_refused_prepare_keeps_the_confirmed_page_and_copy(self):
        self.start()
        self.write_content()
        self.prepare()
        self.succeed("confirm")
        self.make_test_pdf()
        self.assertTrue(self.client_page.is_file())
        self.change()
        self.refuse_prepare()

    def test_interrupted_prepare_cannot_leave_an_old_copy_at_the_current_path(self):
        self.start()
        self.write_content()
        self.prepare()
        self.succeed("confirm")
        original = self.make_test_pdf()
        self.write_content(headline="The pickup form is ready.")
        setup = """
replace = os.replace

def stop_after_first_publication(source, destination):
    replace(source, destination)
    if os.path.basename(destination) in {"week-3.json", "week-3-content.json", "week-3.html"}:
        os._exit(91)

os.replace = stop_after_first_publication
"""
        result = self.command(
            "prepare", "--content", str(self.content_path), "--date", self.meeting_date, setup=setup,
        )
        self.assertEqual(result.returncode, 91, result.stdout + result.stderr)
        self.assertFalse(self.client_page.exists())
        self.prepare()
        self.succeed("confirm")
        self.assertNotEqual(self.make_test_pdf(), original)

    def test_prepare_restores_previous_files_and_copy_on_a_write_error(self):
        self.start()
        self.write_content()
        self.prepare()
        self.succeed("confirm")
        self.make_test_pdf()
        self.write_content(headline="The pickup form is ready.")
        before = snapshot(self.scratch)
        setup = """
replace = os.replace

def fail_on_first_page_write(source, destination):
    if os.path.basename(destination) == "week-3.html":
        os.replace = replace
        raise OSError("Test could not replace the page.")
    replace(source, destination)

os.replace = fail_on_first_page_write
"""
        result = self.command(
            "prepare", "--content", str(self.content_path), "--date", "2027-03-01", setup=setup,
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(snapshot(self.scratch), before)
        self.assertIn("The bread menu is ready.", self.page.read_text(encoding="utf-8"))

    def test_prepare_succeeds_when_a_temporary_backup_cannot_be_removed(self):
        self.start()
        self.write_content()
        self.prepare()
        self.succeed("confirm")
        self.make_test_pdf()
        self.write_content(headline="The pickup form is ready.")
        setup = """
from pathlib import Path

unlink = Path.unlink

def leave_one_busy_backup(path, *args, **kwargs):
    if path.name.startswith(".weekflow-") and path.exists():
        Path.unlink = unlink
        raise PermissionError("Test backup is busy.")
    return unlink(path, *args, **kwargs)

Path.unlink = leave_one_busy_backup
"""
        result = self.command(
            "prepare", "--content", str(self.content_path), "--date", self.meeting_date, setup=setup,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.client_page.exists())
        self.assertFalse(self.read_json(self.week)["owner_confirmed_on"])
        self.assertIn("The pickup form is ready.", self.page.read_text(encoding="utf-8"))

    def test_new_one_line_fields_are_read_the_same_on_page_and_copy(self):
        self.start("--client", "Bakery\rshop", "--attendee", "the\u2028owner", "the\u2029client")
        self.succeed("change", "--what", "New\npickup", "--reason", "Extra\rtime",
                     "--asked-by", "shop\u2028lead", "--days", "0")
        self.write_content(
            headline="Bread\u2029menu is ready.",
            finished=[{"text": "Oat\r\nbread", "source": "app/menu.py"}],
            next_week=[{"text": "Show\u0085the form"}],
            needs=[{"text": "Pickup\ntimes", "by": "2027-03-01"}],
        )
        self.prepare()
        self.succeed("confirm")
        expected = ("Bakery shop", "the owner, the client", "New pickup", "Extra time", "shop lead",
                    "Bread menu is ready.", "Oat bread", "Show the form", "Pickup times")
        self.assertEqual([item for item in expected if item not in self.page.read_text(encoding="utf-8")], [])
        if PDF_TEXT:
            copy = self.pdf_text()
            self.assertEqual([item for item in expected if item not in " ".join(copy.split())], [])
            headings = [line.casefold() for line in copy.splitlines() if line.casefold() in SECTIONS]
            self.assertEqual(headings, SECTIONS[1:])

    def test_hand_edited_one_line_fields_stay_within_their_sections(self):
        self.start()
        self.write_content()
        self.change("--days", "2")
        setup_path = self.weekly / "project.json"
        setup = self.read_json(setup_path)
        setup.update(project="Corner\nBakery", client="Bakery\rshop", attendees=["the\u2028owner"])
        setup_path.write_text(json.dumps(setup), encoding="utf-8")
        changes_path = self.weekly / "changes.json"
        changes = self.read_json(changes_path)
        changes[0].update(what="Later\npickup", reason="Longer\u2029hours", asked_by="shop\r\nlead")
        changes_path.write_text(json.dumps(changes), encoding="utf-8")
        self.prepare()
        self.succeed("confirm")
        expected = ("Corner Bakery", "Bakery shop", "the owner", "Later pickup", "Longer hours", "shop lead")
        self.assertEqual([item for item in expected if item not in self.page.read_text(encoding="utf-8")], [])
        if PDF_TEXT:
            copy = " ".join(self.pdf_text().split())
            self.assertEqual([item for item in expected if item not in copy], [])

    def test_confirm_refuses_an_altered_page_or_changed_source(self):
        self.start()
        self.write_content()
        self.prepare()
        self.page.write_text("This page was edited.", encoding="utf-8")
        self.assertIn("prepare", self.refuse("confirm").lower())
        self.prepare()
        (self.project / "app/menu.py").write_text('ITEMS = ("Rolls",)\n', encoding="utf-8")
        self.assertIn("prepare", self.refuse("confirm").lower())
        self.assertFalse(self.read_json(self.week)["owner_confirmed_on"])

    def test_client_copy_refuses_a_setup_change_after_confirmation(self):
        self.start()
        self.write_content()
        self.prepare()
        self.succeed("confirm")
        setup_file = self.weekly / "project.json"
        setup = dict(self.read_json(setup_file), meeting_day="Monday")
        setup_file.write_text(json.dumps(setup), encoding="utf-8")
        self.assertIn("prepare", self.refuse("client-copy").lower())
        self.assertFalse(self.client_page.exists())

    def test_successful_meeting_only_writes_below_weekly(self):
        before = snapshot(self.scratch)
        self.write_content()
        self.start()
        self.change("--days", "1")
        self.prepare()
        self.succeed("confirm")
        self.make_test_pdf()
        after = snapshot(self.scratch)
        prefix = f"{self.project.name}/docs/weekly"
        self.assertEqual(
            {path: data for path, data in after.items()
             if path != prefix and not path.startswith(prefix + "/")},
            before,
        )

    def test_prepare_refuses_weekly_write_through_a_symlink(self):
        self.start()
        outside = self.scratch / "outside"
        outside.mkdir()
        try:
            self.pages.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("This system does not allow test symlinks.")
        draft = outside / self.content_path.name
        draft.write_text('{"headline": "Draft outside the project"}', encoding="utf-8")
        self.refuse_prepare()
        self.assertEqual(list(outside.iterdir()), [draft])
