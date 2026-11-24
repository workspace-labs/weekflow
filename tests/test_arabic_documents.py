"""Exercise Arabic source and draft protections with temporary files."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/weekflow/scripts"))

from weekflow_tool.content import read_content
from weekflow_tool.documents import prd_is_draft, read_approved_prd, read_meeting_form, read_project_name
from weekflow_tool.storage import ProjectFiles, Refusal


QUESTION = "من يؤكد الطلب؟"
FORM = f"""# نموذج اجتماع العميل: مخبز الحي

| العميل (الجهة، القسم) | إدارة المخبز |

## الاجتماعات التي عُقدت
| # | التاريخ والمكان | المرحلة | الحاضرون (اسم كل واحد ووظيفته) | ما تقرر |
|---|---|---|---|---|
| 2 | في المخبز | 1، 2 | المالك | |
| 4 | في المخبز | 3 | المالك؛ العميل | |

## ما زال مفتوحًا
| # | السؤال | سبب بقائه مفتوحًا (ناقص أو متعارض) |
|---|---|---|
| 1 | {QUESTION} | لم يُحسم |
| 10 | 10. القرار | لم يُحسم |

## المرحلة 4: اعتماد النطاق أو التوقف
### 10. القرار
| القرار | ✓ |
|---|---|
| معتمد | |
| تعديلات أولًا (مكتوبة أدناه، ثم اجتماع آخر للمرحلة 4) | |
| توقف (السبب أدناه) | |
"""

PRD = "# متطلبات المنتج (PRD): مخبز الحي\n"
QUOTE = "عند فتح المخبز، يراجع {D-001} القائمة."


class ArabicDocumentTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.files = ProjectFiles(self.root)
        self.write("docs/meeting-form.md", FORM)
        self.write("docs/prd.md", PRD + "> الإصدار 1 · مسودة\n\n"
                   + QUOTE.replace("{D-001}", "لم يُحسم"))
        self.decision = {"id": "D-001", "question": QUESTION, "why": "لم يُحسم بعد.",
                         "options": ["المالك", "العميل"]}
        self.sentence = {"text": QUOTE, "source": "docs/prd.md"}
        self.payload = {"headline": "طلبات الاستلام", "stage": 3,
                        "document": [{"title": "الطلبات", "sentences": [self.sentence]}],
                        "decisions": [self.decision]}

    def write(self, relative, content):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def read_draft(self, *, mode="docs", allowed_latin=()):
        self.write("draft.json", json.dumps(self.payload, ensure_ascii=False))
        return read_content(self.files, "draft.json", mode=mode, language="ar", allowed_latin=allowed_latin)

    def test_project_title_draft_approval_and_dates(self):
        self.assertTrue(prd_is_draft(self.files))
        self.assertIsNone(read_approved_prd(self.files))
        self.assertEqual(read_project_name(self.files, read_meeting_form(self.files)), "مخبز الحي")
        approved = PRD + "> الإصدار 2 · معتمد 2027-02-07 من العميل\n\n"
        dates = "- **المواعيد:** التسليم في 2027-03-12.\n"
        self.write("docs/prd.md", approved + dates)
        result = read_approved_prd(self.files)
        self.assertEqual((result.project, result.scope_approved_on), ("مخبز الحي", "2027-02-07"))
        self.assertEqual(result.planned_end.value, "2027-03-12")
        self.assertEqual(result.planned_end.number, 4)
        self.write("docs/prd.md", approved + dates +
                   "  - تغيّر في 2027-02-08: من 2027-03-12 إلى 2027-03-19، لأن الموعد تغيّر.\n")
        self.assertEqual(read_approved_prd(self.files).planned_end.value, "2027-03-19")
        for unresolved in ("لا موعد. اقتُرح 2027-03-12.", "لم يُحسم الموعد 2027-03-12.",
                           "تاريخ بدء المشروع: 2027-03-12.", "المشروع يبدأ في 2027-03-12.",
                           "بداية البناء في 2027-03-12.", "2027-03-12 أو 2027-03-19."):
            with self.subTest(unresolved=unresolved):
                self.write("docs/prd.md", approved + f"- **المواعيد:** {unresolved}\n")
                self.assertIsNone(read_approved_prd(self.files).planned_end)

    def test_form_number_stage_open_questions_and_stop(self):
        form = read_meeting_form(self.files)
        self.assertEqual((form.project, form.client), ("مخبز الحي", "إدارة المخبز"))
        self.assertEqual(form.attendees, ["المالك", "العميل"])
        self.assertEqual((form.last_number, form.latest_stage), (4, 3))
        self.assertEqual(form.stage_meetings, {1: 2, 2: 2, 3: 4})
        self.assertEqual(form.still_open, (QUESTION, "10. القرار"))
        self.assertFalse(form.stopped)
        marked = FORM.replace("| توقف (السبب أدناه) | |", "| توقف (السبب أدناه) | ✓ |")
        self.write("docs/meeting-form.md", marked)
        self.assertTrue(read_meeting_form(self.files).stopped)
        with self.assertRaisesRegex(Refusal, "stopped"):
            self.read_draft()
        row = "| 5 | في المخبز | 4 | العميل | توقّف: طلب العميل ذلك |\n"
        self.write("docs/meeting-form.md", FORM.replace("## ما زال", row + "\n## ما زال"))
        self.assertTrue(read_meeting_form(self.files).stopped)
        for checked in ("معتمد", "تعديلات أولًا (مكتوبة أدناه، ثم اجتماع آخر للمرحلة 4)"):
            self.write("docs/meeting-form.md", FORM.replace(f"| {checked} | |", f"| {checked} | ✓ |"))
            self.assertFalse(read_meeting_form(self.files).stopped)

    def test_scope_row_is_never_an_option_question(self):
        for question in ("10. القرار", "١٠. الْقَرَارُ؟", "10.\u200f القرَار"):
            with self.subTest(question=question):
                self.decision["question"] = question
                self.write("docs/meeting-form.md", FORM.replace("10. القرار | لم", question + " | لم"))
                with self.assertRaisesRegex(Refusal, "scope decision"):
                    self.read_draft()

    def test_scope_actions_are_refused_for_each_target_and_order(self):
        for action in ("اعتماد", "قبول", "الموافقة على", "التوقيع على", "رفض", "إيقاف", "إلغاء"):
            for target in ("النطاق", "المشروع", "البناء", "موعد النطاق", "تاريخ المشروع", "تاريخ البناء",
                           "مكان النطاق", "مكان المشروع", "مكان البناء"):
                with self.subTest(action=action, target=target):
                    self.decision["options"][1] = f"{action} بعد المراجعة {target}"
                    with self.assertRaisesRegex(Refusal, "cannot approve or stop"):
                        self.read_draft()
        for option in ("موعدُ البِناءِ مُعْتَمَد", "أعْتَمِدُ النِّطَاقَ", "إلْـغاء المَشْرُوع",
                       "تصديق موعدِ المَشروع", "وَقْفُ العمل على المشروع", "بدء البناء", "تَوَقَّفْ",
                       "إمْضاء على النِطاق", "أوْقِف المشرُوع", "اقبل المَشروع", "لِنُوقِّع البناء",
                       "المشروع مرفوض", "التوقيع على محلّ تنفيذ المشروع", "إيـقافُ الْمَشْروع",
                       "اعتماد مكان البناء", "لا تتابع المشروع", "مرفوض: بعد المراجعة",
                       "فَسَنُعْتَمِدُ الـمَشْرُوعَ", "تم الاعتماد", "وافق على مكان المشروع", "وقّع النطاق",
                       "إبطال الموافقة على مكان النِّطاق", "عدم اعتماد المشروع"):
            with self.subTest(option=option):
                self.decision["options"][1] = option
                with self.assertRaisesRegex(Refusal, "cannot approve or stop"):
                    self.read_draft()

    def test_names_cannot_hide_a_mixed_scope_option(self):
        self.payload["latin_names"] = ["Approve"]
        self.decision["options"][1] = "Approve المشروع"
        with self.assertRaisesRegex(Refusal, "cannot approve or stop"):
            self.read_draft()

    def test_project_approval_and_work_directives_stay_out_of_options(self):
        options = (
            ("اعتماد المسودة", "اِعْتِمادُ الـمَسْوَدَّه"),
            ("اعتماد الوثيقة", "اِعْتِمادُ الوَثِيقَه"),
            ("اعتماد الخطة", "اِعْتِمادُ الْخُطَّه"),
            ("إيقاف العمل", "ايقاف العَمَل"),
            ("أوقفوا العمل", "اَوْقِفُوا الْعَمَل"),
            ("إنهاء العمل", "اِنْهَاءُ الْعَمَل"),
            ("ابدأوا البناء", "اِبْدَؤُوا البِناء"),
            ("ابدأوا التنفيذ", "ٱبْدَأُوا التَّنْفِيذ"),
            ("انطلقوا في المشروع", "اِنْطَلِقُوا فِي الـمَشْرُوع"),
            ("اعتماد موعد التسليم", "اِعْتِمادُ مَوْعِدِ الـتَّسْلِيم"),
        )
        for spellings in options:
            for option in spellings:
                with self.subTest(option=option):
                    self.decision["options"][1] = option
                    with self.assertRaisesRegex(Refusal, "cannot approve or stop"):
                        self.read_draft()

    def test_ordinary_order_and_timing_options_stay_available(self):
        for option in ("إلغاء الطلب", "عند بدء الخبز", "في نهاية المشروع",
                       "قبل بدء المشروع", "بعد انتهاء البناء", "ساعات العمل", "بعد العمل",
                       "أثناء العمل", "قبل بدء العمل", "قَبْلَ بَدْءِ الْعَمَلِ", "موعد الاستلام",
                       "قبل التوقف عن العمل", "عند بدء العمل", "مكان العمل"):
            with self.subTest(option=option):
                self.decision["options"][1] = option
                self.assertEqual(self.read_draft()[0]["decisions"][0]["options"][1], option)

    def test_approval_and_work_start_stop_variants_stay_out_of_options(self):
        for option in ("اعتماد خطة العمل", "اِعْتِمادُ خُـطَّه الْعَمَلِ",
                       "اعتماد مسودة", "ٱعْتِمَادُ مَسْوَدَّه",
                       "توقفوا عن العمل", "تَوَقَّفُوا عَنِ الْعَمَلِ",
                       "التوقف عن العمل", "الـتَّوَقُّفُ عَنِ العَمَل",
                       "ابدأوا العمل", "ٱبْدَؤُوا الْعَمَلَ", "بدء العمل", "بَـدْءُ العَمَلِ",
                       "نبدأ العمل", "وَنَبْدَأُ الْعَمَلَ", "ابدأ الآن", "اِبْدَأْ الْآنَ",
                       "باشروا العمل", "أكملوا العمل"):
            with self.subTest(option=option):
                self.decision["options"][1] = option
                with self.assertRaisesRegex(Refusal, "cannot approve or stop"):
                    self.read_draft()

    def test_day_before_is_timing_but_acceptance_stays_out_of_options(self):
        for option in ("قبلها بيوم", "قَبْلَها بِيَوْمٍ"):
            with self.subTest(option=option):
                self.decision["options"][1] = option
                self.assertEqual(self.read_draft()[0]["decisions"][0]["options"][1], option)
        for option in ("قبلها", "قبلها العميل", "قَبِلَها بيوم", "قبلها بيوم، نعتمد المشروع"):
            with self.subTest(option=option):
                self.decision["options"][1] = option
                with self.assertRaisesRegex(Refusal, "cannot approve or stop"):
                    self.read_draft()

    def test_scope_actions_with_possessives_future_past_and_object_pronouns(self):
        for option in ("موافقتنا النهائية على المشروع", "تمّت مصادقتنا على مكان النطاق",
                       "إمضاؤنا على موعد البناء", "توقيعنا على مكان البناء", "ألغِ موعد التنفيذ",
                       "سيوقع العميل على النطاق", "سيقِرّ المالك موعد المشروع", "وافقنا على المشروع",
                       "قَبِل المالك المشروع", "قبل المالك المشروع", "المشروع قُبِل بعد المراجعة",
                       "نعطي الضوء الأخضر للبناء", "اعتمدناه بعد المراجعة", "قبله المالك",
                       "نوافق عليه بعد المراجعة", "توقيعنا النهائي عليه", "سنلغيها إذا تعذّر العمل",
                       "رفضناه صباحًا", "أوقفوه فورًا", "اعتماده كما هو", "قبل نهاية الأسبوع، نوافق عليه",
                       "قبل أن نعتمده، يجب توقيعه", "تمت الموافقة", "المشروع موقّع",
                       "في نهاية المشروع، تابع البناء"):
            with self.subTest(option=option):
                self.decision["options"][1] = option
                with self.assertRaisesRegex(Refusal, "cannot approve or stop"):
                    self.read_draft()

    def test_localized_deferral_stays_reserved(self):
        self.decision["options"][1] = "نقرر الأسبوع المقبل"
        with self.assertRaisesRegex(Refusal, "Decide next week"):
            self.read_draft()

    def test_allows_timing_and_choosing_who_can_approve(self):
        (self.root / "docs/meeting-form.md").unlink()
        self.decision["question"] = "من يعتمد النطاق؟"
        for option in ("في نهاية المشروع", "قبل انتهاء المشروع", "عند بدء البناء", "قبل موعد المشروع",
                       "قبل المشروع", "بعد أن ينتهي البناء", "بعد اعتماد الطلب اليومي",
                       "بعد توقيعه", "موقع البناء", "مقر المشروع", "موقعه في المتجر",
                       "تأكيد موعد البناء", "تأكيد مكان المشروع"):
            with self.subTest(option=option):
                self.decision["options"][1] = option
                self.assertEqual(self.read_draft()[0]["decisions"][0]["options"][1], option)

    def test_handles_arabic_punctuation_direction_marks_and_placeholders(self):
        for placeholder in ("TBD", "لم يُحسم", "\u200fلم يُحسم\u200e"):
            with self.subTest(placeholder=placeholder):
                self.write("docs/prd.md", QUOTE.replace("{D-001}", placeholder) + " متى يبدأ العميل؟")
                self.assertEqual(self.read_draft()[0]["document"][0]["sentences"][0]["text"], QUOTE)
        self.sentence["text"] = "عند فتح المخبز، يراجع {D-001} القائمة؟"
        self.write("docs/prd.md", "عند فتح المخبز،\u200f يراجع لم يُحسم القائمة؟ ثم يبدأ العمل.")
        self.read_draft()

    def test_quotes_cannot_invent_or_cross_sentence_and_block_boundaries(self):
        for source in ("عند فتح المخبز، يراجع المالك الفاتورة.",
                       "عند فتح المخبز، يراجع المالك أمرًا. ثم يبدأ العمل بالقائمة.",
                       "عند فتح المخبز، يراجع المالك أمرًا؟ ثم يبدأ العمل بالقائمة.",
                       "عند فتح المخبز، يراجع المالك أمرًا؛ ثم يبدأ العمل بالقائمة.",
                       "عند فتح المخبز، يراجع المالك أمرًا، ثم يطبع القائمة.",
                       "- عند فتح المخبز، يراجع المالك أمرًا\n- يبدأ العمل حسب القائمة."):
            with self.subTest(source=source):
                self.write("docs/prd.md", source)
                with self.assertRaisesRegex(Refusal, "not found"):
                    self.read_draft()
        self.payload["decisions"] = []
        self.sentence["text"] = "يفتح المخبز. يراجع المالك القائمة."
        self.write("docs/prd.md", self.sentence["text"])
        with self.assertRaisesRegex(Refusal, "not found"):
            self.read_draft()

    def test_rejects_an_english_sentence_and_names_its_field(self):
        self.payload["headline"] = "راجع القائمة. The client will collect the order."
        with self.assertRaisesRegex(Refusal, "headline"):
            self.read_draft()
        self.payload["headline"] = "طلبات الاستلام"
        self.decision["options"][1] = "The client packs the bread."
        with self.assertRaisesRegex(Refusal, "option for D-001"):
            self.read_draft()
        self.decision["options"][1] = "العميل"
        self.payload["next_week"] = [{"text": "The client collects the order."}]
        with self.assertRaisesRegex(Refusal, "item 1 in next_week"):
            self.read_draft(mode="build")

    def test_allows_exact_names_without_translating_and_records_declarations(self):
        self.payload["headline"] = "يراجع Sam Lee الطلبات في MenuTool."
        self.payload["latin_names"] = ["MenuTool"]
        content, _ = self.read_draft(allowed_latin=("Sam Lee",))
        self.assertEqual(content["headline"], self.payload["headline"])
        self.assertEqual(content["latin_names"], ["MenuTool"])
        self.payload["headline"] = "يراجع Sam Leeman الطلبات."
        with self.assertRaisesRegex(Refusal, "headline"):
            self.read_draft(allowed_latin=("Sam Lee",))
        self.payload["latin_names"] = ["The client collects the order"]
        with self.assertRaisesRegex(Refusal, "latin_names"):
            self.read_draft()

    def test_a_latin_sentence_cannot_be_declared_one_word_at_a_time(self):
        self.payload["headline"] = "القائمة جاهزة. The menu is ready."
        self.payload["latin_names"] = ["The", "menu", "is", "ready"]
        with self.assertRaisesRegex(Refusal, "headline"):
            self.read_draft()
        self.payload["headline"] = "قائمة MenuTool، وراجعها Sam Lee."
        self.payload["latin_names"] = ["MenuTool", "Sam Lee"]
        self.assertEqual(self.read_draft()[0]["headline"], self.payload["headline"])

    def test_saved_content_allows_an_empty_name_list_after_redaction(self):
        self.payload["latin_names"] = []
        content, digests = self.read_draft()
        saved = dict(content, source_digests=digests)
        self.write("saved.json", json.dumps(saved))
        self.assertEqual(read_content(self.files, "saved.json", mode="docs", language="ar", saved=True,
                                      check_live_proof=False), (saved, digests))
