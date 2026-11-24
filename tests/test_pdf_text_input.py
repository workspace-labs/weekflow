"""Refuse unsupported client-copy text before commands save it."""

import unittest

from test_recorded_meeting import BLOCK_REPORTLAB, RecordedMeetingFixture


UNSUPPORTED = "محمد"


class PdfTextInputTests(RecordedMeetingFixture, unittest.TestCase):
    def refuse_glyph(self, command, field, *args):
        refusal = self.refuse(command, *args, setup=BLOCK_REPORTLAB)
        self.assertIn("pdf font cannot draw u+", refusal)
        self.assertIn(field, refusal)
        self.assertNotIn(UNSUPPORTED, refusal)

    def lock_first_week(self):
        self.prepare()
        self.record_manual()
        self.stamp_stub_pdf()
        self.command("lock")

    def test_start_refuses_unsupported_client_attendee_and_prd_project(self):
        setup_args = ("--language", "en", "--meeting-day", "Thursday",
                      "--planned-end", "2026-03-12")
        for flag, field in (("--client", "client"), ("--attendee", "attendees")):
            with self.subTest(field=field):
                self.refuse_glyph("start", field, *setup_args, flag, UNSUPPORTED)
        prd = self.project / "docs/prd.md"
        text = prd.read_text(encoding="utf-8").replace("# PRD: Corner Bakery", f"# PRD: {UNSUPPORTED}")
        prd.write_text(text, encoding="utf-8")
        self.refuse_glyph("start", "project", *setup_args)

    def test_change_refuses_each_unsupported_text_field(self):
        self.start()
        defaults = {"what": "Later pickup", "reason": "The shop stays open", "asked-by": "The client"}
        for field in defaults:
            with self.subTest(field=field):
                values = dict(defaults, **{field: UNSUPPORTED})
                flags = [flag for key, value in values.items() for flag in (f"--{key}", value)]
                self.refuse_glyph("change", field, "--days", "2", *flags)

    def test_prepare_refuses_unsupported_headline_and_each_item_list(self):
        self.start()
        options = ("--date", self.meeting_date, "--content", str(self.draft))
        draft = self.read_json(self.draft)
        for field in ("headline", "finished", "next_week", "needs"):
            with self.subTest(field=field):
                bad_value = UNSUPPORTED if field == "headline" else [dict(draft[field][0], text=UNSUPPORTED)]
                self.write_json(self.draft, dict(draft, **{field: bad_value}))
                self.refuse_glyph("prepare", field, *options)

    def test_prepare_checks_text_in_earlier_saved_changes(self):
        self.start()
        self.add_change()
        changes = self.read_json(self.changes)
        changes[0]["asked_by"] = UNSUPPORTED
        self.write_json(self.changes, changes)
        self.refuse_glyph("prepare", "asked-by", "--date", self.meeting_date, "--content", str(self.draft))

    def test_record_refuses_unsupported_attendee_and_decider(self):
        self.start()
        self.add_change()
        self.prepare()
        self.refuse_glyph("record", "attendees", "--answer", "C-001=no",
                          "--decided-by", "Client", "--attendee", UNSUPPORTED)
        self.refuse_glyph("record", "decided-by", "--answer", "C-001=no",
                          "--decided-by", UNSUPPORTED, "--attendee", "Owner")

    def test_check_promise_refuses_unsupported_note(self):
        self.start()
        self.lock_first_week()
        self.refuse_glyph("check-promise", "note", "--id", "P-001", "--status", "not-finished",
                          "--note", UNSUPPORTED)

    def test_correct_refuses_each_unsupported_detail(self):
        self.start()
        self.lock_first_week()
        defaults = {"what": "The date was wrong", "reason": "The form was revised", "by": "Owner"}
        for field in defaults:
            with self.subTest(field=field):
                values = dict(defaults, **{field: UNSUPPORTED})
                flags = [flag for key, value in values.items() for flag in (f"--{key}", value)]
                self.refuse_glyph("correct", field, "--week", "3", *flags)

    def test_remove_name_refuses_unsupported_details_before_writing(self):
        self.command("start", "--language", "en", "--meeting-day", "Thursday",
                     "--planned-end", "2026-03-12", "--client", "Avery Fox")
        defaults = {"what": "Client name", "reason": "Privacy request", "by": "Owner"}
        for field in defaults:
            with self.subTest(field=field):
                values = dict(defaults, **{field: UNSUPPORTED})
                flags = [flag for key, value in values.items() for flag in (f"--{key}", value)]
                self.refuse_glyph("remove-name", field, "--name", "Avery Fox", *flags)

    def test_prepare_uses_the_font_for_each_field(self):
        self.start()
        # The display font has this glyph. The body font used for needs does not.
        draft = dict(self.read_json(self.draft), headline="Ready ½")
        self.write_json(self.draft, draft)
        options = ("--date", self.meeting_date, "--content", str(self.draft))
        self.command("prepare", *options, setup=BLOCK_REPORTLAB)
        self.write_json(self.draft, dict(draft, needs=[{"text": "Need ½"}]))
        self.refuse_glyph("prepare", "needs", *options)
