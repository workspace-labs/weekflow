"""Check meeting records and paper-signature gates on disposable projects."""

from datetime import date, timedelta
from html.parser import HTMLParser
import importlib.util
import json
from pathlib import Path
import re
import shutil
from pdftotext_file import poppler_pdftotext
import subprocess
import sys
import tempfile
import unittest

from test_weekflow import FIXTURE, TOOL, run_project_command, snapshot


REPORTLAB = importlib.util.find_spec("reportlab") is not None
PDFTOTEXT = poppler_pdftotext()
BLOCK_REPORTLAB = """
class WithoutReportLab:
    def find_spec(self, fullname, *args):
        if fullname == "reportlab" or fullname.startswith("reportlab."):
            raise ModuleNotFoundError("Test without reportlab", name=fullname)

sys.meta_path.insert(0, WithoutReportLab())
"""
STUB_PDF = """
sys.path.insert(0, os.path.dirname(sys.argv[1]))
from weekflow_tool import client_pdf

client_pdf.render_pdf = lambda view: b'%PDF-1.4\\n%%EOF\\n'
"""


def normalise(value):
    return " ".join(value.split()).casefold()


class MeetingText(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.inside_body = False
        self.parts = []
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        if tag == "body":
            self.inside_body = True
        if tag == "script":
            self.inside_body = False

    def handle_endtag(self, tag):
        if tag == "script":
            self.inside_body = True

    def handle_data(self, data):
        if self.inside_body:
            self.parts.append(data)


class RecordedMeetingFixture:
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.scratch = Path(scratch.name)
        self.project = self.scratch / "sample"
        shutil.copytree(FIXTURE, self.project)
        weekly = self.project / "docs/weekly"
        self.project_file = weekly / "project.json"
        self.changes = weekly / "changes.json"
        self.week = weekly / "weeks/week-3.json"
        self.page = weekly / "pages/week-3.html"
        self.content = self.page.with_name("week-3-content.json")
        self.pdf = self.page.with_suffix(".pdf")
        self.source = self.project / "app/menu.py"
        self.answers_path = self.scratch / "answers.json"
        self.draft = self.page.parent / "draft.json"
        self.draft.parent.mkdir(parents=True)
        self.meeting_date = "2026-02-26"
        self.write_json(self.draft, {
            "headline": "The bread menu is ready.",
            "finished": [{"text": "Oat bread and spice buns", "source": "app/menu.py"}],
            "next_week": [{"text": "Show the pickup form"}],
            "needs": [{"text": "Pickup times", "by": "2026-03-01"}],
        })

    def command(self, command, *args, setup="", expected=0):
        launcher = [str(TOOL)]
        if setup:
            launcher = ["-c", f"""
import os
import runpy
import sys

{setup}

sys.argv = sys.argv[1:]
sys.path.insert(0, os.path.dirname(sys.argv[0]))
runpy.run_path(sys.argv[0], run_name="__main__")
""", str(TOOL)]
        result = run_project_command(
            [sys.executable, "-B", *launcher], command, self.project, *args,
            cwd=self.scratch, capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, expected, output)
        return output

    def refuse(self, command, *args, setup=""):
        original = snapshot(self.scratch)
        output = self.command(command, *args, setup=setup, expected=2)
        lines = output.strip().splitlines()
        self.assertTrue(lines)
        for index, line in enumerate(lines, 1):
            self.assertRegex(line, rf"^{index}\. .+")
        self.assertEqual(snapshot(self.scratch), original)
        return output.casefold()

    def write_json(self, path, data):
        path.write_text(json.dumps(data), encoding="utf-8")

    def read_json(self, path):
        return json.loads(path.read_text(encoding="utf-8"))

    def start(self, planned_end="2026-03-12"):
        self.command("start", "--language", "en", "--meeting-day", "Thursday",
                     "--planned-end", planned_end)

    def add_change(self, title="Offer a later pickup slot", days=2):
        options = ("--days", str(days)) if days is not None else ()
        self.command("change", "--what", title, "--reason", "The shop stays open longer",
                     "--asked-by", "the client", *options)

    def prepare(self, *, confirm=True):
        self.command("prepare", "--date", self.meeting_date, "--content", str(self.draft))
        if confirm:
            self.command("confirm")

    def answer_file(self, answers):
        html = self.page.read_text(encoding="utf-8")
        match = re.search(r"<!-- Draft fingerprint: ([0-9a-f]{64}) -->", html)
        self.assertIsNotNone(match)
        return {"week": 3, "fingerprint": match[1], "answers": answers}

    def record_saved(self, answers, *, decided_by="the client"):
        self.write_json(self.answers_path, self.answer_file(answers))
        return self.record_download(decided_by=decided_by)

    def record_download(self, *, decided_by="the client"):
        decider = ("--decided-by", decided_by) if decided_by is not None else ()
        return self.command("record", "--answers", str(self.answers_path),
                            "--attendee", "the owner", "--attendee", "the manager", *decider)

    def record_manual(self, *answers):
        flags = [part for answer in answers for part in ("--answer", answer)]
        return self.command("record", *(flags or ["--answer"]), "--attendee", "the owner",
                            *(("--decided-by", "the client") if answers else ()))

    def stamp_stub_pdf(self):
        # Use a current-copy marker without drawing a PDF. The signature, lock and
        # write-failure checks run without ReportLab on either interpreter.
        subprocess.run([sys.executable, "-B", "-c", """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from weekflow_tool.meetings import current_week, fresh_view
from weekflow_tool.pdf_artifact import stamp_pdf
from weekflow_tool.storage import ProjectFiles
files = ProjectFiles(sys.argv[2])
view = fresh_view(files, current_week(files))
Path(sys.argv[3]).write_bytes(stamp_pdf(b'%PDF-1.4\\n%%EOF\\n', view))
""", str(TOOL.parent), str(self.project), str(self.pdf)],
            cwd=self.scratch, check=True, capture_output=True, timeout=15)

    def extract_pdf(self, layout=False):
        options = ["-layout"] if layout else []
        return subprocess.run([PDFTOTEXT, "-enc", "UTF-8", *options, str(self.pdf), "-"],
                              check=True, capture_output=True, text=True, encoding="utf-8", timeout=15).stdout

    def client_copy(self):
        # Exercise the actual copy command and PDF receipt on both interpreters.
        self.command("client-copy", setup="" if REPORTLAB else STUB_PDF)
        return self.pdf.read_bytes()

    def edit_source(self):
        with self.source.open("ab") as source:
            source.write(b"\n# Work continues after the meeting.\n")


class RecordedMeetingTests(RecordedMeetingFixture, unittest.TestCase):
    def test_record_uses_only_saved_change_days_and_keeps_approval_pending(self):
        self.start(planned_end="2026-02-27")
        self.add_change(days=3)
        self.prepare()
        before = self.read_json(self.week)
        page_before = self.page.read_bytes()

        self.record_saved({"C-001": "yes"})

        self.assertEqual(self.read_json(self.week), dict(
            before, held=True, attendees=["the owner", "the manager"],
            answers=[{"id": "C-001", "answer": "yes", "days": 3}], end_after="2026-03-02",
        ))
        self.assertEqual(self.page.read_bytes(), page_before)
        [change] = self.read_json(self.changes)
        self.assertEqual(change["status"], "waiting")
        self.assertIsNone(change["decided_week"])
        self.assertEqual(change["decided_by"], "the client")
        self.assertEqual(self.read_json(self.project_file)["planned_end"], "2026-02-27")

    def test_record_refuses_before_confirmation(self):
        self.start()
        self.add_change()
        self.prepare(confirm=False)
        options = ("--answer", "C-001=yes", "--attendee", "the owner", "--decided-by", "the client")
        self.assertIn("confirm", self.refuse("record", *options))

    def test_request_logged_after_save_waits_for_next_meeting(self):
        self.start()
        self.add_change(days=2)
        self.prepare()
        self.write_json(self.answers_path, self.answer_file({"C-001": "yes"}))
        confirmed_page = self.page.read_bytes()
        download = self.answers_path.read_bytes()
        late_request = "Display a map of pickup bays"
        self.add_change(late_request, days=5)
        _, late_change = self.read_json(self.changes)

        self.assertIn("prepare", self.refuse("client-copy", setup=STUB_PDF))
        self.assertIn("prepare", self.refuse("confirm"))
        self.assertFalse(self.pdf.exists())
        self.record_download()
        pdf = self.client_copy()
        if REPORTLAB and PDFTOTEXT:
            pdf_text = normalise(self.extract_pdf())
            self.assertNotIn(late_request.casefold(), pdf_text)
            self.assertIn("14 march", pdf_text)
        self.command("sign", "--by", "the client", "--on", self.meeting_date)
        self.command("lock")

        week = self.read_json(self.week)
        self.assertEqual(week["answers"], [{"id": "C-001", "answer": "yes", "days": 2}])
        self.assertEqual(week["end_after"], "2026-03-14")
        self.assertEqual(week["locked_on"], date.today().isoformat())
        approved, waiting = self.read_json(self.changes)
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(waiting, late_change)
        self.assertEqual(waiting["status"], "waiting")
        self.assertEqual(self.page.read_bytes(), confirmed_page)
        self.assertEqual(self.answers_path.read_bytes(), download)
        self.assertEqual(self.read_json(self.project_file)["planned_end"], "2026-03-12")

        self.command("check-promise", "--id", "P-001", "--status", "done")
        self.command("prepare", "--date", "2026-03-05", "--content", str(self.draft))
        next_page = self.page.with_name("week-4.html").read_text(encoding="utf-8")
        self.assertIn(late_request, next_page)
        self.assertEqual(self.read_json(self.week.with_name("week-4.json"))["end_before"], "2026-03-14")
        self.assertEqual(self.pdf.read_bytes(), pdf)

    def test_request_without_days_logged_after_save_does_not_block_record(self):
        self.start()
        self.add_change()
        self.prepare()
        self.write_json(self.answers_path, self.answer_file({"C-001": "yes"}))
        self.add_change("Asked for cubby shelves", days=None)
        self.assertIn("days", self.refuse("client-copy", setup=STUB_PDF))
        self.record_download()
        self.assertEqual(self.read_json(self.week)["answers"], [
            {"id": "C-001", "answer": "yes", "days": 2},
        ])
        self.assertIsNone(self.read_json(self.changes)[1]["days_added"])
        self.stamp_stub_pdf()
        self.command("sign", "--by", "the client", "--on", self.meeting_date)
        self.command("lock")
        self.command("check-promise", "--id", "P-001", "--status", "done")
        self.assertIn("c-002", self.refuse("prepare", "--date", "2026-03-05",
                                         "--content", str(self.draft)))

    def test_record_accepts_no_shown_decisions_after_a_request_is_logged(self):
        self.start()
        self.prepare()
        self.write_json(self.answers_path, self.answer_file({}))
        self.add_change(days=None)
        self.record_download(decided_by=None)
        week = self.read_json(self.week)
        self.assertEqual(week["answers"], [])
        self.assertEqual(week["end_after"], week["end_before"])
        self.assertEqual(self.read_json(self.changes)[0]["status"], "waiting")

    def test_record_refuses_an_edited_removed_or_decided_shown_change(self):
        self.start()
        self.add_change()
        self.add_change("An unanswered change")
        self.prepare()
        self.write_json(self.answers_path, self.answer_file({"C-001": "yes"}))
        self.add_change("A new request after saving")
        first, unanswered, added = self.read_json(self.changes)

        for scenario, changes in (
            ("edited", [first, dict(unanswered, reason="The client changed the reason"), added]),
            ("removed", [first, added]),
            ("decided", [first, dict(unanswered, status="approved", decided_week=2,
                                     decided_by="the owner"), added]),
        ):
            with self.subTest(scenario=scenario):
                self.write_json(self.changes, changes)
                self.assertIn("prepare", self.refuse(
                    "record", "--answers", str(self.answers_path),
                    "--attendee", "the owner", "--decided-by", "the client",
                ))

    def test_record_refuses_an_edited_confirmed_page(self):
        self.start()
        self.add_change()
        self.prepare()
        with self.page.open("ab") as page:
            page.write(b"<!-- different -->")
        self.assertIn("prepare", self.refuse("record", "--answer", "C-001=yes",
                           "--attendee", "the owner", "--decided-by", "the client"))

    def check_work_can_continue(self, before_command, *, remove_source=False):
        self.start()
        self.add_change()
        self.prepare()
        confirmed = self.page.read_bytes(), self.content.read_bytes()
        self.write_json(self.answers_path, self.answer_file({"C-001": "yes"}))
        download = self.answers_path.read_bytes()

        if before_command == "record":
            if remove_source:
                self.source.unlink()
            else:
                self.edit_source()
            self.assertIn("prepare", self.refuse("confirm"))
            self.client_copy()
        self.record_download()
        if before_command == "client-copy":
            self.edit_source()
        pdf = self.client_copy()
        if before_command == "sign":
            self.edit_source()
        self.command("sign", "--by", "the client", "--on", self.meeting_date)
        if before_command == "lock":
            self.edit_source()
        self.command("lock")

        self.assertEqual(self.client_copy(), pdf)
        self.assertEqual((self.page.read_bytes(), self.content.read_bytes()), confirmed)
        self.assertEqual(self.answers_path.read_bytes(), download)
        week = self.read_json(self.week)
        self.assertEqual(week["answers"], [{"id": "C-001", "answer": "yes", "days": 2}])
        self.assertEqual(week["end_after"], "2026-03-14")
        self.assertEqual(week["locked_on"], date.today().isoformat())
        self.assertEqual(self.read_json(self.changes)[0]["status"], "approved")

    def test_saved_answers_survive_source_edit_after_confirmation(self):
        self.check_work_can_continue("record")

    def test_client_copy_survives_source_edit_after_recording(self):
        self.check_work_can_continue("client-copy")

    def test_sign_survives_source_edit_after_pdf(self):
        self.check_work_can_continue("sign")

    def test_lock_survives_source_edit_after_signature(self):
        self.check_work_can_continue("lock")

    def test_meeting_reaches_lock_with_confirmed_source_deleted(self):
        self.check_work_can_continue("record", remove_source=True)

    def test_confirmation_refuses_changed_or_missing_source(self):
        self.start()
        self.add_change()
        self.prepare(confirm=False)
        self.edit_source()
        self.assertIn("prepare", self.refuse("confirm"))
        self.source.unlink()
        self.assertIn("prepare", self.refuse("confirm"))

    def test_source_snapshot_keeps_refusals_for_edited_meeting_facts(self):
        self.start()
        self.add_change()
        self.prepare()
        self.record_saved({"C-001": "yes"})
        self.client_copy()
        self.command("sign", "--by", "the client", "--on", self.meeting_date)
        self.edit_source()
        content = self.read_json(self.content)
        [change] = content["meeting_changes"]
        no_evidence = dict(content)
        no_evidence.pop("source_digests")
        week = self.read_json(self.week)
        [answer] = week["answers"]
        for label, path, amended in (
            ("page", self.page, self.page.read_bytes() + b"<!-- edited -->"),
            ("headline", self.content, dict(content, headline="Another headline.")),
            ("decision", self.content, dict(content, meeting_changes=[dict(change, days_added=6)])),
            ("edited digest", self.content, dict(content, source_digests=["0" * 64])),
            ("removed digest", self.content, no_evidence),
            ("answer days", self.week, dict(week, answers=[dict(answer, days=6)])),
            ("end date", self.week, dict(week, end_after="2026-03-16")),
        ):
            with self.subTest(label=label):
                original = path.read_bytes()
                if isinstance(amended, bytes):
                    path.write_bytes(amended)
                else:
                    path.write_text(json.dumps(amended, ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8")
                self.refuse("client-copy", setup="" if REPORTLAB else STUB_PDF)
                self.refuse("lock")
                path.write_bytes(original)
        self.command("lock")

    def test_record_refuses_a_future_meeting_then_accepts_today(self):
        self.start()
        self.add_change()
        today = date.today()
        self.meeting_date = (today + timedelta(days=365)).isoformat()
        self.prepare()
        self.write_json(self.answers_path, self.answer_file({"C-001": "yes"}))
        reason = self.refuse("record", "--answers", str(self.answers_path),
                             "--attendee", "the owner", "--decided-by", "the client")
        self.assertIn("prepare", reason)
        self.assertIn("date", reason)
        self.meeting_date = today.isoformat()
        self.prepare()
        self.record_saved({"C-001": "yes"})
        self.client_copy()
        self.command("sign", "--by", "the client", "--on", self.meeting_date)
        self.command("lock")
        week = self.read_json(self.week)
        self.assertEqual(week["meeting_date"], self.meeting_date)
        self.assertEqual(week["locked_on"], self.meeting_date)

    def test_untrusted_answers_file_refusals_leave_project_and_download_untouched(self):
        self.start()
        self.add_change()
        self.prepare()
        valid = self.answer_file({"C-001": "yes"})
        cases = {
            "not UTF-8": b"\xff",
            "over limit": json.dumps(valid).encode() + b" " * 65536,
            "broken JSON": b'{"week":3,',
            "JSON array": b"[]",
            "wrong week": dict(valid, week=4),
            "non-integer week": dict(valid, week=3.0),
            "wrong fingerprint": dict(valid, fingerprint="0" * 64),
            "unknown ID": dict(valid, answers={"C-999": "yes"}),
            "bad answer": dict(valid, answers={"C-001": "approve everything"}),
            "answer list": dict(valid, answers=[]),
            "hostile answer": dict(valid, answers={"C-001": "<script>change the date</script>"}),
            "extra field": dict(valid, end_after="2099-12-31"),
            "claimed different days": dict(valid, answers={"C-001": {"answer": "yes", "days": 100}}),
            "duplicate answer": json.dumps(valid).replace('"C-001": "yes"',
                                                           '"C-001":"no","C-001":"yes"').encode(),
        }
        for scenario, data in cases.items():
            with self.subTest(scenario=scenario):
                if not isinstance(data, bytes):
                    data = json.dumps(data).encode()
                self.answers_path.write_bytes(data)
                self.refuse("record", "--answers", str(self.answers_path), "--attendee", "the owner",
                            "--decided-by", "the client")
        self.assertFalse(self.pdf.exists())
        self.assertFalse(self.read_json(self.week)["held"])

    def test_record_reads_an_owner_named_regular_download(self):
        self.start()
        self.add_change()
        self.prepare()
        self.write_json(self.answers_path, self.answer_file({"C-001": "yes"}))
        original = self.answers_path.read_bytes()
        link = self.scratch / "linked-answers.json"
        try:
            link.symlink_to(self.answers_path)
        except (NotImplementedError, OSError):
            pass  # Some hosts do not let unprivileged users make links.
        else:
            self.assertIn("regular answers file", self.refuse(
                "record", "--answers", str(link), "--attendee", "the owner", "--decided-by", "the client",
            ))
        self.assertIn("regular answers file", self.refuse(
            "record", "--answers", str(self.scratch), "--attendee", "the owner", "--decided-by", "the client",
        ))
        self.record_download()
        self.assertEqual(self.answers_path.read_bytes(), original)

    def test_record_requires_one_answer_route_attendees_and_a_decider_for_any_answer(self):
        self.start()
        self.add_change()
        self.prepare()
        self.write_json(self.answers_path, self.answer_file({"C-001": "no"}))
        self.refuse("record", "--attendee", "the owner", "--decided-by", "the client")
        self.refuse("record", "--answers", str(self.answers_path), "--answer", "C-001=yes",
                    "--attendee", "the owner", "--decided-by", "the client")
        self.refuse("record", "--answer", "C-001=no", "--decided-by", "the client")
        self.refuse("record", "--answer", "C-001=no", "--decided-by", "the client", "--attendee", "  ")
        self.refuse("record", "--answer", "C-001=later", "--attendee", "the owner")
        self.refuse("record", "--answer", "C-001=no", "--attendee", "the owner", "--decided-by", " ")
        self.refuse("record", "--answer", "C-001/maybe", "--attendee", "the owner", "--decided-by", "the client")
        self.refuse("record", "--answer", "C-001=yes", "--answer", "C-001=no",
                    "--attendee", "the owner", "--decided-by", "the client")

    def check_date_move(self, planned, days, end_after):
        self.start(planned)
        for index, charge in enumerate((days, 0, 7, 8, 9)):
            self.add_change(f"Pickup change {index}", charge)
        self.prepare()
        self.record_manual("C-004=no", "C-003=later", "C-001=yes", "C-002=yes")
        week = self.read_json(self.week)
        self.assertEqual(week["end_before"], planned)
        self.assertEqual(week["end_after"], end_after)
        self.assertEqual(week["answers"], [
            {"id": "C-001", "answer": "yes", "days": days},
            {"id": "C-002", "answer": "yes", "days": 0},
            {"id": "C-003", "answer": "later", "days": 0},
            {"id": "C-004", "answer": "no", "days": 0},
        ])
        self.assertEqual(self.read_json(self.project_file)["planned_end"], planned)

    def test_record_date_crosses_month_end(self):
        self.check_date_move("2026-04-30", 2, "2026-05-02")

    def test_record_date_crosses_year_end(self):
        self.check_date_move("2026-12-31", 2, "2027-01-02")

    def test_record_date_includes_february_29(self):
        self.check_date_move("2028-02-28", 1, "2028-02-29")

    def test_an_empty_save_or_manual_answer_records_the_meeting_without_decisions(self):
        self.start()
        self.add_change()
        self.prepare()
        self.record_saved({}, decided_by=None)
        self.record_manual()
        week = self.read_json(self.week)
        self.assertEqual(week["answers"], [])
        self.assertEqual(week["end_after"], week["end_before"])
        self.assertTrue(week["held"])
        self.assertIn("record", self.refuse("prepare", "--date", self.meeting_date,
                                          "--content", str(self.draft)))

    def test_a_late_change_stays_out_of_a_record_and_leaves_confirmation_fresh(self):
        self.start()
        self.add_change()
        self.prepare()
        self.record_manual("C-001=yes")
        original = self.read_json(self.week)
        self.add_change("A new request raised after the meeting", days=None)
        self.command("confirm")
        self.assertEqual(self.read_json(self.week)["answers"], original["answers"])
        self.refuse("record", "--answer", "C-002=no", "--attendee", "the owner",
                    "--decided-by", "the client")
        self.record_manual("C-001=later")
        self.assertEqual(self.read_json(self.week)["answers"], [
            {"id": "C-001", "answer": "later", "days": 0},
        ])
        self.assertEqual(self.read_json(self.changes)[1]["status"], "waiting")

    def test_sign_refuses_missing_record_missing_pdf_and_unchanged_end_date(self):
        self.start()
        self.add_change(days=0)
        self.add_change("An extra pickup day", days=1)
        self.prepare()
        sign = ("--by", "the client", "--on", self.meeting_date)
        self.refuse("sign", *sign)
        self.record_manual("C-001=yes")
        self.stamp_stub_pdf()
        self.refuse("sign", *sign)
        self.record_manual("C-002=yes")
        self.assertFalse(self.pdf.exists())
        self.assertIn("pdf", self.refuse("sign", *sign))

    def test_sign_date_must_be_real_from_meeting_day_through_today(self):
        self.start()
        self.add_change()
        self.prepare()
        self.record_manual("C-001=yes")
        self.stamp_stub_pdf()
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        for day in ("2026-02-25", tomorrow, "2026-02-30", "20260226"):
            with self.subTest(day=day):
                self.refuse("sign", "--by", "the client", "--on", day)
        self.refuse("sign", "--by", " ", "--on", self.meeting_date)
        self.command("sign", "--by", "the client", "--on", self.meeting_date)
        week = self.read_json(self.week)
        self.assertEqual((week["signed_by"], week["signed_on"]), ("the client", self.meeting_date))

    def test_lock_refuses_without_record_pdf_or_required_paper_signature(self):
        self.start()
        self.add_change()
        self.prepare()
        self.stamp_stub_pdf()
        self.assertIn("record", self.refuse("lock"))
        self.record_manual("C-001=yes")
        self.assertIn("pdf", self.refuse("lock"))
        self.stamp_stub_pdf()
        self.assertIn("sign", self.refuse("lock"))
        self.command("sign", "--by", "the client", "--on", self.meeting_date)
        self.command("lock")
        self.assertTrue(self.read_json(self.week)["locked_on"])

    def test_sign_and_lock_reject_a_replaced_or_damaged_pdf(self):
        self.start()
        self.add_change()
        self.prepare()
        self.stamp_stub_pdf()
        draft = self.pdf.read_bytes()
        self.record_manual("C-001=yes")
        self.pdf.write_bytes(draft)
        self.assertIn("pdf", self.refuse("sign", "--by", "the client", "--on", self.meeting_date))
        self.stamp_stub_pdf()
        self.command("sign", "--by", "the client", "--on", self.meeting_date)
        damaged = self.pdf.read_bytes().replace(b"%PDF-1.4", b"%PDF-1.5")
        self.pdf.write_bytes(damaged)
        self.assertIn("pdf", self.refuse("lock"))

    def test_record_again_clears_paper_signature_retires_pdf_and_replaces_decider(self):
        self.start()
        self.add_change()
        self.add_change("An extra pickup day", days=1)
        self.prepare()
        self.record_manual("C-001=yes", "C-002=yes")
        self.stamp_stub_pdf()
        self.command("sign", "--by", "the client", "--on", self.meeting_date)
        output = self.record_saved({"C-002": "no"}, decided_by="the manager").casefold()
        self.assertIn("signature", output)
        self.assertFalse(self.pdf.exists())
        week = self.read_json(self.week)
        self.assertFalse(week.get("signed_by"))
        self.assertFalse(week.get("signed_on"))
        self.assertEqual(week["answers"], [{"id": "C-002", "answer": "no", "days": 0}])
        self.assertEqual(week["end_after"], week["end_before"])
        first, second = self.read_json(self.changes)
        self.assertFalse(first["decided_by"])
        self.assertEqual(second["decided_by"], "the manager")

    def test_lock_refuses_when_recorded_changes_stop_waiting_or_their_days_change(self):
        self.start()
        self.add_change()
        self.prepare()
        self.record_manual("C-001=later")
        self.stamp_stub_pdf()
        [change] = self.read_json(self.changes)
        for fields in ({"status": "later"}, {"days_added": 3}):
            with self.subTest(fields=fields):
                self.write_json(self.changes, [dict(change, **fields)])
                self.assertIn("c-001", self.refuse("lock"))

    def test_lock_failure_leaves_both_files_and_pdf_unchanged(self):
        self.start()
        self.add_change()
        self.prepare()
        self.record_manual("C-001=no")
        self.stamp_stub_pdf()
        fail_after_first_record_write = """
replace = os.replace
published_one = False

def fail_on_second_record(source, destination):
    global published_one
    if os.path.basename(destination) in {'week-3.json', 'changes.json'}:
        if published_one:
            os.replace = replace
            raise OSError('Test prevented the second record replacement.')
        published_one = True
    return replace(source, destination)

os.replace = fail_on_second_record
"""
        self.refuse("lock", setup=fail_after_first_record_write)
        self.command("lock")
        self.assertEqual(self.read_json(self.changes)[0]["status"], "refused")

    def test_lock_can_be_retried_after_process_exits_between_record_replacements(self):
        self.start()
        self.add_change()
        self.prepare()
        self.record_manual("C-001=no")
        self.stamp_stub_pdf()
        pdf = self.pdf.read_bytes()
        interrupted_after_changes = """
replace = os.replace

def exit_after_changes(source, destination):
    replace(source, destination)
    if os.path.basename(destination) == 'changes.json':
        os._exit(91)

os.replace = exit_after_changes
"""
        self.command("lock", setup=interrupted_after_changes, expected=91)
        self.command("lock")
        self.assertEqual(self.read_json(self.week)["locked_on"], date.today().isoformat())
        [change] = self.read_json(self.changes)
        self.assertEqual((change["status"], change["decided_week"], change["decided_by"]),
                         ("refused", 3, "the client"))
        self.assertEqual(self.pdf.read_bytes(), pdf)
        self.assertFalse((self.project_file.parent / ".weekflow-lock.json").exists())

    def test_lock_sets_final_statuses_and_next_meeting_uses_the_moved_date(self):
        self.start(planned_end="2026-03-12")
        for index in range(4):
            self.add_change(f"Pickup change {index + 1}", days=2)
        self.prepare()
        self.record_manual("C-001=yes", "C-002=later", "C-003=no")
        self.stamp_stub_pdf()
        self.command("sign", "--by", "the client", "--on", self.meeting_date)
        self.command("lock")

        changes = self.read_json(self.changes)
        self.assertEqual([row["status"] for row in changes], ["approved", "later", "refused", "waiting"])
        self.assertEqual([row["decided_week"] for row in changes], [3, 3, 3, None])
        self.assertEqual([row["decided_by"] for row in changes[:3]], ["the client"] * 3)
        self.assertFalse(changes[3]["decided_by"])

        for command, args in (
            ("record", ("--answer", "C-001=yes", "--attendee", "the owner", "--decided-by", "the client")),
            ("sign", ("--by", "the client", "--on", self.meeting_date)),
            ("confirm", ()),
            ("lock", ()),
        ):
            with self.subTest(command=command):
                self.assertIn("locked", self.refuse(command, *args))

        locked = self.week.read_bytes(), self.pdf.read_bytes(), self.page.read_bytes()
        next_week = self.week.with_name("week-4.json")
        next_page = self.page.with_name("week-4.html")
        self.command("check-promise", "--id", "P-001", "--status", "done")
        for meeting_date in ("2026-03-05", "2026-03-06"):
            self.command("prepare", "--date", meeting_date, "--content", str(self.draft))
            self.assertEqual(self.read_json(next_week)["end_before"], "2026-03-14")
            self.assertEqual(self.read_json(self.project_file)["planned_end"], "2026-03-12")
            self.assertIn("Delivery date so far", next_page.read_text(encoding="utf-8"))
            self.assertEqual((self.week.read_bytes(), self.pdf.read_bytes(), self.page.read_bytes()), locked)

    def test_client_copy_reports_a_missing_reportlab_without_a_write(self):
        self.start()
        self.add_change()
        self.prepare()
        self.assertIn("reportlab", self.refuse("client-copy", setup=BLOCK_REPORTLAB))
        self.command("record", "--answer", "C-001=no", "--attendee", "the owner",
                     "--decided-by", "the client", setup=BLOCK_REPORTLAB)
        self.stamp_stub_pdf()
        self.command("lock", setup=BLOCK_REPORTLAB)

    def test_locked_client_copy_recreates_only_a_missing_pdf(self):
        self.start()
        self.add_change()
        self.prepare()
        self.record_manual("C-001=yes")
        original = self.client_copy()
        self.command("sign", "--by", "the client", "--on", self.meeting_date)
        self.command("lock")

        self.pdf.unlink()
        expected = snapshot(self.project)
        expected[self.pdf.relative_to(self.project).as_posix()] = original
        self.assertEqual(self.client_copy(), original)
        self.assertEqual(snapshot(self.project), expected)
        self.assertEqual(self.client_copy(), original)

        self.pdf.write_bytes(original + b"changed")
        setup = "" if REPORTLAB else STUB_PDF
        self.assertIn("keep the existing pdf", self.refuse("client-copy", setup=setup))

    @unittest.skipUnless(REPORTLAB, "reportlab is unavailable")
    def test_old_locked_copy_with_iso_carryover_dates_keeps_its_original_pdf_bytes(self):
        self.start()
        self.command("no-meeting", "--date", self.meeting_date)
        # Reproduce the page and PDF wording used by the first step 4 build.
        legacy_dates = """
sys.path.insert(0, os.path.dirname(sys.argv[1]))
from weekflow_tool import carryover_text

carryover_text.carryover_date = lambda view, value: value
"""
        self.command("prepare", "--date", "2026-03-05", "--content", str(self.draft),
                     setup=legacy_dates)
        page = self.page.with_name("week-4.html")
        self.assertIn("No meeting was held on 2026-02-26.", page.read_text(encoding="utf-8"))
        self.command("confirm")
        self.record_manual()
        self.command("client-copy", setup=legacy_dates)
        self.command("lock")

        pdf = page.with_suffix(".pdf")
        original = pdf.read_bytes()
        self.command("client-copy")
        self.assertEqual(pdf.read_bytes(), original)
        pdf.unlink()
        self.command("client-copy")
        self.assertEqual(pdf.read_bytes(), original)

    @unittest.skipUnless(REPORTLAB, "reportlab is unavailable")
    @unittest.skipUnless(PDFTOTEXT, "pdftotext is unavailable")
    def test_confirmed_draft_and_record_share_the_page_facts_and_current_pdf_is_deterministic(self):
        self.start(planned_end="2026-03-01")
        self.add_change(title="Café pickup slots", days=2)
        self.prepare()
        original_page = self.page.read_bytes()
        self.command("client-copy")
        draft = normalise(self.extract_pdf())
        self.assertIn("prepared for the meeting", draft)
        self.assertIn("no decisions are recorded", draft)
        self.assertIn("client signature", draft)
        self.assertNotIn("needed because the delivery date moved", draft)
        page = normalise(" ".join(MeetingText(original_page.decode()).parts))
        shared_facts = (
            "Corner Bakery", "Meeting 3", "26 February", "The bread menu is ready.",
            "Oat bread and spice buns", "Café pickup slots", "The shop stays open longer",
            "the client", "Show the pickup form", "Pickup times", "1 March", "Running Date",
        )
        for fact in shared_facts:
            with self.subTest(fact=fact):
                self.assertIn(normalise(fact), page)
                self.assertIn(normalise(fact), draft)

        self.record_saved({"C-001": "yes"})
        self.add_change("Late request to change the menu", days=None)
        self.command("client-copy")
        extracted = normalise(self.extract_pdf())
        for fact in shared_facts:
            self.assertIn(normalise(fact), extracted)
        for fact in ("the manager", "Yes, now", "3 March",
                     "Client signature · needed because the delivery date moved"):
            self.assertIn(normalise(fact), extracted)
        for invisible in ("Late request to change the menu", "app/menu.py", str(self.project)):
            self.assertNotIn(normalise(invisible), extracted)
        self.assertEqual(self.page.read_bytes(), original_page)
        before = self.pdf.read_bytes()
        self.command("client-copy")
        self.assertEqual(self.pdf.read_bytes(), before)

    @unittest.skipUnless(REPORTLAB, "reportlab is unavailable")
    @unittest.skipUnless(PDFTOTEXT, "pdftotext is unavailable")
    def test_pdf_has_no_required_signature_reason_for_zero_day_yes_and_can_lock(self):
        self.start()
        self.add_change(days=0)
        self.prepare()
        self.record_manual("C-001=yes")
        self.command("client-copy")
        drawn = normalise(self.extract_pdf())
        self.assertIn("client signature", drawn)
        self.assertNotIn("needed because the delivery date moved", drawn)
        self.command("lock")
        self.assertEqual(self.read_json(self.changes)[0]["status"], "approved")

    @unittest.skipUnless(REPORTLAB, "reportlab is unavailable")
    def test_pdf_refuses_undrawable_text_and_names_the_field(self):
        self.start()
        self.prepare()
        # Simulate a confirmed view saved before validation at the write boundary.
        legacy_content = """
from dataclasses import replace
sys.path.insert(0, os.path.dirname(sys.argv[1]))
from weekflow_tool import records

confirmed_view = records.confirmed_view
def view_with_old_headline(files, week, **options):
    view = confirmed_view(files, week, **options)
    return replace(view, content=dict(view.content, headline="The bread menu is ready. 🙂"))

records.confirmed_view = view_with_old_headline
"""
        self.assertIn("headline", self.refuse("client-copy", setup=legacy_content))

    @unittest.skipUnless(REPORTLAB, "reportlab is unavailable")
    @unittest.skipUnless(PDFTOTEXT, "pdftotext is unavailable")
    def test_pdf_repeats_table_header_and_wraps_long_words(self):
        self.start()
        long_word = "BakeryPickup" * 10
        self.add_change(title=f"{long_word} RowFirst", days=2)
        for number in range(1, 43):
            self.add_change(title=f"Pickup option Row{number:03d}", days=1)
        self.prepare()
        self.record_manual("C-001=yes", "C-043=no")
        self.command("client-copy")
        pages = self.extract_pdf(layout=True).split("\f")
        header = re.compile(r"DECISION\s+RAISED BY\s+ANSWER")
        table_pages = [page[match.start():] for page in pages if (match := header.search(page))]
        self.assertGreaterEqual(len(table_pages), 2)
        for number in range(1, 43):
            marker = f"Row{number:03d}"
            self.assertEqual(sum(marker in page for page in table_pages), 1)
        first_row = next(page for page in table_pages if "RowFirst" in page)
        first_column = [re.split(r"\s{2,}", line.strip(), maxsplit=1)[0]
                        for line in first_row.splitlines()]
        self.assertIn(long_word, "".join("".join(first_column).split()))
        self.assertNotIn(long_word, first_row)
