"""Run docs meetings on disposable projects through the public commands."""

import itertools
from importlib.util import find_spec
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock

from test_weekflow import FIXTURE, PDF_TEXT, TEST_PDF_RENDERER, TOOL, run_project_command, snapshot
from test_frozen_meeting_design import READY


FORM = """# Client meeting form: Corner Bakery

## Meetings held
| # | Date and place | Stage | Who came (name and job) | What was decided |
|---|---|---|---|---|
| 1 | 2026-08-01 | 1, 2 | the owner; the client | Orders are phoned in |
| 2 | 2026-08-08 | 3 | the owner; the client | Ask about pickup |

## Still open
| # | Question | Why open (missing or conflict) | Blocks the work? (yes or can wait) | Who answers | Raised in meeting |
|---|---|---|---|---|---|
| 1 | Who confirms pickup? | missing | can wait | the client | 2 |
| 2 | Where do orders wait? | conflict | can wait | the client | 2 |
| 3 | Who packs bread? | missing | can wait | the client | 2 |
"""

SOURCE = """## How orders run

The shop will **confirm** pickup.
Orders wait in a basket.
The client packs
the bread.
"""
DECISIONS = [
    {"id": "D-001", "question": "Who confirms pickup?", "why": "Pick one person.",
     "options": ["the client", "the manager"]},
    {"id": "D-002", "question": "Where do orders wait?", "why": "The accounts differ.",
     "said": [{"who": "the manager", "what": "Use the counter."}],
     "options": ["at the counter", "on the shelf"]},
    {"id": "D-003", "question": "Who packs bread?", "why": "Avoid missed orders.",
     "options": ["the client", "the owner"]},
]
DRAFT_PATH = "docs/weekly/pages/draft.json"


class DocsMeetingTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.scratch = Path(scratch.name)
        self.project = self.scratch / "bakery"
        shutil.copytree(FIXTURE, self.project)
        self.weekly = self.project / "docs/weekly"
        self.prd = self.project / "docs/prd.md"
        # Write bytes so Windows keeps LF line endings and the page fingerprint matches.
        self.prd.write_bytes(("# PRD: Corner Bakery\n> v1 · Draft\n\n" + SOURCE).encode("utf-8"))
        self.form = self.project / "docs/meeting-form.md"
        self.form.write_bytes(FORM.encode("utf-8"))
        self.draft = self.project / DRAFT_PATH
        self.page = self.weekly / "pages/week-3.html"
        self.project_row = self.weekly / "project.json"

    def invoke(self, name, *options, succeeds=True, setup=None):
        command = [sys.executable, str(TOOL)]
        if setup:
            command = [sys.executable, "-c", """
import os
import runpy
import sys
sys.path.insert(0, os.path.dirname(sys.argv[1]))
""" + setup + """
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name="__main__")
""", str(TOOL)]
        before = snapshot(self.project) if not succeeds else None
        result = run_project_command(
            command, name, self.project, *options,
            cwd=self.scratch, capture_output=True, text=True, encoding="utf-8", timeout=15,
        )
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0 if succeeds else 2, output)
        if not succeeds:
            self.assertEqual(snapshot(self.project), before, output)
        return output

    def start(self, *options):
        return self.invoke("start", "--meeting-day", "Saturday", "--language", "en", *options)

    def week(self, number=3):
        return self.read(self.weekly / f"weeks/week-{number}.json")

    @staticmethod
    def read(path):
        return json.loads(path.read_text(encoding="utf-8"))

    def write_draft(self, *, decisions=DECISIONS, **overrides):
        sentences = [
            {"text": text, "source": "docs/prd.md"} for text in (
                "The shop will confirm {D-001} pickup.",
                "Orders wait in a basket {D-002}.",
                "The client packs the bread {D-003}.",
            )
        ]
        if decisions != DECISIONS:
            ids = {decision["id"] for decision in decisions}
            sentences = [row for identifier, row in zip(DECISIONS, sentences) if identifier["id"] in ids]
        content = {"headline": "Pickup orders", "stage": 3, "decisions": decisions,
                   "document": [{"title": "How orders run", "sentences": sentences}] if sentences else [],
                   "next_week": [], "needs": []}
        self.draft.parent.mkdir(parents=True, exist_ok=True)
        self.draft.write_text(json.dumps(dict(content, **overrides)), encoding="utf-8")

    def prepare(self, when="2026-08-15", *, succeeds=True):
        return self.invoke("prepare", "--date", when, "--content", DRAFT_PATH, succeeds=succeeds)

    def record(self, *answers, succeeds=True):
        route = tuple(part for answer in answers for part in ("--answer", answer)) or ("--answer",)
        return self.invoke("record", *route, "--attendee", "the client", "--decided-by", "the client",
                           succeeds=succeeds)

    def close(self, *, real_pdf=False):
        self.invoke("client-copy", setup=None if real_pdf else TEST_PDF_RENDERER)
        self.invoke("lock")

    def approve(self, *, delivery=True):
        prd = self.prd.read_text(encoding="utf-8")
        prd = prd.replace("Draft", "Approved 2026-08-15 by the client")
        if delivery:
            prd += "\n- **Dates:** Delivery by 2026-12-18.\n"
        self.prd.write_text(prd, encoding="utf-8")

    def test_start_without_project_documents_takes_owner_name_once(self):
        shutil.rmtree(self.project / "docs")
        output = self.start("--project", "Corner Bakery")
        self.assertEqual(output.lower().count("project-docs"), 1)
        self.assertEqual(self.read(self.project_row)["project"], "Corner Bakery")
        self.write_draft(stage=1, decisions=[], document=[
            {"title": "Pickup", "sentences": [{"text": "The client wants pickup.", "source": "owner"}]},
        ])
        output = self.prepare()
        self.assertNotIn("project-docs", output.lower())
        self.assertIn("The client wants pickup.", (self.weekly / "pages/week-1.html").read_text())

    def test_confirm_checks_live_source_and_keeps_saved_answers_after_edits(self):
        self.start()
        self.write_draft()
        self.prepare()
        original = self.prd.read_bytes()
        self.prd.write_bytes(original + b"\nA later note.\n")
        self.invoke("confirm", succeeds=False)
        self.prd.write_bytes(original)
        self.invoke("confirm")
        html = self.page.read_text(encoding="utf-8")
        self.assertIn("Held in meeting 1", html)
        self.assertIn("We are here", html)
        fingerprint = re.search(r"\b[0-9a-f]{64}\b", html).group()
        download = self.scratch / "answers.json"
        download.write_text(json.dumps({"week": 3, "fingerprint": fingerprint,
                                        "answers": {"D-001": "the manager", "D-002": "later"}}))
        self.prd.write_bytes(original + b"\nA later note.\n")
        self.form.write_text(FORM + "| 4 | Who opens? | missing | can wait | the client | 3 |\n")
        outside = {path: data for path, data in snapshot(self.project).items()
                   if not path.startswith("docs/weekly")}
        setup_before = self.project_row.read_bytes()
        self.invoke("record", "--answers", str(download), "--attendee", "the client",
                    "--decided-by", "the client")
        week = self.week()
        self.assertEqual(week["answers"], [
            {"id": "D-001", "answer": "the manager", "days": 0, "decided_by": "the client"},
            {"id": "D-002", "answer": "later", "days": 0},
        ])
        self.assertEqual(week["decisions_left"], 2)
        self.assertTrue({"end_before", "end_after", "signed_on", "signed_by"}.isdisjoint(week))
        self.assertIn("sign", self.invoke("sign", "--by", "the client", "--on", "2026-08-15",
                                         succeeds=False).lower())
        self.close()
        self.assertEqual(setup_before, self.project_row.read_bytes())
        self.assertEqual(outside, {path: data for path, data in snapshot(self.project).items()
                                   if not path.startswith("docs/weekly")})
        self.assertFalse((self.weekly / "changes.json").exists())

    def test_record_recovers_page_fonts_after_the_docs_scope_is_approved(self):
        design = self.project / "DESIGN.md"
        design.write_text(READY, encoding="utf-8")
        live_fonts = self.project / "docs/fonts"
        shutil.copytree(TOOL.parent.parent / "assets/fonts", live_fonts)
        self.start()
        self.write_draft()
        self.prepare()
        self.invoke("confirm")
        markup = self.page.read_bytes()
        fingerprint = re.search(rb"<!-- Draft fingerprint: ([0-9a-f]{64}) -->", markup)[1].decode("ascii")
        download = self.scratch / "answers.json"
        download.write_text(json.dumps({"week": 3, "fingerprint": fingerprint,
                                        "answers": {"D-001": "the manager"}}), encoding="utf-8")
        self.approve()
        frozen_fonts = self.page.parent / "fonts"
        frozen_fonts.rename(self.scratch / "lost-frozen")
        live_fonts.rename(self.scratch / "lost-live")
        design.unlink()

        self.invoke("record", "--answers", str(download), "--attendee", "the client",
                    "--decided-by", "the client")

        self.assertTrue(self.week()["held"])
        self.assertEqual(self.week()["answers"][0]["answer"], "the manager")
        self.assertEqual(self.page.read_bytes(), markup)
        self.assertEqual(snapshot(frozen_fonts), snapshot(self.scratch / "lost-frozen"))
        self.close()
        self.invoke("enter-build")
        self.assertEqual(self.read(self.project_row)["mode"], "build")

    def test_rejects_unknown_answer_and_tampered_record(self):
        self.start()
        self.write_draft()
        self.prepare()
        self.invoke("confirm")
        self.record("D-001=Approve the scope", succeeds=False)
        self.record("D-004=the client", succeeds=False)
        self.record("D-001=the client")
        week = self.week()
        record_path = self.weekly / "weeks/week-3.json"
        for edited in (dict(week, decisions_left=0), dict(week, end_after="2026-10-03"),
                       dict(week, answers=[{"id": "D-001", "answer": "invented", "days": 0}])):
            with self.subTest(edited=edited):
                record_path.write_text(json.dumps(edited), encoding="utf-8")
                self.invoke("client-copy", succeeds=False, setup=TEST_PDF_RENDERER)
        record_path.write_text(json.dumps(week), encoding="utf-8")
        self.close()

    def test_carries_open_decisions_promises_and_needs_across_missed_week(self):
        self.start()
        needs = [{"text": "Bring the price list.", "by": "2026-09-05"}]
        self.write_draft(needs=needs, next_week=[{"text": "Show the order list."}])
        self.prepare()
        self.invoke("confirm")
        self.record("D-001=the client", "D-002=later")
        self.close()
        self.invoke("correct", "--week", "3", "--what", "Pickup wording", "--reason", "Clearer",
                    "--by", "the owner")
        self.invoke("no-meeting", "--date", "2026-08-22")
        missed = self.week(4)
        self.assertEqual(missed["mode"], "docs")
        self.assertTrue({"end_before", "end_after"}.isdisjoint(missed))
        self.invoke("check-promise", "--id", "P-001", "--status", "done")
        self.write_draft(decisions=DECISIONS[1:])
        self.assertIn("Bring the price list", self.prepare("2026-08-29", succeeds=False))
        self.write_draft(decisions=DECISIONS[2:], needs=needs)
        self.assertIn("D-002", self.prepare("2026-08-29", succeeds=False))
        self.write_draft(decisions=DECISIONS[1:], needs=needs)
        self.prepare("2026-08-29")
        page = (self.weekly / "pages/week-5.html").read_text(encoding="utf-8")
        for text in ("22 August", "5 September", "Show the order list.", "Pickup wording"):
            self.assertIn(text, page)
        self.assertNotIn("D-001", page)

    def lock_first_with_open_questions(self):
        self.start()
        self.write_draft()
        self.prepare()
        self.invoke("confirm")
        self.record("D-001=the client", "D-002=later")
        self.close()

    def test_settled_and_reworded_questions_stay_in_the_next_locked_meeting(self):
        self.lock_first_with_open_questions()
        original = self.week()
        settled = DECISIONS[1]["question"]
        reworded = DECISIONS[2]["question"]
        replacement = dict(DECISIONS[2], question="Who packs today's bread?")
        self.form.write_text(
            "\n".join(line for line in FORM.splitlines() if settled not in line)
            .replace(reworded, replacement["question"]) + "\n", encoding="utf-8",
        )
        self.write_draft(decisions=[replacement])
        self.assertIn(settled, self.prepare("2026-08-22", succeeds=False))
        self.write_draft(decisions=[replacement], settled=[settled, reworded.lower()])
        self.assertIn(reworded.lower(), self.prepare("2026-08-22", succeeds=False))
        self.write_draft(decisions=[replacement], settled=[settled, reworded])
        self.prepare("2026-08-22")
        content = self.read(self.weekly / "pages/week-4-content.json")
        self.assertEqual(content["settled"], [settled, reworded])
        page = (self.weekly / "pages/week-4.html").read_text(encoding="utf-8")
        for phrase in ("Settled outside the meeting", settled, reworded):
            self.assertIn(phrase, page)
        self.invoke("confirm")
        self.record("D-003=the owner")
        self.close(real_pdf=bool(PDF_TEXT))
        self.assertEqual(self.week(), original)
        current = self.week(4)
        self.assertTrue(current["locked_on"])
        self.assertEqual(current["decisions_left"], 0)
        if PDF_TEXT:
            pdf = self.weekly / "pages/week-4.pdf"
            flat = " ".join(subprocess.check_output(["pdftotext", "-enc", "UTF-8", str(pdf), "-"],
                                                    text=True, encoding="utf-8").split())
            for phrase in ("All decided", "Settled outside the meeting", settled, reworded):
                self.assertIn(phrase, flat)
        self.write_draft(decisions=[])
        self.prepare("2026-08-29")

    def test_prepare_continues_from_live_form_after_pages_are_lost(self):
        self.lock_first_with_open_questions()
        original = self.week()
        self.draft.parent.rename(self.scratch / "unavailable-pages")
        self.write_draft(decisions=DECISIONS[1:])
        warning = "The last meeting's open decisions could not be read."
        output = self.prepare("2026-08-22")
        self.assertEqual(output.count(warning), 1)
        self.assertIn("Ask the owner", output)
        self.assertNotIn(warning, self.prepare("2026-08-22"))
        self.invoke("confirm")
        self.record()
        self.close()
        self.assertEqual(self.week(), original)
        current = self.week(4)
        self.assertTrue(current["locked_on"])
        self.assertEqual(current["decisions_left"], 2)

    def test_enter_build_reports_open_decisions_after_a_missed_week(self):
        self.lock_first_with_open_questions()
        self.invoke("no-meeting", "--date", "2026-08-22")
        self.approve()
        output = self.invoke("enter-build")
        for decision in DECISIONS[1:]:
            self.assertEqual(output.count(decision["question"]), 1)
        self.assertNotIn(DECISIONS[0]["question"], output)
        self.assertEqual(self.read(self.project_row)["mode"], "build")

    def test_enter_build_reports_unavailable_open_decisions_without_blocking(self):
        self.lock_first_with_open_questions()
        self.draft.parent.rename(self.scratch / "unavailable-pages")
        self.approve()
        output = self.invoke("enter-build")
        self.assertEqual(output.count("The last meeting's open decisions could not be read."), 1)
        self.assertEqual(self.read(self.project_row)["mode"], "build")

    def test_enter_build_tells_how_to_finish_an_unrecorded_draft(self):
        self.start()
        self.write_draft()
        self.prepare()
        self.approve()
        output = self.invoke("enter-build", succeeds=False).lower()
        for phrase in ("record", "lock", "no-meeting"):
            self.assertIn(phrase, output)
        self.invoke("no-meeting", "--date", "2026-08-15")
        self.assertFalse(self.week()["held"])
        self.invoke("enter-build")

    def test_reprepares_the_same_unconfirmed_docs_meeting_after_prd_approval(self):
        self.start()
        self.write_draft()
        self.prepare()
        initial_setup = self.project_row.read_bytes()
        self.approve()
        approved_prd = self.prd.read_bytes()
        self.assertIn("record", self.invoke("enter-build", succeeds=False).lower())
        refusal = self.invoke("confirm", succeeds=False)
        self.assertIn("document files changed after preparation", refusal)
        self.assertIn("Prepare the meeting again", refusal)
        self.prepare()
        self.assertIn("2026-08-15", self.prepare("2026-08-22", succeeds=False))
        self.assertEqual((self.week()["mode"], self.week()["meeting_date"]), ("docs", "2026-08-15"))
        self.record("D-001=the client", succeeds=False)
        self.invoke("confirm")
        self.record("D-001=the client", "D-002=later")
        self.assertTrue(self.week()["held"])
        self.assertNotIn("end_before", self.week())
        self.assertNotIn("end_after", self.week())
        self.assertIn("Lock week 3", self.invoke("enter-build", succeeds=False))
        self.close(real_pdf=bool(PDF_TEXT))
        self.assertTrue(self.week()["locked_on"])
        self.assertEqual(self.project_row.read_bytes(), initial_setup)
        self.assertIn("enter-build", self.prepare("2026-08-22", succeeds=False))
        output = self.invoke("enter-build")
        self.assertIn(DECISIONS[1]["question"], output)
        self.assertEqual(self.prd.read_bytes(), approved_prd)
        project = self.read(self.project_row)
        self.assertEqual((project["mode"], project["scope_approved_on"], project["planned_end"]),
                         ("build", "2026-08-15", "2026-12-18"))

    def test_enter_build_requires_latest_week_locked_and_keeps_historical_copy(self):
        self.start()
        need = {"text": "Bring price list."}
        self.write_draft(needs=[need], next_week=[{"text": "Show the draft."}])
        self.prepare()
        self.invoke("enter-build", succeeds=False)
        self.invoke("confirm")
        self.approve(delivery=False)
        self.assertIn("enter-build", self.prepare(succeeds=False))
        self.assertIn("lock", self.invoke("enter-build", "--planned-end", "2026-12-18",
                                         succeeds=False).lower())
        self.record("D-001=the client")
        self.close()
        previous_week = self.week()
        self.assertIn("planned", self.invoke("enter-build", succeeds=False).lower())
        self.invoke("enter-build", "--planned-end", "2026-12-18")
        self.invoke("correct-date", "--planned-end", "2026-12-22")
        # Reopen the same historical docs record with changed live project setup.
        pdf = (self.weekly / "pages/week-3.pdf").read_bytes()
        self.invoke("client-copy", setup=TEST_PDF_RENDERER)
        self.assertEqual((self.weekly / "pages/week-3.pdf").read_bytes(), pdf)
        self.assertEqual(self.week(), previous_week)
        self.invoke("check-promise", "--id", "P-001", "--status", "done")
        self.write_draft(stage=3, decisions=[], finished=[])
        self.assertIn("Bring price list", self.prepare("2026-08-22", succeeds=False))
        self.write_draft(stage=3, decisions=[], finished=[], needs=[need])
        self.prepare("2026-08-22")
        first_build = self.week(4)
        self.assertEqual((first_build["mode"], first_build["end_before"]), ("build", "2026-12-22"))
        self.invoke("correct-date", "--planned-end", "2026-12-24", succeeds=False)

    def test_enter_build_reads_prd_line_and_warns_once_if_scope_returns_to_draft(self):
        self.start()
        self.approve()
        self.write_draft()
        self.assertIn("enter-build", self.prepare(succeeds=False))
        output = self.invoke("enter-build")
        for phrase in ("2026-08-15", "2026-12-18", "docs/prd.md:", "Delivery by"):
            self.assertIn(phrase, output)
        self.prd.write_text(self.prd.read_text().replace("Approved 2026-08-15 by the client", "Draft"))
        self.write_draft(decisions=[], finished=[])
        self.assertIn("draft", self.prepare().lower())
        self.assertNotIn("scope document is a draft", self.prepare().lower())
        self.assertEqual((self.week()["mode"], self.week()["end_before"]), ("build", "2026-12-18"))

    def test_stop_in_form_refuses_prepare_and_enter_build(self):
        self.start()
        self.form.write_text(FORM + """
## Stage 4: approve the scope, or stop
### 10. The decision
| Decision | ✓ |
|---|---|
| Approved | |
| Stop (why, below) | ✓ |
""", encoding="utf-8")
        self.write_draft(stage=4)
        self.assertIn("stopp", self.prepare(succeeds=False).lower())
        self.approve()
        self.assertIn("stopp", self.invoke("enter-build", succeeds=False).lower())

    def test_remove_name_rebuilds_docs_week_and_preserves_chosen_option(self):
        self.start()
        self.write_draft(headline="The manager will review pickup.")
        self.prepare()
        self.invoke("confirm")
        self.record("D-001=the manager")
        self.close()
        self.invoke("remove-name", "--name", "the manager", "--what", "Personal detail",
                    "--reason", "A correction made after the owner approved the project",
                    "--by", "the owner", setup=TEST_PDF_RENDERER)
        week = self.week()
        self.assertEqual(week["decisions_left"], 2)
        self.assertIn("A correction made", week["answers"][0]["answer"])
        self.assertNotIn("the manager", self.page.read_text(encoding="utf-8").lower())
        self.invoke("client-copy", setup=TEST_PDF_RENDERER)

    @unittest.skipUnless(PDF_TEXT, "ReportLab and pdftotext are required for PDF text checks.")
    def test_pdf_uses_selected_sentences_decisions_and_real_dates(self):
        self.start()
        self.invoke("no-meeting", "--date", "2026-08-15")
        self.invoke("correct", "--week", "3", "--what", "Pickup wording", "--reason", "Clearer",
                    "--by", "the owner")
        self.write_draft(needs=[{"text": "Bring the price list.", "by": "2026-09-05"}])
        self.prepare("2026-08-22")
        self.invoke("confirm")
        self.record("D-001=the manager", "D-002=later")
        self.close(real_pdf=True)
        text = subprocess.check_output(["pdftotext", "-enc", "UTF-8", str(self.weekly / "pages/week-4.pdf"), "-"],
                                       text=True, encoding="utf-8")
        flat = " ".join(text.split())
        for phrase in ("22 August", "5 September", "No meeting was held on 15 August",
                       "Correction for week 3 on", "Held in meeting 1", "Decide next week",
                       "The shop will confirm the manager pickup.", "Left to decide: 2",
                       "The goal", "The people and today's work", "The needs and the new way",
                       "The scope decision", "We are here", "The accounts differ.",
                       "Use the counter.", "at the counter", "on the shelf",
                       "This record does not approve the scope.", "No items are planned for next week."):
            self.assertIn(phrase, flat)
        for phrase in ("Days", "On time", "Planned delivery date", "Signature"):
            self.assertNotIn(phrase, flat)

    @unittest.skipUnless(find_spec("reportlab"), "ReportLab is required for the PDF page count.")
    def test_standard_docs_week_keeps_agenda_and_table_on_one_page(self):
        self.start()
        self.write_draft(
            headline="How the bakery will confirm pickup orders",
            next_week=[{"text": "Review the pickup instructions together."}],
            needs=[{"text": "Opening hours for weekend pickup.", "by": "2026-08-20"}],
        )
        self.prepare()
        self.invoke("confirm")
        self.record("D-001=the manager", "D-002=later")
        self.close(real_pdf=True)
        pdf = self.page.with_suffix(".pdf").read_bytes()
        self.assertEqual(len(re.findall(rb"/Type /Page\b", pdf)), 1)


