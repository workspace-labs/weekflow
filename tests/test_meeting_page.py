"""Check the five-step meeting page on disposable copies of the sample."""

from base64 import b64decode, b64encode
from datetime import date, timedelta
from hashlib import sha256
from html import escape
from html.parser import HTMLParser
from importlib.util import find_spec
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from test_weekflow import run_project_command


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "skills/weekflow/scripts/weekflow.py"
FIXTURE = ROOT / "tests/fixtures/corner-bakery"
PANEL_IDS = {f"panel-{number}" for number in range(1, 6)}
PDF_TEXT = find_spec("reportlab") is not None and shutil.which("pdftotext")


class PageMarkup(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.tags = []
        self.text = []
        self.feed(html)

    def handle_starttag(self, tag, attributes):
        self.tags.append((tag, dict(attributes)))

    def handle_data(self, data):
        self.text.append(data)


class MeetingPageTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.project = Path(scratch.name) / "sample"
        shutil.copytree(FIXTURE, self.project)
        self.weekly = self.project / "docs/weekly"
        self.page = self.weekly / "pages/week-3.html"
        self.copy = self.weekly / "pages/week-3.pdf"
        self.draft = self.page.with_name("draft.json")
        self.command("start", "--meeting-day", "Friday", "--language", "en")
        self.draft.parent.mkdir()
        self.write_draft()

    def command(self, command, *args, expected=0):
        result = run_project_command(
            [sys.executable, str(TOOL)], command, self.project, *args,
            cwd=self.project, capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result.stdout + result.stderr

    def write_draft(self, **fields):
        content = dict(
            headline="The bread menu is ready.",
            finished=[{"text": "Oat bread", "source": "app/menu.py"}],
            next_week=[{"text": "Show the pickup form"}],
            needs=[{"text": "Pickup times", "by": "2027-03-01"}],
        )
        content.update(fields)
        self.draft.write_text(json.dumps(content), encoding="utf-8")

    def update_project(self, **fields):
        path = self.weekly / "project.json"
        setup = json.loads(path.read_text(encoding="utf-8"))
        path.write_text(json.dumps(dict(setup, **fields)), encoding="utf-8")

    def add_change(self, days, what="Later pickup", reason="The shop stays open longer",
                   raised_by="the client"):
        self.command("change", "--what", what, "--reason", reason, "--asked-by", raised_by,
                     "--days", str(days))

    def prepare(self, meeting="2027-02-26"):
        self.command("prepare", "--date", meeting, "--content", str(self.draft))
        return self.page.read_text(encoding="utf-8")

    def confirmed_copy(self):
        self.command("confirm")
        self.command("client-copy")
        return self.copy.read_bytes()

    def pdf_text(self):
        self.confirmed_copy()
        return " ".join(subprocess.check_output(["pdftotext", str(self.copy), "-"], text=True).split())

    def test_page_is_self_contained(self):
        self.add_change(2)
        html = self.prepare()
        tags = PageMarkup(html).tags
        self.assertEqual([attributes for tag, attributes in tags if tag == "script"], [{}])
        (script,) = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)
        script_hash = b64encode(sha256(script.encode("utf-8")).digest()).decode("ascii")
        self.assertIn(f"script-src 'sha256-{script_hash}'", html)
        panels = {attributes.get("id") for tag, attributes in tags if tag == "section"} & PANEL_IDS
        allowed_links = {f"#{panel}" for panel in panels}
        for tag, attributes in tags:
            self.assertNotIn(tag, {"iframe", "link", "object", "embed", "base"})
            self.assertFalse({"src", "srcset", "action", "formaction", "poster", "ping"} & attributes.keys())
            self.assertFalse(any(name.startswith("on") for name in attributes))
            if tag == "a":
                self.assertIn(attributes.get("href"), allowed_links)
                self.assertNotIn("target", attributes)
            else:
                self.assertNotIn("href", attributes)
        self.assertIn("font-src data:", html)
        embedded = re.findall(r'url\("data:font/ttf;base64,([A-Za-z0-9+/=]+)"\)', html)
        fonts = TOOL.parents[1] / "assets/fonts"
        expected_fonts = [fonts / f"{family}-{weight}.ttf"
                          for family in ("BricolageGrotesque", "InstrumentSans")
                          for weight in ("Regular", "Bold")]
        self.assertCountEqual([b64decode(face, validate=True) for face in embedded],
                              [path.read_bytes() for path in expected_fonts])
        without_fonts = re.sub(r'url\("data:font/ttf;base64,[A-Za-z0-9+/=]+"\)', "", html)
        self.assertNotRegex(without_fonts, r"(?i)https?://|@import\b|\burl\s*\(")
        self.assertIn('<noscript><p class="quiet">Tell the agent the answers.</p></noscript>', html)

    def test_navigation_links_reach_their_meeting_steps(self):
        tags = PageMarkup(self.prepare()).tags
        links = {attributes.get("id"): attributes.get("href") for tag, attributes in tags if tag == "a"}
        expected = {
            **{f"step-{number}": f"#panel-{number}" for number in range(1, 6)},
            **{f"back-{number}": f"#panel-{number - 1}" for number in range(2, 6)},
            **{f"next-{number}": f"#panel-{number + 1}" for number in range(1, 5)},
        }
        self.assertEqual({control: links.get(control) for control in expected}, expected)

    def test_saved_text_cannot_break_out_of_text_or_attributes(self):
        payload = '<unsafe-tag onclick="bad">O\'Brien & bread</unsafe-tag>'
        self.update_project(project=payload, client=payload, attendees=[payload])
        self.add_change(1, what=payload, reason=payload, raised_by=payload)
        self.write_draft(
            headline=payload,
            finished=[{"text": payload, "source": "app/menu.py"}],
            next_week=[{"text": payload}],
            needs=[{"text": payload, "by": "2027-03-01"}],
        )
        html = self.prepare()
        markup = PageMarkup(html)
        self.assertIn(escape(payload, quote=True), html)
        self.assertTrue(any(payload in attributes.get("aria-label", "") for _, attributes in markup.tags))
        self.assertNotIn(payload, html)
        self.assertIn(payload, " ".join(markup.text))
        for tag, attributes in markup.tags:
            self.assertNotEqual(tag, "unsafe-tag")
            self.assertNotIn("onclick", attributes)
            for name in ("id", "class"):
                self.assertNotRegex(attributes.get(name, ""), r"[<\"'&]|unsafe-tag|O.Brien")

    def test_day_wording_and_sources_on_page_and_copy(self):
        for days in (0, 1, 2):
            self.add_change(days, what=f"Pickup option {days}")
        html = self.prepare()
        self.assertIn("No days added", html)
        source = self.weekly / "pages/week-3-content.json"
        self.assertEqual(json.loads(source.read_text(encoding="utf-8"))["finished"][0]["source"],
                         "app/menu.py")
        outputs = [html]
        self.assertIn("on time", html.casefold())
        if PDF_TEXT:
            copy = self.pdf_text()
            self.assertIn("on time", copy.casefold())
            outputs.append(copy)
        for output in outputs:
            self.assertNotIn("app/menu.py", output)
            self.assertNotIn("1 days", output)
            for wording in ("0 days", "1 day", "2 days"):
                self.assertIn(wording, output)

    def test_decisions_start_with_three_unselected_choices(self):
        self.add_change(1)
        self.add_change(2)
        html = self.prepare()
        markup = PageMarkup(html)
        for index in (1, 2):
            group = f"decision-{index}"
            radios = [attributes for tag, attributes in markup.tags
                      if tag == "input" and attributes.get("name") == group]
            self.assertEqual([control.get("value") for control in radios], ["yes", "later", "no"])
            self.assertTrue(all(control.get("type") == "radio" and "checked" not in control for control in radios))
        for label in ("Yes, now", "After launch", "No", "Not decided"):
            self.assertIn(label, markup.text)

    def test_calendar_offsets_cross_months_years_and_leap_days(self):
        self.add_change(1)
        changes = self.weekly / "changes.json"
        rows = json.loads(changes.read_text(encoding="utf-8"))
        for start, label, days, end in (
            ("2027-03-31", "31 March", 1, "2027-04-01"),
            ("2027-12-31", "31 December", 1, "2028-01-01"),
            ("2028-02-28", "28 February 2028", 1, "2028-02-29"),
            ("2028-02-28", "28 February 2028", 2, "2028-03-01"),
            ("2028-02-29", "29 February 2028", 0, "2028-02-29"),
            ("2027-03-12", "12 March", 100000, "2300-12-26"),
        ):
            with self.subTest(start=start, days=days):
                self.update_project(planned_end=start)
                rows[0]["days_added"] = days
                changes.write_text(json.dumps(rows), encoding="utf-8")
                html = self.prepare()
                self.assertIn(f'<time datetime="{start}">{label}</time>', html)
                start_days = re.findall(r"--start-day:\s*(\d+)", html)
                self.assertEqual(start_days, [str(date.fromisoformat(start).toordinal() - 1)])
                self.assertRegex(html, r"--meeting-year:\s*2027\b")
                offsets = [int(value) for value in re.findall(r"--days-\d+:\s*(\d+)", html)]
                selected_offset = max(offsets, default=0)
                self.assertEqual(selected_offset, days)
                initial = date(1, 1, 1) + timedelta(days=int(start_days[0]))
                self.assertEqual((initial + timedelta(days=selected_offset)).isoformat(), end)

    def test_layout_a_shows_both_dates_even_if_the_meeting_is_outside_the_delivery_window(self):
        approval = "2027-02-08"
        for delivery, meeting in (
            ("2027-03-12", "2027-02-26"),
            ("2027-03-12", approval),
            ("2027-03-12", "2027-03-12"),
            ("2027-03-12", "2027-02-07"),
            ("2027-03-12", "2027-03-13"),
            (approval, approval),
            ("2027-02-07", approval),
        ):
            with self.subTest(delivery=delivery, meeting=meeting):
                self.update_project(planned_end=delivery)
                html = self.prepare(meeting)
                classes = [attributes.get("class", "").split() for _, attributes in PageMarkup(html).tags]
                self.assertIn(["delivery-track"], classes)
                offset = (date.fromisoformat(delivery) - date.fromisoformat(meeting)).days
                self.assertIn(f'--plan-from-meeting: {offset}"', html)
                self.assertIn(f'datetime="{delivery}"', html)
                self.assertIn(f'datetime="{meeting}"', html)
                self.assertIn("The bread menu is ready.", html)
                self.assertIn("What we agreed", html)

    def test_meeting_number_is_distinct_from_the_calendar_week(self):
        html = self.prepare("2027-02-11")
        page_text = " ".join(" ".join(PageMarkup(html).text).split())
        self.assertIn("· Weekly meeting 3 11 February", page_text)
        self.assertNotIn("Week 3", page_text)
        if PDF_TEXT:
            copy = self.pdf_text()
            self.assertIn("weekly meeting 3", copy.casefold())
            self.assertIn("11 February", copy)
            self.assertNotIn("Week 1 of 5", copy)
            self.assertNotIn("Week 3", copy)

        record = self.weekly / "weeks/week-3.json"
        self.assertEqual(json.loads(record.read_text(encoding="utf-8"))["number"], 3)

    def test_empty_steps_say_what_is_empty(self):
        self.write_draft(finished=[], next_week=[], needs=[])
        html = self.prepare()
        outputs = [html]
        if PDF_TEXT:
            outputs.append(self.pdf_text())
        for output in outputs:
            for message in ("No finished work is listed.", "No decisions are waiting.",
                            "No items are planned for next week.", "Nothing is needed from the client."):
                self.assertIn(message, output)
        self.assertIn("No days added", html)
        self.assertIn("running-total", html)

    def test_page_size_grows_in_even_steps(self):
        sizes = []
        for _ in range(12):
            self.add_change(10000)
            sizes.append(len(self.prepare().encode("utf-8")))
        growth = [after - before for before, after in zip(sizes, sizes[1:])]
        self.assertGreater(min(growth), 0, sizes)
        self.assertLessEqual(max(growth), min(growth) * 1.10, sizes)

    def test_edits_are_refused_after_deterministic_preparation(self):
        self.add_change(1)
        first = self.prepare()
        self.assertEqual(self.prepare(), first)
        self.command("client-copy", expected=2)
        self.assertFalse(self.copy.exists())
        self.command("confirm")
        original = self.confirmed_copy() if find_spec("reportlab") is not None else None
        self.page.write_text(first + "<!-- Edited -->\n", encoding="utf-8")
        for command in ("confirm", "client-copy"):
            with self.subTest(command=command):
                self.assertIn("Prepare", self.command(command, expected=2))
        if original is None:
            self.assertFalse(self.copy.exists())
        else:
            self.assertEqual(self.copy.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
