"""Check docs evidence and the project form on disposable inputs."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/weekflow/scripts"))

from weekflow_tool.content import read_content
from weekflow_tool.documents import has_project_docs, prd_is_draft, read_approved_prd, read_meeting_form
from weekflow_tool.storage import ProjectFiles, Refusal


FORM = """# Client meeting form: Corner Bakery

| Client (organisation, department) | Corner Bakery shop |

## Meetings held

| # | Date and place | Stage | Who came (name and job) | What was decided |
|---|---|---|---|---|
| 2 | at the shop | 1, 2 | the owner | |
| 4 | at the shop | 2 | the owner; the client | |

## Still open

| # | Question | Why open (missing or conflict) |
|---|---|---|
| 1.1 | Who confirms the order? | missing |
| 10 | 10. The decision | missing |

## Stage 4: approve the scope, or stop

### 10. The decision

| Decision | ✓ |
|---|---|
| Approved | |
| Changes first (listed below, then another Stage 4 meeting) | |
| Stop (why, below) | |
"""


class DocsContentTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.files = ProjectFiles(self.root)
        self.payload = {
            "headline": "The order",
            "stage": 3,
            "document": [{"title": "Orders", "sentences": [{
                "text": "The shop confirms each order with {D-001}.",
                "source": "docs/prd.md",
            }]}],
            "decisions": [{"id": "D-001", "question": "Who confirms the order?",
                           "why": "The form is open.",
                           "options": ["the owner", "the client"]}],
        }
        self.write("docs/prd.md", "# PRD: Corner Bakery\n> v2 · Draft\n\n"
                                   "> The shop **confirms** each\n> [order](orders.md) with not decided.\n")
        self.write("docs/meeting-form.md", FORM)

    def write(self, relative, content):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def draft(self):
        self.write("draft.json", json.dumps(self.payload))
        return read_content(self.files, "draft.json", mode="docs")

    def test_form_tracks_actual_held_stages_and_checked_stop(self):
        form = read_meeting_form(self.files)
        self.assertEqual(form.project, "Corner Bakery")
        self.assertEqual(form.attendees, ["the owner", "the client"])
        self.assertEqual(form.last_number, 4)
        self.assertEqual(form.latest_stage, 2)
        self.assertEqual(form.stage_meetings, {1: 2, 2: 4})
        self.assertEqual(form.still_open, ("Who confirms the order?", "10. The decision"))
        self.assertFalse(form.stopped)
        self.write("docs/meeting-form.md", FORM.replace("| Stop (why, below) | |", "| Stop (why, below) | ✓ |"))
        self.assertTrue(read_meeting_form(self.files).stopped)

    def test_freezes_matched_words_and_form_until_confirmation(self):
        content, digests = self.draft()
        self.assertEqual(content["stage_meetings"], {"1": 2, "2": 4})
        self.assertEqual(content["form_still_open"], list(read_meeting_form(self.files).still_open))
        self.assertEqual(len(digests), 1)
        snapshot = dict(content, source_digests=digests)
        self.write("saved.json", json.dumps(snapshot))
        self.write("docs/prd.md", "A different source.")
        with self.assertRaisesRegex(Refusal, "The shop confirms each order"):
            read_content(self.files, "saved.json", mode="docs", saved=True)
        (self.root / "docs/prd.md").unlink()
        (self.root / "docs/meeting-form.md").unlink()
        self.assertEqual(read_content(self.files, "saved.json", mode="docs", saved=True,
                                      check_live_proof=False), (snapshot, digests))

    def test_exact_question_stage_and_scope_rules(self):
        decision = self.payload["decisions"][0]
        for question in ("Who confirms the order", "Who  confirms the order?", "10. The decision"):
            with self.subTest(question=question):
                decision["question"] = question
                with self.assertRaisesRegex(Refusal, "Still open|scope decision"):
                    self.draft()
        decision["question"] = "Who confirms the order?"
        for option in ("Stop", "Stop: for now", "Sign off on the PRD", "Scope approved",
                       "Proceed to build", "Proceed", "Continue the project",
                       "Move forward with the project", "Give the go-ahead", "Do not go ahead"):
            with self.subTest(option=option):
                decision["options"] = ["the owner", option]
                with self.assertRaisesRegex(Refusal, "scope|stop"):
                    self.draft()
        decision["options"] = ["the owner", "the client"]
        self.payload["stage"] = 1
        with self.assertRaisesRegex(Refusal, "stage 2"):
            self.draft()

    def test_distinguishes_scope_approval_from_choosing_an_approval_role(self):
        (self.root / "docs/meeting-form.md").unlink()
        decision = self.payload["decisions"][0]
        decision["question"] = "Can we proceed with the project?"
        decision["options"] = ["Yes", "No"]
        with self.assertRaisesRegex(Refusal, "scope decision"):
            self.draft()
        decision["question"] = "Who approves the scope?"
        decision["options"] = ["the owner", "the client"]
        content, _ = self.draft()
        self.assertEqual(content["decisions"][0], decision)

    def test_evidence_names_wrong_words_and_catches_invalid_markers(self):
        sentence = self.payload["document"][0]["sentences"][0]
        for invalid in ("The shop confirms every order with {D-001}.",
                        "The shop confirms each order with {D-099}.",
                        "The shop confirms each order with {D-01}.",
                        "The shop confirms each order with not decided."):
            with self.subTest(sentence=invalid):
                sentence["text"] = invalid
                with self.assertRaises(Refusal):
                    self.draft()

    def test_source_accepts_placeholders_inside_one_actual_sentence(self):
        sentence = self.payload["document"][0]["sentences"][0]
        sentence["text"] = "Before noon, {D-001} reviews the list."
        for placeholder in ("TBD", "not decided", "(owner to confirm)", "(who?)", "...", "?", ""):
            with self.subTest(placeholder=placeholder):
                self.write("docs/prd.md",
                           f"Before noon, {placeholder} reviews the list. "
                           "The cashier puts the list away.")
                self.draft()

    def test_source_keeps_common_abbreviations_inside_one_sentence(self):
        sentence = self.payload["document"][0]["sentences"][0]
        for quote in ("Before 5 p.m. {D-001} reviews the list.",
                      "Dr. {D-001} reviews the list.",
                      "At 8 a.m. the owner asks {D-001} to review the list.",
                      "Ms. {D-001} reviews the list.",
                      "Name a reviewer, e.g. {D-001} from the shop."):
            with self.subTest(quote=quote):
                sentence["text"] = quote
                self.write("docs/prd.md", quote.replace("{D-001}", "TBD") + " The shop opens.")
                self.draft()

    def test_sentence_can_end_with_a_time_abbreviation(self):
        sentence = self.payload["document"][0]["sentences"][0]
        sentence["text"] = "The shop closes at 5 p.m. {D-001} reviews the list."
        self.write("docs/prd.md", "The shop closes at 5 p.m. A colleague reviews the list.")
        with self.assertRaisesRegex(Refusal, "not found"):
            self.draft()

    def test_lowercase_ms_ends_a_sentence(self):
        sentence = self.payload["document"][0]["sentences"][0]
        sentence["text"] = "Wait 500 ms. {D-001} then leaves."
        self.write("docs/prd.md", "Wait 500 ms. The cashier then leaves.")
        with self.assertRaisesRegex(Refusal, "not found"):
            self.draft()

    def test_markers_cannot_join_unrelated_source_sentences_or_invent_words(self):
        sentence = self.payload["document"][0]["sentences"][0]
        sentence["text"] = "Before noon, {D-001} reviews the list."
        for source in ("Before noon, the cashier reviews each list.",
                       "Before noon, the cashier gets ready. A colleague reviews the list.",
                       "Before noon, the cashier gets ready! A colleague reviews the list.",
                       "Before noon, the cashier gets ready? A colleague reviews the list.",
                       "Before noon, (the cashier gets ready.) A colleague reviews the list.",
                       "Before noon, the cashier gets ready\n\nA colleague reviews the list.",
                       "Before noon, the cashier gets ready\n## Handoff\nA colleague reviews the list.",
                       "- Before noon, the cashier gets ready\n- A colleague reviews the list.",
                       "Sara reviews the list. Before noon, the shop opens."):
            with self.subTest(source=source):
                self.write("docs/prd.md", source)
                with self.assertRaisesRegex(Refusal, "not found"):
                    self.draft()

    def test_multiple_markers_keep_every_literal_fragment_in_order(self):
        sentence = self.payload["document"][0]["sentences"][0]
        sentence["text"] = "{D-001} verifies the list before {D-002} packs the order."
        self.write("docs/meeting-form.md", FORM.replace(
            "| 10 |", "| 1.2 | Who packs the order? | missing |\n| 10 |", 1))
        self.payload["decisions"].append({"id": "D-002", "question": "Who packs the order?",
                                          "why": "No picker yet.", "options": ["cashier", "host"]})
        self.write("docs/prd.md", "TBD verifies the list before not decided packs the order.")
        self.draft()
        self.write("docs/prd.md", "Before the owner packs the order, TBD verifies the list.")
        with self.assertRaisesRegex(Refusal, "not found"):
            self.draft()

    def test_timing_options_do_not_act_on_the_scope(self):
        decision = self.payload["decisions"][0]
        for option in ("At the end of the project", "End of the build", "Before the project ends",
                       "At project end", "Until the project ends", "Before the build starts",
                       "Confirm the build date", "Confirm the date of the build",
                       "Confirm the venue for the project"):
            with self.subTest(option=option):
                decision["options"] = ["the owner", option]
                content, _ = self.draft()
                self.assertEqual(content["decisions"][0]["options"][1], option)

    def test_scope_date_and_venue_actions_are_refused(self):
        decision = self.payload["decisions"][0]
        for option in ("Approve the project date", "Approve the build dates",
                       "Approve the date for the project", "Project date approved",
                       "Accept the delivery date for the build", "Green light the project date",
                       "Approve the scope date", "Stop the build date", "Cancel the project venue",
                       "Approve the date for the build", "Approve or confirm the build date",
                       "Confirm the build date and approve the project date",
                       "Project date approval", "Project venue acceptance",
                       "Cancellation of the project venue", "Project venue cancellation"):
            with self.subTest(option=option):
                decision["options"] = ["the owner", option]
                with self.assertRaisesRegex(Refusal, "scope"):
                    self.draft()

    def test_scope_actions_are_refused_despite_intervening_words(self):
        decision = self.payload["decisions"][0]
        for option in ("Approve the scope", "Approve the revised scope", "Approve the proposed scope",
                       "Stop the project", "Stop work on the project", "Stop working on the build",
                       "End all work on this project", "Halt the work on the current project",
                       "Sign off the build", "Sign off on the final build", "End this project",
                       "Scope approved", "Approve the draft scope", "Approve the full scope",
                       "Approve the agreed scope", "We approve all of the scope", "Accept the draft PRD",
                       "The scope is now approved", "Cancel the client project",
                       "Sign off on the draft scope", "Reject the draft scope",
                       "Approve after reading the entire packet, then approve all of the scope",
                       "At the end of the project, sign off on the draft scope",
                       "Confirm the build date and approve the draft scope",
                       "Approve, after we confirm the date for the build, the draft scope"):
            with self.subTest(option=option):
                decision["options"] = ["the owner", option]
                with self.assertRaisesRegex(Refusal, "scope"):
                    self.draft()

    def test_settled_keeps_exact_question_text_after_the_form_changes(self):
        settled = ["Who  used to check the list?"]
        self.payload["settled"] = settled
        content, digests = self.draft()
        self.assertEqual(content["settled"], settled)
        saved = dict(content, source_digests=digests)
        self.write("saved.json", json.dumps(saved))
        self.assertEqual(read_content(self.files, "saved.json", mode="docs", saved=True,
                                      check_live_proof=False), (saved, digests))

    def test_settled_refuses_invalid_duplicates_and_current_questions(self):
        for invalid in (None, "Who checked the list?", [False], [""], ["\uD800"],
                        ["Who checked the list?"] * 2, ["Who confirms the order?"]):
            with self.subTest(settled=invalid):
                self.payload["settled"] = invalid
                with self.assertRaisesRegex(Refusal, "settled"):
                    self.draft()

    def test_plain_project_document_and_path_boundaries(self):
        sentence = self.payload["document"][0]["sentences"][0]
        sentence["source"] = "docs/order  notes"
        self.write(sentence["source"], "The shop confirms each order with not decided.")
        self.draft()
        self.write("docs/weekly/notes.md", "The shop confirms each order with not decided.")
        hidden_link = self.root / "docs/notes.md"
        try:
            hidden_link.symlink_to(self.root / "docs/weekly/notes.md")
        except (OSError, NotImplementedError):
            self.skipTest("This system does not allow test symlinks.")
        for source in ("../notes.md", "docs/weekly/notes.md", "docs/notes.md"):
            with self.subTest(source=source):
                sentence["source"] = source
                with self.assertRaisesRegex(Refusal, "project document"):
                    self.draft()

    def test_draft_stamp_and_owner_evidence_without_project_docs(self):
        self.assertIsNone(read_approved_prd(self.files))
        self.assertTrue(prd_is_draft(self.files))
        sentence = self.payload["document"][0]["sentences"][0]
        sentence["source"] = "owner"
        with self.assertRaisesRegex(Refusal, "owner"):
            self.draft()
        (self.root / "docs/prd.md").unlink()
        (self.root / "docs/meeting-form.md").unlink()
        self.assertFalse(has_project_docs(self.files))
        self.assertFalse(prd_is_draft(self.files))
        content, digests = self.draft()
        self.assertEqual(content["document"][0]["sentences"][0]["source"], "owner")
        self.assertEqual(len(digests), 1)