class DocsTotalsTests(unittest.TestCase):
    @unittest.skipUnless(find_spec("reportlab"), "ReportLab is required for stage geometry checks.")
    def test_pdf_stage_markers_mirror_and_fill_the_current_stage(self):
        scripts = str(TOOL.parent)
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        from weekflow_tool.docs_pdf_c import StageLine
        from weekflow_tool.docs_presentation import stage_steps
        from weekflow_tool.meeting_design import studio_design

        stage = {"stage": 3, "stage_meetings": {"1": 1, "2": 2}}
        width = 420
        positions = []
        for language in ("en", "ar"):
            design = studio_design(language)
            track = StageLine(tuple(stage_steps(stage, language)), design, rtl=language == "ar")
            track.canv = Mock()
            track.wrap(width, 100)
            track.draw()
            dots = [call.args[0] for call in track.canv.circle.call_args_list]
            self.assertEqual(len(dots), 4)
            self.assertTrue(all(0 < x < width for x in dots))
            x1, _, x2, _ = track.canv.line.call_args.args
            self.assertEqual([x1, x2], [dots[0], dots[-1]])
            fills = [call.args[0] for call in track.canv.setFillColor.call_args_list]
            self.assertEqual(fills, [design.colors[name] for name in ("card", "card", "main", "card")])
            positions.append(dots)
        self.assertEqual(positions[1], [width - x for x in positions[0]])

    def test_every_answer_combination_keeps_deferrals_open(self):
        scripts = str(TOOL.parent)
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        from weekflow_tool.page import MeetingView

        view = MeetingView({}, {"mode": "docs"}, {"decisions": DECISIONS}, [], [])
        variants = [(None, "later", *decision["options"]) for decision in DECISIONS]
        for answers in itertools.product(*variants):
            with self.subTest(answers=answers):
                chosen = dict(zip((row["id"] for row in DECISIONS), answers))
                remaining = len(DECISIONS)
                for index, (_, answer, total) in enumerate(view.running_docs_decisions(chosen)):
                    self.assertEqual(answer, answers[index])
                    remaining -= answer not in (None, "later")
                    self.assertEqual(total, remaining)
