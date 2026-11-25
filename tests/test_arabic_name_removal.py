"""Check that Arabic name removal reaches only approved words in locked weeks."""

import json
import re
import subprocess
import unittest
from datetime import date
from unicodedata import normalize

import test_arabic_lifecycle as lifecycle
import test_weekflow as fixture
from weekflow_tool.meetings import content_file


WORD_PAIRS = (
    ("علي", "على", "نراجع القائمة على الموقع."),
    ("ريم", "كريم", "أرسل الملف مع كريم."),
    ("سام", "وسام", "استقبل وسام."),
    ("نور", "النور", "شاهد النور."),
    ("أمل", "الأمل", "وجد الأمل."),
    ("أمل", "امل", "وجد امل."),
    ("ليلى", "ليلي", "موعد ليلي."),
    ("هدى", "هدي", "عرض هدي."),
)
EXACT_FORMS = ("سارة", "سارَة", "سـارة")
OWNER_DECISIONS = (
    ("إرسال الملف لسارة.", "لسارة", "--also"),
    ("توقيع وسارة.", "وسارة", "--also"),
    ("ملف بسارة.", "بسارة", "--also"),
    ("حضر المالك فسارة.", "فسارة", "--also"),
    ("أعمل كسارة.", "كسارة", "--keep"),
    ("حضرت السارة.", "السارة", "--also"),
    ("جهّز الملف وبالسارة.", "وبالسارة", "--also"),
    ("أرسل الملف للسارة.", "للسارة", "--also"),
    ("استقبل ساره.", "ساره", "--also"),
)
OTHER_TEXT = "ناقش خسارة الطلب وعبارة سارةان."
COPIED_FORMS = (
    ("سا\u200fرة", "تفاحة"),
    ("سا\u200dرة", "برتقالة"),
    ("سا\u200cرة", "كمثرى"),
    ("ﺳﺎﺭﺓ", "ليمونة"),
)


def whole_word(word):
    return re.compile(rf"(?<!\w){re.escape(word)}(?!\w)")


