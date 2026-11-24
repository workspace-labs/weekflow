"""Check all visible copy on the Arabic meeting pages."""

from html.parser import HTMLParser
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/weekflow/scripts"))

from weekflow_tool.meeting_design import studio_design
from weekflow_tool.meeting_language import ARABIC
from weekflow_tool.page import MeetingView
from weekflow_tool.page_html import render_html


class MeetingMarkup(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.language = None
        self.direction = None
        self.non_copy_tag = None
        self.copy = []
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("style", "script"):
            self.non_copy_tag = tag
        if tag == "html":
            self.language, self.direction = attrs["lang"], attrs["dir"]
        self.copy.extend(attrs[key] for key in ("alt", "aria-label") if key in attrs)

    def handle_endtag(self, tag):
        if tag == self.non_copy_tag:
            self.non_copy_tag = None

    def handle_data(self, data):
        if self.non_copy_tag is None:
            self.copy.append(data)


class ArabicPageTests(unittest.TestCase):
    def view(self, mode, *, empty=False):
        day = "2027-03-12"
        project = {"project": "مخبز الحي", "client": "إدارة المخبز",
                   "scope_approved_on": "2027-02-08", "planned_end": day,
                   "attendees": ["المالك", "Dana"], "language": "ar"}
        week = {"number": 3, "meeting_date": "2027-02-26", "mode": mode,
                "held": False, "end_before": day}
        content = {"headline": "جاهزية قائمة الخبز", "finished": [], "next_week": [],
                   "needs": [] if empty else [{"text": "وقت الاستلام", "by": day}],
                   "meeting_promises": [{"status": "not finished", "what": "عرض القائمة"}],
                   "missed_meetings": ["2027-02-19"], "corrections": [
                       {"kind": "removal", "date": day, "week": 1, "by": "المالك",
                        "reason": "الخصوصية", "what": "إزالة صورة"},
                   ]}
        changes = []
        screens = []
        if mode == "docs":
            content.update(stage=3, stage_meetings={"1": 1, "2": 2}, settled=["هل تُعرض الأسعار؟"],
                           decisions=[], document=[])
            if not empty:
                content["decisions"].append({"id": "D-001", "question": "من يؤكد الطلب؟",
                                             "why": "تحديد المسؤول", "options": ["المدير", "العميل"]})
                content["document"].append({"title": "الطلبات", "sentences": [
                    {"text": "يؤكد {D-001} الطلب."},
                ]})
        elif not empty:
            changes.append({"id": "C-001", "what": "إضافة خيار للتسليم", "reason": "طلب العميل",
                            "asked_by": "Dana", "date": day, "days_added": 3})
            screens.append({"id": "summary", "state": "not built", "name": "ملخص الطلب",
                            "current": None, "previous": None})
            content["app_ran"] = False
        return MeetingView(project, week, content, changes, [],
                           screen_map=screens, design=studio_design("ar"))

    def test_no_fixed_english_copy_in_either_arabic_page(self):
        fixed = tuple(label for label in ARABIC if "{" not in label)
        for mode in ("docs", "build"):
            for empty in (False, True):
                with self.subTest(mode=mode, empty=empty):
                    markup = render_html(self.view(mode, empty=empty))
                    parsed = MeetingMarkup(markup)
                    copy = " ".join(parsed.copy)
                    self.assertEqual((parsed.language, parsed.direction), ("ar", "rtl"))
                    for label in fixed:
                        self.assertNotRegex(copy, r"\b" + re.escape(label) + r"\b")
                    self.assertEqual(set(re.findall(r"[A-Za-z]+", copy)), {"Dana"})
                    self.assertIn("26 فبراير 2027", copy)
                    self.assertIn("12 مارس 2027", copy)
                    self.assertIn("حفظ الإجابات", copy)
                    self.assertEqual(markup.count("<script>"), 1)
                    self.assertEqual(markup.count('font-family:"Meeting Arabic"'), 2)

    def test_external_assets_stay_off_and_build_counter_words_are_arabic(self):
        markup = render_html(self.view("build"))
        self.assertIn("default-src 'none'; script-src 'sha256-", markup)
        self.assertIn("font-src data:; img-src data:", markup)
        self.assertNotIn("Date outside preview range", markup)
        self.assertNotIn("No days added", markup)
        self.assertIn("التاريخ خارج نطاق المعاينة", markup)
        self.assertIn("لا أيام إضافية", markup)
