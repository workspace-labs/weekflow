"""Exercise approval-stamp setup through the meeting commands."""

import json
from os import linesep
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import test_docs_meetings as docs
from test_weekflow import TOOL, snapshot


APPROVAL_DATE = "2027-02-08"
DELIVERY_DATE = "2027-03-12"
LANGUAGES = {
    "en": {
        "title": "PRD: Bakery sample",
        "approved": "> v4 · Approved",
        "draft": "> v3 · Draft",
        "approver": "by the client",
        "note": "(kept the pickup hours (including Friday))",
        "bad_date": "on 8 February",
        "prose": "This idea is not approved yet.",
        "variants": (
            "> v4 · approved", "> v4 · APPROVED", "> v4 - Approved",
            "> v4 Approved", "> v4.1 · Approved", ">v4 · Approved", "v4 · Approved",
        ),
    },
    "ar": {
        "title": "متطلبات المنتج (PRD): مخبز تجريبي",
        "approved": "> الإصدار 4 · معتمد",
        "draft": "> الإصدار 3 · مسودة",
        "approver": "من العميل",
        "note": "(ثُبّت موعد الاستلام)",
        "bad_date": "في 8 فبراير",
        "prose": "المقترح غير معتمد بعد.",
        "variants": (
            "> الإصدار 4 - معتمد", "> الإصدار 4 معتمد", "> الإصدار 4.1 · معتمد",
            ">الإصدار 4 · معتمد", "الإصدار 4 · معتمد",
            "> الإصدار ٤ — مُعْتَمَد",
        ),
    },
}


class ApprovalStampTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)

    def project(self, *parts):
        project = self.root / "-".join(parts)
        (project / "docs").mkdir(parents=True)
        return project

    def write_prd(self, project, details, stamp):
        (project / "docs/prd.md").write_text(
            f"# {details['title']}\n{stamp}\n\n## Details\n", encoding="utf-8"
        )

    def invoke(self, project, command, language, *, expected=0):
        args = ["--planned-end", DELIVERY_DATE]
        if command == "start":
            args += ["--language", language, "--meeting-day", "Tuesday"]
        before = snapshot(project) if expected else None
        result = subprocess.run(
            [sys.executable, "-X", "utf8", str(TOOL), command, str(project), *args],
            cwd=self.root, capture_output=True, timeout=15,
        )
        output = (result.stdout + result.stderr).decode("utf-8")
        self.assertEqual(result.returncode, expected, output)
        if expected:
            self.assertEqual(snapshot(project), before)
        return output

    def setup_state(self, project):
        path = project / "docs/weekly/project.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_read_note_beside_approval_date(self):
        for language, details in LANGUAGES.items():
            for command in ("start", "enter-build"):
                for with_approver in (False, True):
                    with self.subTest(language=language, command=command, with_approver=with_approver):
                        project = self.project(language, command, str(with_approver))
                        if command == "enter-build":
                            self.write_prd(project, details, details["draft"])
                            self.invoke(project, "start", language)
                        stamp_fields = [details["approved"], APPROVAL_DATE]
                        if with_approver:
                            stamp_fields.append(details["approver"])
                        stamp_fields.append(details["note"])
                        self.write_prd(project, details, " ".join(stamp_fields))
                        output = self.invoke(project, command, language)

                        state = self.setup_state(project)
                        self.assertEqual(state["mode"], "build")
                        self.assertEqual(state["scope_approved_on"], APPROVAL_DATE)
                        self.assertEqual(state["planned_end"], DELIVERY_DATE)
                        self.assertTrue(any(APPROVAL_DATE in line and details["note"] in line
                                            for line in output.splitlines()), output)

    def test_refuse_unreadable_approval_at_its_source(self):
        for language, details in LANGUAGES.items():
            for command in ("start", "enter-build"):
                for unreadable in (details["bad_date"], "2027-02-30", f"{APPROVAL_DATE} ("):
                    with self.subTest(language=language, command=command, stamp=unreadable):
                        project = self.project(language, command, unreadable)
                        if command == "enter-build":
                            self.write_prd(project, details, details["draft"])
                            self.invoke(project, "start", language)
                        self.write_prd(project, details, f"{details['approved']} {unreadable}")
                        output = self.invoke(project, command, language, expected=2)

                        self.assertIn("docs/prd.md:2", output)
                        self.assertRegex(output.casefold(), r"approval|approved")
                        self.assertNotIn("Started in docs mode", output)

    def test_refuse_stamp_variants_and_misplaced_approval_at_the_actual_line(self):
        for language, details in LANGUAGES.items():
            candidates = (*details["variants"], "\n" + details["approved"])
            for command in ("start", "enter-build"):
                for index, candidate in enumerate(candidates):
                    line = 2 + candidate.count("\n")
                    with self.subTest(language=language, command=command, stamp=candidate):
                        project = self.project(language, command, str(index))
                        if command == "enter-build":
                            self.write_prd(project, details, details["draft"])
                            self.invoke(project, "start", language)
                        self.write_prd(project, details, f"{candidate} {APPROVAL_DATE}")
                        output = self.invoke(project, command, language, expected=2)

                        self.assertIn(f"docs/prd.md:{line}", output)
                        self.assertRegex(output.casefold(), r"approval|approved")
                        self.assertNotIn("Started in docs mode", output)

    def test_draft_and_unstamped_prds_still_start_docs_meetings(self):
        for language, details in LANGUAGES.items():
            for kind, stamp in (("draft", details["draft"]), ("unstamped", ""),
                                ("prose-on-line-2", details["prose"]),
                                ("prose-on-line-3", "\n" + details["prose"])):
                with self.subTest(language=language, stamp=kind):
                    project = self.project(language, kind)
                    self.write_prd(project, details, stamp)
                    output = self.invoke(project, "start", language)

                    self.assertIn("Started in docs mode.", output)
                    state = self.setup_state(project)
                    self.assertEqual(state["mode"], "docs")
                    self.assertEqual(state["scope_approved_on"], "")

    def test_recorded_docs_week_can_close_before_stamp_is_corrected(self):
        meeting = docs.DocsMeetingTests()
        meeting.setUp()
        self.addCleanup(meeting.doCleanups)
        meeting.start()
        meeting.write_draft()
        meeting.prepare()
        meeting.invoke("confirm")
        meeting.record("D-001=the manager")
        text = meeting.prd.read_text(encoding="utf-8")
        meeting.prd.write_text(text.replace("> v1 · Draft", f"> v2 · approved {APPROVAL_DATE}"),
                               encoding="utf-8")

        meeting.close()
        self.assertTrue(meeting.week()["locked_on"])
        self.assertIn("docs/prd.md:2", meeting.prepare("2026-08-22", succeeds=False))

    def test_existing_english_setup_output_matches_800de43(self):
        # Captured by running both commands from a local archive of 800de43.
        baseline = {
            "start": (
                "Weekly meetings are set up.\n"
                "Ask the owner once about client, an optional field.\n"
                "Ask the owner once about attendees, an optional field.\n"
            ),
            "enter-build": (
                "Entered build mode. Read scope approval date 2027-02-08 from docs/prd.md:2.\n"
                "Used planned_end 2027-03-12 supplied with --planned-end.\n"
            ),
        }
        details = LANGUAGES["en"]
        for command, expected in baseline.items():
            for number, suffix in enumerate(("", " by the client", " by (the client)",
                                             " by the client (review role) and the owner")):
                with self.subTest(command=command, approver=suffix):
                    project = self.project("legacy", command, str(number))
                    if command == "enter-build":
                        self.write_prd(project, details, details["draft"])
                        self.invoke(project, "start", "en")
                    self.write_prd(project, details, f"{details['approved']} {APPROVAL_DATE}{suffix}")
                    self.assertEqual(self.invoke(project, command, "en"), expected.replace("\n", linesep))


if __name__ == "__main__":
    unittest.main()
