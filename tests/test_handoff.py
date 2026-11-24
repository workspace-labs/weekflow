"""Exercise the read-only handoff CLI on copies of the bakery."""

from base64 import b64encode
import json
import unittest

import test_weekflow as fixture
from test_arabic_documents import FORM as ARABIC_FORM, PRD as ARABIC_PRD
from test_docs_meetings import DECISIONS, FORM, SOURCE
from test_name_removal import STUB_REMOVAL_PDF


START = "2026-08-01"
PLANNED = "2027-03-12"
AGREED = "2027-03-14"
MILESTONE_FIELDS = {"id", "kind", "date", "source", "confirmed"}
EVENT_FIELDS = MILESTONE_FIELDS | {"what", "reason", "days_added"}


class HandoffTests(unittest.TestCase):
    setUp = fixture.WeekflowTests.setUp
    command = fixture.WeekflowTests.command
    succeed = fixture.WeekflowTests.succeed
    write_content = fixture.WeekflowTests.write_content
    read_json = fixture.WeekflowTests.read_json

    def write_json(self, relative, data):
        path = self.weekly / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def close_meeting(self, when, *answers, signer=None, person="the client"):
        self.succeed("prepare", "--content", str(self.content_path), "--date", when)
        self.succeed("confirm")
        flags = [value for answer in answers for value in ("--answer", answer)] or ["--answer"]
        self.succeed("record", *flags, "--attendee", person, "--decided-by", person)
        result = self.command("client-copy", setup=fixture.TEST_PDF_RENDERER)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        if signer:
            self.succeed("sign", "--by", signer, "--on", when)
        self.succeed("lock")

    def start_docs(self):
        (self.project / "docs/meeting-form.md").write_text(FORM, encoding="utf-8")
        self.prd.write_text("# PRD: Corner Bakery\n> v1 · Draft\n\n" + SOURCE, encoding="utf-8")
        self.succeed("start", "--meeting-day", "Saturday", "--language", "en")

    def close_docs_week(self):
        self.write_json("pages/draft.json", {
            "headline": "Pickup orders", "stage": 3, "decisions": DECISIONS,
            "document": [{"title": "How orders run", "sentences": [
                {"text": sentence, "source": "docs/prd.md"} for sentence in (
                    "The shop will confirm {D-001} pickup.",
                    "Orders wait in a basket {D-002}.",
                    "The client packs the bread {D-003}.",
                )
            ]}],
            "next_week": [], "needs": [],
        })
        self.close_meeting("2026-08-15", "D-001=the client", "D-002=later", "D-003=later")

    def log_change(self, what, reason, asked_by, days):
        result = self.command("change", "--what", what, "--reason", reason, "--asked-by", asked_by,
                              "--days", days, setup=fixture.cli_date_setup("2026-09-01"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def run_handoff(self, *options, start=START, real_end=AGREED, expected=0):
        before = fixture.snapshot(self.scratch)
        result = self.command("handoff", "--start", start, "--real-end", real_end, *options)
        self.assertEqual(fixture.snapshot(self.scratch), before)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        if expected:
            self.assertEqual(result.stdout, "")
            self.assertTrue(result.stderr.strip())
            return result.stderr
        self.assertEqual(result.stderr, "")
        summary, separator, encoded = result.stdout.partition("\nDates JSON\n")
        self.assertTrue(separator, result.stdout)
        self.assertTrue(summary.strip())
        return summary, json.loads(encoded)

    def finish_sample(self):
        self.start_docs()
        self.close_docs_week()
        self.succeed("no-meeting", "--date", "2026-08-22")
        approved_prd = self.prd.read_text(encoding="utf-8").replace("Draft", "Approved 2026-08-15 by the client")
        self.prd.write_text(approved_prd + f"\n- **Dates:** Delivery by {PLANNED}.\n", encoding="utf-8")
        self.succeed("enter-build")
        for what, days in (("Extend pickup hours", "2"), ("Rename the pickup label", "0"),
                           ("Add another shelf", "5"), ("Add table service", "8")):
            self.log_change(what, "The client asked", "the client", days)
        self.write_content(needs=[])
        self.close_meeting("2026-09-05", "C-001=yes", "C-002=yes", "C-003=later", "C-004=no",
                           signer="the client")
        self.succeed("no-meeting", "--date", "2026-09-12")

    def seed_ledger(self):
        self.succeed("start", "--language", "en", "--meeting-day", "Saturday", "--planned-end", PLANNED)
        self.write_json("weeks/week-3.json", {
            "number": 3, "meeting_date": "2026-08-15", "held": False, "mode": "docs",
            "locked_on": "2026-08-15",
        })
        week = {
            "number": 4, "meeting_date": "2026-09-05", "held": True, "mode": "build",
            "attendees": ["the client"], "answers": [{"id": "C-001", "answer": "yes", "days": 2}],
            "end_before": PLANNED, "end_after": AGREED, "owner_confirmed_on": "2026-09-05",
            "signed_by": "the client", "signed_on": "2026-09-05", "locked_on": "2026-09-05",
        }
        change = {
            "id": "C-001", "date": "2026-09-01", "what": "Extend pickup hours",
            "reason": "The client asked", "asked_by": "the client", "days_added": 2,
            "status": "approved", "decided_week": 4, "decided_by": "the client",
        }
        self.write_json("weeks/week-4.json", week)
        self.write_json("changes.json", [change])
        return week, change

    def test_finished_project_hands_over_only_approved_changes_including_zero(self):
        self.finish_sample()
        summary, preliminary = self.run_handoff()
        _, confirmed = self.run_handoff("--confirmed")
        self.assertEqual(len(preliminary), 5)
        self.assertEqual(len({row["id"] for row in preliminary}), 5)
        self.assertEqual([dict(row, confirmed=True) for row in preliminary], confirmed)
        self.assertTrue(all(row["confirmed"] is False for row in preliminary))
        milestones = {row["kind"]: row for row in confirmed if row["kind"] != "change request"}
        self.assertEqual(set(milestones), {"start", "planned end", "real end"})
        for kind, day in (("start", START), ("planned end", PLANNED), ("real end", AGREED)):
            self.assertEqual(set(milestones[kind]), MILESTONE_FIELDS)
            self.assertEqual(milestones[kind]["date"], day)
            self.assertIn(day, summary)
        self.assertEqual(milestones["start"]["source"], "the owner")
        self.assertEqual(milestones["real end"]["source"], "the owner")
        self.assertIn("docs/weekly/project.json", milestones["planned end"]["source"])
        events = {row["id"]: row for row in confirmed if row["kind"] == "change request"}
        self.assertEqual(set(events), {"C-001", "C-002"})
        for saved in self.read_json(self.weekly / "changes.json")[:2]:
            row = events[saved["id"]]
            self.assertEqual(set(row), EVENT_FIELDS | {"asked_by"})
            for name in ("date", "what", "reason", "asked_by", "days_added"):
                self.assertEqual(row[name], saved[name])
            for source_part in ("docs/weekly/changes.json", saved["id"], str(saved["decided_week"])):
                self.assertIn(source_part, row["source"])
            self.assertIn(saved["what"], summary)
            self.assertIn(saved["reason"], summary)

    def test_repeated_delays_can_extend_dates_or_finish_early(self):
        self.seed_ledger()
        for end, days in (("2027-03-19", "3"), ("2027-03-10", "-6")):
            with self.subTest(days=days):
                _, rows = self.run_handoff(
                    "--delay", "2027-03-01", "Inspect the shelf", "2", "The shelf needs a check",
                    "--delay", "2027-03-02", "Schedule the pickup trial", days,
                    "The client changed the trial date", real_end=end,
                )
                delays = [row for row in rows if row["kind"] == "delay"]
                self.assertEqual(len({row["id"] for row in rows}), len(rows))
                self.assertEqual([row["days_added"] for row in delays], [2, int(days)])
                self.assertEqual([row["date"] for row in delays], ["2027-03-01", "2027-03-02"])
                self.assertEqual([row["what"] for row in delays], ["Inspect the shelf", "Schedule the pickup trial"])
                self.assertEqual([row["reason"] for row in delays], ["The shelf needs a check",
                                                                   "The client changed the trial date"])
                self.assertTrue(all(set(row) == EVENT_FIELDS and row["source"] == "the owner"
                                    for row in delays))

    def test_delay_days_refuse_zero_and_nonintegers(self):
        self.seed_ledger()
        for days in ("0", "-0", "1.5", "two"):
            with self.subTest(days=days):
                output = self.run_handoff("--delay", "2027-03-01", "Inspect the shelf", days,
                                          "The shelf needs a check", expected=2)
                self.assertRegex(output.casefold(), r"delay|days")

    def test_delay_keeps_words_that_look_like_flags(self):
        self.seed_ledger()
        _, rows = self.run_handoff("--delay", "2027-03-01", "-weather", "1", "--confirmed",
                                   real_end="2027-03-15")
        self.assertTrue(all(row["confirmed"] is False for row in rows))
        delay, = [row for row in rows if row["kind"] == "delay"]
        self.assertEqual((delay["what"], delay["reason"]), ("-weather", "--confirmed"))

    def test_delay_text_is_one_line_in_the_preview_and_json(self):
        self.seed_ledger()
        summary, rows = self.run_handoff(
            "--delay", "2027-03-01", "  Inspect\n\t the  shelf ", "1",
            "\tThe shelf\r\n needs a check  ", real_end="2027-03-15",
        )
        delay, = [row for row in rows if row["kind"] == "delay"]
        self.assertEqual((delay["what"], delay["reason"]), ("Inspect the shelf", "The shelf needs a check"))
        self.assertIn(delay["what"], summary)
        self.assertIn(delay["reason"], summary)

    def test_abbreviated_confirmation_is_refused(self):
        self.seed_ledger()
        self.assertIn("--conf", self.run_handoff("--conf", expected=2))

    def test_docs_project_refuses_handoff(self):
        self.start_docs()
        self.assertRegex(self.run_handoff(expected=2).casefold(), r"docs|enter-build|build mode")

    def test_build_project_needs_a_locked_build_week(self):
        self.succeed("start", "--language", "en", "--meeting-day", "Saturday", "--planned-end", PLANNED)
        output = self.run_handoff(real_end=PLANNED, expected=2)
        self.assertIn("build week", output.casefold())

    def test_legacy_missed_week_keeps_the_prior_delivery_date(self):
        self.seed_ledger()
        self.write_json("weeks/week-5.json", {"number": 5, "meeting_date": "2026-09-12",
                                              "held": False, "mode": "build", "locked_on": "2026-09-12",
                                              "end_before": AGREED})
        _, rows = self.run_handoff()
        self.assertEqual([row["date"] for row in rows if row["kind"] == "real end"], [AGREED])

    def test_every_week_must_be_locked_including_old_docs_weeks(self):
        self.seed_ledger()
        for number in (3, 4):
            with self.subTest(number=number):
                path = f"weeks/week-{number}.json"
                locked = self.read_json(self.weekly / path)
                unlocked = dict(locked)
                del unlocked["locked_on"]
                self.write_json(path, unlocked)
                self.assertIn(f"week {number}", self.run_handoff(expected=2).casefold())
                self.write_json(path, locked)

    def test_waiting_change_is_named_and_blocks_handoff(self):
        _, approved = self.seed_ledger()
        waiting = dict(approved, id="C-002", status="waiting", days_added=None,
                       decided_by="", decided_week=None)
        self.write_json("changes.json", [approved, waiting])
        output = self.run_handoff(expected=2)
        self.assertIn("C-002", output)
        self.assertRegex(output.casefold(), r"wait|decid|decision")

    def test_approved_change_needs_all_recorded_details(self):
        _, approved = self.seed_ledger()
        for name in ("days_added", "decided_by", "decided_week", "reason", "asked_by"):
            with self.subTest(name=name):
                incomplete = dict(approved)
                del incomplete[name]
                self.write_json("changes.json", [incomplete])
                output = self.run_handoff(expected=2)
                self.assertRegex(output, r"C-001|changes\.json row 1")
                self.assertIn(name, output)

    def test_week_dates_and_approved_days_are_reconciled_independently(self):
        week, change = self.seed_ledger()
        self.write_json("weeks/week-4.json", dict(week, end_after="2027-03-15"))
        self.assertIn("week 4", self.run_handoff(expected=2).casefold())

        self.write_json("weeks/week-4.json", week)
        self.write_json("changes.json", [dict(change, days_added=1)])
        self.assertIn("C-001", self.run_handoff(expected=2))

    def test_approved_change_must_point_to_its_recorded_answer(self):
        _, change = self.seed_ledger()
        self.write_json("changes.json", [dict(change, decided_week=3)])
        self.assertIn("C-001", self.run_handoff(expected=2))

    def test_bad_dates_name_their_rows(self):
        week, change = self.seed_ledger()
        for field, options in (("start", {"start": "2026-02-30"}),
                               (r"real[- ]end", {"real_end": "20270314"})):
            with self.subTest(field=field):
                self.assertRegex(self.run_handoff(expected=2, **options).casefold(), field)
        output = self.run_handoff("--delay", "2027-02-30", "Inspect the shelf", "2",
                                  "The shelf needs a check", expected=2)
        self.assertIn("delay", output.casefold())

        self.write_json("changes.json", [dict(change, date="2026-09-31")])
        output = self.run_handoff(expected=2)
        self.assertRegex(output, r"C-001|changes\.json row 1")
        self.write_json("changes.json", [change])

        self.write_json("weeks/week-4.json", dict(week, end_after="2027-03-32"))
        self.assertIn("week 4", self.run_handoff(expected=2).casefold())
        self.write_json("weeks/week-4.json", week)

        project = self.read_json(self.weekly / "project.json")
        self.write_json("project.json", dict(project, planned_end="2027-03-32"))
        self.assertRegex(self.run_handoff(expected=2).casefold(), r"planned.end")

    def test_start_must_precede_both_planned_and_real_end(self):
        self.seed_ledger()
        for start, real_end in (("2027-03-13", "2027-03-14"), ("2027-03-10", "2027-03-09")):
            with self.subTest(start=start, real_end=real_end):
                output = self.run_handoff(start=start, real_end=real_end, expected=2)
                self.assertIn("start", output.casefold())

    def test_change_and_delay_must_fall_within_the_project(self):
        _, change = self.seed_ledger()
        self.write_json("changes.json", [dict(change, date="2026-07-31")])
        self.assertIn("C-001", self.run_handoff(expected=2))
        self.write_json("changes.json", [change])
        output = self.run_handoff("--delay", "2027-03-15", "Inspect the shelf", "1",
                                  "The shelf needs a check", expected=2)
        self.assertIn("delay", output.casefold())

    def test_unreconciled_real_end_names_both_dates_and_difference(self):
        self.seed_ledger()
        output = self.run_handoff(real_end="2027-03-16", expected=2)
        self.assertIn(AGREED, output)
        self.assertIn("2027-03-16", output)
        self.assertRegex(output.casefold(), r"\b2\s+(?:calendar\s+)?days\b")
        self.assertIn("owner", output.casefold())
        self.assertIn("delay", output.casefold())

    def test_pending_transaction_is_not_recovered_during_handoff(self):
        self.seed_ledger()
        self.write_json(".weekflow-undo.json", [{
            "path": "docs/weekly/changes.json", "data": b64encode(b"[]\n").decode("ascii"),
        }])
        output = self.run_handoff(expected=2)
        self.assertRegex(output.casefold(), r"recover|pending|interrupted")

    def test_arabic_and_dated_name_removal_are_preserved_verbatim(self):
        (self.project / "docs/meeting-form.md").write_text(ARABIC_FORM, encoding="utf-8")
        self.prd.write_text(ARABIC_PRD + "> الإصدار 1 · معتمد 2026-08-15 من العميل\n\n"
                            + f"- **المواعيد:** التسليم في {PLANNED}.\n", encoding="utf-8")
        self.succeed("start", "--language", "ar", "--meeting-day", "الأحد")
        self.log_change("تعديل وقت الاستلام", "طلب العميل", "ريم", "0")
        self.write_content(headline="قائمة الخبز جاهزة.", finished=[], next_week=[], needs=[])
        self.close_meeting("2026-09-06", "C-001=yes", person="العميل")
        result = self.command("remove-name", "--name", "ريم", "--what", "إزالة بيانات شخصية",
                              "--reason", "الخصوصية", "--by", "المالك", setup=STUB_REMOVAL_PDF)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        summary, rows = self.run_handoff("--confirmed", real_end=PLANNED)
        saved = self.read_json(self.weekly / "changes.json")[0]
        event, = [row for row in rows if row["kind"] == "change request"]
        self.assertNotIn("ريم", summary + str(rows))
        self.assertIn("بسبب الخصوصية", saved["asked_by"])
        for key in ("what", "reason", "asked_by"):
            self.assertEqual(event[key], saved[key])
            self.assertIn(saved[key], summary)


if __name__ == "__main__":
    unittest.main()