class ArabicNameRemovalTests(unittest.TestCase):
    def make_meeting(self, promises, *, draw=False):
        meeting = lifecycle.ArabicLifecycleTests()
        meeting.setUp()
        self.addCleanup(meeting.doCleanups)
        meeting.start_build()
        meeting.build_draft(next_week=[{"text": text} for text in promises])
        meeting.prepare_week("2026-11-08")
        meeting.record_build()
        meeting.copy_pdf(5, setup="" if draw else fixture.TEST_PDF_RENDERER)
        meeting.succeed("lock")
        return meeting

    def remove(self, meeting, name, *options, draw=False):
        result = meeting.command(*self.removal(name, *options),
                                 setup="" if draw else fixture.TEST_PDF_RENDERER)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Changed weeks 5.", result.stdout)

    def removal(self, name, *options, reason="الخصوصية"):
        return ("remove-name", "--name", name, "--what", "إزالة اسم",
                "--reason", reason, "--by", "المالك", *options)

    def saved_texts(self, meeting):
        return (meeting.weekly / "promises.json", meeting.project / content_file(5),
                meeting.pages / "week-5.html")

    def drawn_line(self, pdf, word):
        drawn = subprocess.check_output(["pdftotext", "-enc", "UTF-8", str(pdf), "-"], text=True, encoding="utf-8", timeout=15)
        return [line.encode("utf-8") for line in drawn.splitlines()
                if whole_word(word).search(normalize("NFKC", line))]

    def test_every_possible_word_requires_an_owner_decision_without_writing(self):
        meeting = self.make_meeting(["راجع الملف مع سارة.", "إرسال الملف لسارة.",
                                     "موعد لسارة.", "حضر المالك وسارة.", "أعمل كسارة."])
        output = meeting.refuse(*self.removal("سارة"))
        for word in ("لسارة", "وسارة", "كسارة"):
            self.assertEqual(len(whole_word(word).findall(output)), 1, output)
        self.assertNotRegex(output, whole_word("سارة"))

        partial = meeting.refuse(*self.removal("سارة", "--also", "لسارة", "--keep", "وسارة"))
        self.assertRegex(partial, whole_word("كسارة"))
        complete = ("--also", "لسارة", "--keep", "وسارة", "--keep", "كسارة")
        for extra in (("--also", "مريم"), ("--keep", "مريم"), ("--keep", "سارة"),
                      ("--keep", "لسارة")):
            with self.subTest(extra=extra):
                meeting.refuse(*self.removal("سارة", *complete, *extra))

    def test_arabic_removal_details_must_also_leave_out_exact_and_possible_names(self):
        meeting = self.make_meeting(["راجع الملف مع سارة."])
        for word in ("سارَة", "ساره"):
            with self.subTest(word=word):
                output = meeting.refuse(*self.removal("سارة", reason=f"تخص {word}"))
                self.assertIn("Use removal details that leave out the name.", output)

    def test_keep_leaves_an_extra_weekly_file_byte_identical(self):
        meeting = self.make_meeting(["راجع الملف مع علي."])
        extra = meeting.weekly / "notes.txt"
        original = "نراجع القائمة على الموقع.\n".encode("utf-8")
        extra.write_bytes(original)

        self.assertRegex(meeting.refuse(*self.removal("علي")), whole_word("على"))
        before = fixture.snapshot(meeting.scratch)
        result = meeting.command(*self.removal("علي", "--also", "على"), setup=fixture.TEST_PDF_RENDERER)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("still contains the name", result.stderr)
        self.assertEqual(fixture.snapshot(meeting.scratch), before)
        self.remove(meeting, "علي", "--keep", "على")
        self.assertEqual(extra.read_bytes(), original)
        for path in self.saved_texts(meeting):
            self.assertNotRegex(path.read_text(encoding="utf-8"), whole_word("علي"))

    def test_exact_forms_are_removed_and_owner_can_decide_several_other_words(self):
        promises = [f"راجع مع {word}." for word in EXACT_FORMS]
        promises += [line for line, _, _ in OWNER_DECISIONS] + [OTHER_TEXT]
        meeting = self.make_meeting(promises)
        flags = [value for _, word, flag in OWNER_DECISIONS for value in (flag, word)]
        self.remove(meeting, "سارة", *flags)
        for path in self.saved_texts(meeting):
            with self.subTest(file=path.name):
                after = path.read_text(encoding="utf-8")
                for word in EXACT_FORMS:
                    self.assertNotRegex(after, whole_word(word))
                for line, word, flag in OWNER_DECISIONS:
                    if flag == "--also":
                        self.assertNotRegex(after, whole_word(word))
                    else:
                        self.assertIn(line, after)
                self.assertIn(OTHER_TEXT, after)
                self.assertIn("أُزيل في", after)

    def test_copied_forms_need_an_owner_decision_and_keep_their_original_bytes(self):
        sentences = [(word, f"راجع {marker} مع {word}.") for word, marker in COPIED_FORMS]
        for flag in ("--also", "--keep"):
            with self.subTest(decision=flag):
                meeting = self.make_meeting(["راجع الملف مع سارة.", *(line for _, line in sentences)])
                paths = self.saved_texts(meeting)
                output = meeting.refuse(*self.removal("سارة"))
                for word, line in sentences:
                    self.assertIn(f"Possible word: {word!r}.", output)
                    for path in paths:
                        self.assertIn(line.encode("utf-8"), path.read_bytes())

                choices = [part for word, _ in sentences for part in (flag, word)]
                self.remove(meeting, "سارة", *choices)

                for path in paths:
                    with self.subTest(file=path.name):
                        after = path.read_bytes()
                        self.assertNotIn("سارة".encode("utf-8"), after)
                        for word, line in sentences:
                            if flag == "--keep":
                                self.assertIn(line.encode("utf-8"), after)
                            else:
                                self.assertNotIn(word.encode("utf-8"), after)
                        if flag == "--also":
                            for char in "\u200f\u200d\u200c":
                                self.assertNotIn(char.encode("utf-8"), after)

    @unittest.skipUnless(fixture.PDF_TEXT, "ReportLab and pdftotext are required for redrawn PDF checks")
    def test_copied_forms_are_removed_or_kept_in_the_drawn_pdf(self):
        for flag in ("--also", "--keep"):
            with self.subTest(decision=flag):
                meeting = self.make_meeting(["راجع الملف مع سارة.", *(
                    f"راجع {marker} مع {word}." for word, marker in COPIED_FORMS
                )], draw=True)
                pdf = meeting.pages / "week-5.pdf"
                before = {marker: self.drawn_line(pdf, marker) for _, marker in COPIED_FORMS}
                self.assertEqual(len(self.drawn_line(pdf, "سارة")), len(COPIED_FORMS) + 1)
                for lines in before.values():
                    self.assertTrue(any("سارة" in normalize("NFKC", line.decode("utf-8")) for line in lines))

                choices = [part for word, _ in COPIED_FORMS for part in (flag, word)]
                self.remove(meeting, "سارة", *choices, draw=True)

                self.assertTrue(self.drawn_line(pdf, "أُزيل"))
                if flag == "--keep":
                    self.assertEqual(len(self.drawn_line(pdf, "سارة")), len(COPIED_FORMS))
                    for marker, lines in before.items():
                        self.assertEqual(self.drawn_line(pdf, marker), lines)
                else:
                    self.assertFalse(self.drawn_line(pdf, "سارة"))
                    for marker in before:
                        self.assertTrue(self.drawn_line(pdf, marker))

    @unittest.skipUnless(fixture.PDF_TEXT, "ReportLab and pdftotext are required for redrawn PDF checks")
    def test_keeping_all_copied_forms_leaves_the_locked_week_byte_identical(self):
        meeting = self.make_meeting([f"راجع {marker} مع {word}." for word, marker in COPIED_FORMS], draw=True)
        before = fixture.snapshot(meeting.scratch)
        choices = [part for word, _ in COPIED_FORMS for part in ("--keep", word)]

        output = meeting.succeed(*self.removal("سارة", *choices))

        self.assertIn("No weeks changed.", output)
        self.assertEqual(fixture.snapshot(meeting.scratch), before)

    def test_also_and_keep_preserve_the_intended_bytes_in_records_and_page(self):
        for name, variant, sentence in WORD_PAIRS:
            for flag in ("--also", "--keep"):
                with self.subTest(name=name, variant=variant, decision=flag):
                    meeting = self.make_meeting([f"راجع الملف مع {name}.", sentence])
                    paths = self.saved_texts(meeting)
                    for path in paths:
                        self.assertIn(sentence.encode("utf-8"), path.read_bytes())
                    if flag == "--keep":
                        self.assertRegex(meeting.refuse(*self.removal(name)), whole_word(variant))
                    before = fixture.snapshot(meeting.weekly)

                    self.remove(meeting, name, flag, variant)

                    for path in paths:
                        value = path.read_text(encoding="utf-8")
                        self.assertNotRegex(value, whole_word(name))
                        self.assertIn("أُزيل في", value)
                        if flag == "--also":
                            self.assertNotRegex(value, whole_word(variant))
                        else:
                            self.assertIn(sentence.encode("utf-8"), path.read_bytes())
                    for relative, raw in fixture.snapshot(meeting.weekly).items():
                        if not relative.endswith(".json"):
                            continue
                        with self.subTest(record=relative):
                            self.assertNotIn(b"--also", raw)
                            self.assertNotIn(b"--keep", raw)
                            original = before.get(relative, b"").decode("utf-8")
                            count = len(whole_word(variant).findall(original)) if flag == "--keep" else 0
                            self.assertEqual(len(whole_word(variant).findall(raw.decode("utf-8"))), count)
                    corrections = json.loads((meeting.weekly / "corrections.json").read_bytes())
                    self.assertEqual(corrections, [{"id": "X-001", "week": 5, "kind": "removal",
                                                   "date": date.today().isoformat(), "what": "إزالة اسم",
                                                   "reason": "الخصوصية", "by": "المالك"}])

    @unittest.skipUnless(fixture.PDF_TEXT, "ReportLab and pdftotext are required for redrawn PDF checks")
    def test_also_and_keep_preserve_the_intended_text_in_the_drawn_pdf(self):
        for name, variant, sentence in WORD_PAIRS:
            for flag in ("--also", "--keep"):
                with self.subTest(name=name, variant=variant, decision=flag):
                    meeting = self.make_meeting([f"راجع الملف مع {name}.", sentence], draw=True)
                    pdf = meeting.pages / "week-5.pdf"
                    before = self.drawn_line(pdf, variant)
                    self.assertTrue(before)
                    self.assertTrue(self.drawn_line(pdf, name))

                    self.remove(meeting, name, flag, variant, draw=True)

                    self.assertFalse(self.drawn_line(pdf, name))
                    self.assertEqual(self.drawn_line(pdf, variant), before if flag == "--keep" else [])
                    self.assertTrue(self.drawn_line(pdf, "أُزيل"))

    @unittest.skipUnless(fixture.PDF_TEXT, "ReportLab and pdftotext are required for redrawn PDF checks")
    def test_exact_forms_and_owner_selected_words_are_removed_from_drawn_pdf(self):
        promises = [f"راجع مع {word}." for word in EXACT_FORMS]
        promises += [line for line, _, _ in OWNER_DECISIONS] + [OTHER_TEXT]
        meeting = self.make_meeting(promises, draw=True)
        pdf = meeting.pages / "week-5.pdf"
        words = (*EXACT_FORMS, *(word for _, word, _ in OWNER_DECISIONS))
        before = {word: self.drawn_line(pdf, word) for word in words}
        self.assertTrue(all(before.values()), before)
        flags = [value for _, word, flag in OWNER_DECISIONS for value in (flag, word)]
        self.remove(meeting, "سارة", *flags, draw=True)
        for word in words:
            self.assertEqual(self.drawn_line(pdf, word), before[word] if word == "كسارة" else [])
        self.assertTrue(self.drawn_line(pdf, "خسارة"))
        self.assertTrue(self.drawn_line(pdf, "سارةان"))
