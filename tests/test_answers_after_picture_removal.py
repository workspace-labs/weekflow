"""Keep answers from confirmed pages through dated picture removals."""

import unittest

from test_recorded_meeting import RecordedMeetingFixture
from test_screen_meetings import png


class AnswersAfterPictureRemovalTests(RecordedMeetingFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.start()
        self.add_change()
        self.command("screen", "--id", "menu", "--name", "Menu", "--state", "finished")
        self.screens = self.project_file.with_name("screens.json")
        self.picture_input = self.scratch / "capture.png"
        self.earlier = self.save_picture((20, 30, 40), "2026-02-24")
        self.current = self.save_picture((50, 60, 70), "2026-02-25")
        self.write_json(self.draft, dict(self.read_json(self.draft), app_ran=True))
        self.prepare()

    def save_picture(self, color, day):
        self.picture_input.write_bytes(png(color))
        self.command("screen-picture", "--id", "menu", "--kind", "screenshot",
                     "--file", str(self.picture_input), "--taken-on", day)
        self.command("screen-check", "--id", "menu")
        return self.read_json(self.screens)[0]["picture"]

    def remove_picture(self, reference):
        self.command("remove-picture", "--id", "menu", "--file", reference,
                     "--what", "Picture in the meeting", "--reason", "Personal details", "--by", "the owner")

    def test_answers_from_each_confirmed_page_survive_successive_removals(self):
        original = self.answer_file({"C-001": "yes"})
        self.remove_picture(self.earlier)
        intermediate = self.answer_file({"C-001": "later"})
        self.remove_picture(self.current)
        latest = self.answer_file({"C-001": "no"})
        self.assertEqual(len({download["fingerprint"] for download in (original, intermediate, latest)}), 3)

        for download in (original, intermediate, latest):
            with self.subTest(download=download["answers"]):
                self.write_json(self.answers_path, download)
                saved_bytes = self.answers_path.read_bytes()
                self.record_download()
                [answer] = self.read_json(self.week)["answers"]
                self.assertEqual(answer["answer"], download["answers"]["C-001"])
                self.assertEqual(self.answers_path.read_bytes(), saved_bytes)

    def test_a_changed_meeting_still_requires_answers_from_its_confirmed_page(self):
        original = self.answer_file({"C-001": "yes"})
        self.remove_picture(self.current)
        self.write_json(self.draft, dict(self.read_json(self.draft), headline="The pickup form is ready."))
        self.prepare()
        self.write_json(self.answers_path, original)
        self.assertIn("answers saved from the confirmed meeting page", self.refuse(
            "record", "--answers", str(self.answers_path), "--attendee", "the owner", "--decided-by", "the client",
        ))
        self.record_saved({"C-001": "yes"})
