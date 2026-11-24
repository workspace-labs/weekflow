"""Exercise promises, needs and missed meetings through the local CLI."""

from datetime import date, timedelta
import unittest

from test_recorded_meeting import RecordedMeetingFixture


WEEK_DATE = "2026-03-05"
AFTER_MISSED = "2026-03-12"


class CarryOverTests(RecordedMeetingFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.start()
        self.promises = self.project_file.with_name("promises.json")
        self.next_record = self.week.with_name("week-4.json")
        self.next_content = self.content.with_name("week-4-content.json")
        self.next_page = self.page.with_name("week-4.html")

    def finish_week(self, *answers, lock=True):
        self.prepare()
        self.record_manual(*answers)
        self.stamp_stub_pdf()
        if lock:
            self.command("lock")

    def check_promise(self, *args):
        self.command("check-promise", "--id", "P-001", *args)

    def refuse_prepare(self, meeting_date=WEEK_DATE):
        return self.refuse("prepare", "--date", meeting_date, "--content", str(self.draft))

    def set_draft(self, **fields):
        self.write_json(self.draft, dict(self.read_json(self.draft), **fields))

    def test_lock_creates_each_promise_once_after_interrupted_write(self):
        self.set_draft(next_week=[{"text": "First promise"}, {"text": "Second promise"}])
        self.add_change()
        self.finish_week("C-001=no", lock=False)
        interrupt_after_promises = """
replace = os.replace

def exit_after_promises(source, destination):
    replace(source, destination)
    if os.path.basename(destination) == 'promises.json':
        os._exit(91)

os.replace = exit_after_promises
"""
        self.command("lock", setup=interrupt_after_promises, expected=91)
        self.command("lock")
        self.assertEqual(self.read_json(self.promises), [
            {"id": "P-001", "made_week": 3, "what": "First promise", "status": "open"},
            {"id": "P-002", "made_week": 3, "what": "Second promise", "status": "open"},
        ])
        waiting = self.refuse_prepare()
        for text in ("p-001", "p-002", "first promise", "second promise"):
            self.assertIn(text, waiting)
        self.assertEqual(self.read_json(self.changes)[0]["status"], "refused")
        self.assertFalse(list(self.project_file.parent.glob(".weekflow-*")))

    def test_checks_need_owner_text_and_freeze_with_locked_meeting(self):
        self.finish_week()
        locked_files = (self.week.read_bytes(), self.page.read_bytes(), self.pdf.read_bytes())
        base = ("--id", "P-001", "--status")
        for note in ((), ("--note", "   ")):
            self.assertIn("note", self.refuse("check-promise", *base, "not-finished", *note))
        self.check_promise("--status", "done")
        self.meeting_date = WEEK_DATE
        self.prepare(confirm=False)
        self.check_promise("--status", "not-finished", "--note", "Ready after the delivery")
        self.assertIn("prepare", self.refuse("confirm"))
        self.prepare()
        frozen = self.next_content.read_bytes(), self.next_page.read_bytes()
        [result] = self.read_json(self.next_content)["meeting_promises"]
        self.assertEqual(result, {"id": "P-001", "made_week": 3, "checked_week": 4,
                                  "what": "Show the pickup form", "status": "not finished",
                                  "note": "Ready after the delivery"})
        self.assertIn("prepare", self.refuse("check-promise", *base, "done"))
        self.record_manual()
        self.assertIn("prepare", self.refuse("check-promise", *base, "done"))
        self.pdf = self.next_page.with_suffix(".pdf")
        self.stamp_stub_pdf()
        self.command("lock")
        self.assertIn("locked", self.refuse("check-promise", *base, "done"))
        self.assertEqual((self.next_content.read_bytes(), self.next_page.read_bytes()), frozen)
        self.assertEqual((self.week.read_bytes(), self.page.read_bytes(),
                          self.page.with_suffix(".pdf").read_bytes()), locked_files)

    def test_prepare_refuses_omissions_and_accepts_carried_and_received_needs(self):
        self.set_draft(next_week=[], needs=[{"text": "Pickup times"}, {"text": "Menu prices"}])
        self.finish_week()
        self.set_draft(needs=[])
        refusal = self.refuse_prepare()
        self.assertIn("pickup times", refusal)
        self.assertIn("menu prices", refusal)
        self.set_draft(needs=[{"text": "Pickup times"}], received=["menu prices"])
        self.assertIn("menu prices", self.refuse_prepare())
        self.set_draft(received=["Menu prices"])
        self.meeting_date = WEEK_DATE
        self.prepare()
        self.assertEqual(self.read_json(self.next_content)["received"], ["Menu prices"])
        self.assertEqual(self.read_json(self.next_content)["needs"], [{"text": "Pickup times"}])

    def test_restore_without_pages_carries_sheets_to_the_next_lock(self):
        self.set_draft(needs=[{"text": "Pickup times"}])
        self.add_change()
        self.finish_week()
        self.check_promise("--status", "done")
        corrections = self.project_file.with_name("corrections.json")
        self.command("correct", "--week", "3", "--what", "Correct the order count",
                     "--reason", "Check against the order book", "--by", "the owner")
        # A restored project has the records but none of the pages, copies or drafts.
        pages = self.page.parent
        pages.rename(self.scratch / "lost-pages")
        self.assertFalse(pages.exists())
        pages.mkdir()
        self.draft = pages / "new-draft.json"
        self.write_json(self.draft, {"headline": "Ready to check the orders."})
        self.meeting_date = WEEK_DATE
        args = ("--date", self.meeting_date, "--content", str(self.draft))
        message = self.command("prepare", *args)
        self.assertEqual(message.count("needs could not be read"), 1)
        self.assertIn("Ask the owner", message)
        message = self.command("prepare", *args)
        self.assertNotIn("needs could not be read", message)
        shown = self.read_json(self.next_content)
        self.assertEqual([row["id"] for row in shown["meeting_changes"]], ["C-001"])
        self.assertEqual([row["id"] for row in shown["meeting_promises"]], ["P-001"])
        self.assertEqual(shown["corrections"], self.read_json(corrections))
        self.command("confirm")
        self.record_manual("C-001=no")
        self.pdf = self.next_page.with_suffix(".pdf")
        self.client_copy()
        self.command("lock")
        self.assertTrue(self.read_json(self.next_record)["locked_on"])
        self.command("prepare", "--date", AFTER_MISSED, "--content", str(self.draft))
        self.assertNotIn("corrections", self.read_json(self.content.with_name("week-5-content.json")))

    def test_missing_historical_content_shows_its_correction_again(self):
        self.set_draft(next_week=[])
        self.finish_week()
        self.command("correct", "--week", "3", "--what", "Correct the order count",
                     "--reason", "Check against the order book", "--by", "the owner")
        self.meeting_date = WEEK_DATE
        self.prepare()
        self.record_manual()
        self.pdf = self.next_page.with_suffix(".pdf")
        self.stamp_stub_pdf()
        self.command("lock")
        self.next_content.rename(self.scratch / "lost-content.json")

        self.meeting_date = AFTER_MISSED
        self.prepare()
        shown = self.read_json(self.content.with_name("week-5-content.json"))["corrections"]
        self.assertEqual([row["id"] for row in shown], ["X-001"])

    def test_no_meeting_makes_short_record_and_enforces_dates_and_refusals(self):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        self.assertIn("future", self.refuse("no-meeting", "--date", tomorrow))
        self.command("no-meeting", "--date", WEEK_DATE)
        self.assertEqual(self.read_json(self.week), {
            "number": 3, "meeting_date": WEEK_DATE, "held": False, "mode": "build",
            "end_before": "2026-03-12", "end_after": "2026-03-12",
            "locked_on": date.today().isoformat(),
        })
        self.assertFalse(self.promises.exists())
        for path in (self.page, self.content, self.pdf):
            self.assertFalse(path.exists())
        for command, args in (("confirm", ()), ("client-copy", ()),
                              ("record", ("--answer", "--attendee", "the owner")),
                              ("sign", ("--by", "the client", "--on", WEEK_DATE))):
            with self.subTest(command=command):
                self.assertIn("no meeting was held", self.refuse(command, *args))
        self.assertIn("locked", self.refuse("lock"))
        self.assertIn("before", self.refuse("no-meeting", "--date", self.meeting_date))
        self.assertIn("before", self.refuse_prepare(self.meeting_date))
        self.command("no-meeting", "--date", AFTER_MISSED)
        self.meeting_date = AFTER_MISSED
        self.prepare(confirm=False)
        later_content = self.content.with_name("week-5-content.json")
        self.assertEqual(self.read_json(later_content)["missed_meetings"], [WEEK_DATE, AFTER_MISSED])

    def test_retired_draft_leaves_no_copy_and_carries_items_from_prior_meeting(self):
        self.add_change()
        self.add_change(title="Move the final pickup time", days=2)
        self.finish_week("C-002=yes", lock=False)
        self.command("sign", "--by", "the client", "--on", self.meeting_date)
        self.command("lock")
        open_promises = self.promises.read_bytes()
        self.command("no-meeting", "--date", WEEK_DATE)
        self.assertEqual(self.promises.read_bytes(), open_promises)
        self.assertIn("p-001", self.refuse_prepare(AFTER_MISSED))
        self.check_promise("--status", "done")
        self.meeting_date = AFTER_MISSED
        self.prepare()
        self.pdf = self.page.with_name("week-5.pdf")
        self.stamp_stub_pdf()
        retired = (self.page.with_name("week-5.html"), self.content.with_name("week-5-content.json"), self.pdf)
        self.command("no-meeting", "--date", AFTER_MISSED)
        for path in retired:
            self.assertFalse(path.exists())
        self.assertIn("locked", self.refuse("check-promise", "--id", "P-001", "--status", "done"))
        self.set_draft(needs=[])
        self.assertIn("pickup times", self.refuse_prepare(AFTER_MISSED))
        self.set_draft(received=["Pickup times"])
        self.prepare()
        later_week = self.week.with_name("week-6.json")
        later_content = self.content.with_name("week-6-content.json")
        self.assertEqual(self.read_json(later_week)["end_before"], "2026-03-14")
        facts = self.read_json(later_content)
        self.assertEqual([row["id"] for row in facts["meeting_changes"]], ["C-001"])
        self.assertEqual(facts["missed_meetings"], [WEEK_DATE, AFTER_MISSED])
        self.assertEqual([row["checked_week"] for row in facts["meeting_promises"]], [5])

    def test_no_meeting_refuses_recorded_unlocked_week(self):
        self.finish_week(lock=False)
        self.assertIn("recorded", self.refuse("no-meeting", "--date", self.meeting_date))

    def test_same_week_reprepare_keeps_only_originally_confirmed_corrections(self):
        self.set_draft(next_week=[])
        self.finish_week()
        correction = ("--week", "3", "--reason", "Keep the notes accurate", "--by", "the owner")
        self.command("correct", *correction, "--what", "First correction")
        self.meeting_date = WEEK_DATE
        self.prepare()
        self.command("correct", *correction, "--what", "Late correction")
        for _ in range(2):
            self.prepare(confirm=False)
            self.assertEqual([row["id"] for row in self.read_json(self.next_content)["corrections"]], ["X-001"])
            self.assertNotIn("Late correction", self.next_page.read_text(encoding="utf-8"))
        self.command("confirm")
        self.record_manual()
        self.pdf = self.next_page.with_suffix(".pdf")
        self.stamp_stub_pdf()
        self.command("lock")

        self.meeting_date = AFTER_MISSED
        self.prepare()
        later_content = self.content.with_name("week-5-content.json")
        self.assertEqual([row["id"] for row in self.read_json(later_content)["corrections"]], ["X-002"])

    def test_interrupted_no_meeting_can_retire_the_draft_on_retry(self):
        self.prepare()
        self.stamp_stub_pdf()
        interrupt_after_week = """
replace = os.replace

def exit_after_week(source, destination):
    replace(source, destination)
    if os.path.basename(destination) == 'week-3.json':
        os._exit(91)

os.replace = exit_after_week
"""
        self.command("no-meeting", "--date", WEEK_DATE, setup=interrupt_after_week, expected=91)
        self.command("no-meeting", "--date", WEEK_DATE)
        self.assertEqual(self.read_json(self.week)["number"], 3)
        for path in (self.page, self.content, self.pdf):
            self.assertFalse(path.exists())
        self.assertFalse(self.next_record.exists())
        self.assertFalse(list(self.project_file.parent.glob(".weekflow-*")))
