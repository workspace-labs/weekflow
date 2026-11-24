"""Check the docs content in the revised offline meeting page."""

from dataclasses import replace
import unittest

import test_arabic_page as arabic_page

from weekflow_tool.meeting_design import studio_design
from weekflow_tool.page import MeetingView
from weekflow_tool.page_html import render_html


def revised(view):
    return replace(view, design=replace(view.design, page_layout="a"))


def docs_view():
    project = {"project": "Corner Bakery", "client": "Corner Bakery shop",
               "attendees": ["the owner", "the client"]}
    week = {"number": 3, "meeting_date": "2026-08-15", "mode": "docs", "held": False}
    decision = {"id": "D-001", "question": "Who confirms pickup?", "why": "Pick one person.",
                "said": [{"who": "the client", "what": "I can confirm it."}],
                "options": ["the client", "the manager"]}
    content = {
        "headline": "Pickup orders", "stage": 3, "stage_meetings": {"1": 1, "2": 2},
        "document": [{"title": "How orders run", "sentences": [{"text": "{D-001} confirms pickup."}]}],
        "settled": ["Is the shop open?"], "decisions": [decision],
        "next_week": [{"text": "Review pickup times."}], "needs": [],
    }
    return MeetingView(project, week, content, [], [], design=studio_design())


class DocsLayoutATests(unittest.TestCase):
    def test_docs_stages_and_response_tiles_keep_the_native_answers(self):
        html = render_html(revised(docs_view()))

        self.assertIn('class="docs-stage-panel"', html)
        self.assertIn('class="docs-header docs-header-a"', html)
        self.assertEqual(html.count('class="docs-stage-mark"'), 4)
        self.assertIn('<li aria-current="step"><span class="docs-stage-mark"', html)
        self.assertIn('Held in meeting 1', html)
        self.assertIn('Delivery date is set when the scope is approved', html)
        self.assertIn('aria-label="Who confirms pickup?"', html)
        self.assertIn('<bdi class="decision-id">D-001</bdi>', html)
        self.assertIn('the client · I can confirm it.', html)
        self.assertIn('class="answer-impact">Resolves this decision', html)
        self.assertIn('class="answer-impact">Keeps this decision open', html)
        self.assertIn('id="docs-decision-1-later" value="later"', html)
        self.assertIn('body:has(#docs-decision-1 input:checked:not([value="later"]))', html)
        self.assertIn('This record does not approve the scope.', html)
        self.assertIn('Settled outside the meeting', html)
        self.assertIn('class="items checklist upcoming"', html)
        self.assertIn('Nothing is needed from the client.', html)
        self.assertIn('id="save-answers"', html)
        self.assertEqual(html.count('<script>'), 1)

    def test_docs_empty_panels_and_completed_count_remain(self):
        view = docs_view()
        view = replace(view, content=dict(view.content, document=[], decisions=[], next_week=[]))
        html = render_html(revised(view))

        self.assertIn('body .docs-header .docs-complete { display: inline; }', html)
        self.assertIn('No document sentences are listed.', html)
        self.assertIn('No decisions are waiting.', html)
        self.assertIn('No items are planned for next week.', html)
        self.assertIn('Nothing is needed from the client.', html)

    def test_arabic_stages_and_answer_effects_are_localized(self):
        view = arabic_page.ArabicPageTests().view("docs")
        html = render_html(revised(view))

        self.assertIn('<html lang="ar" dir="rtl">', html)
        self.assertEqual(html.count('class="docs-stage-mark"'), 4)
        self.assertIn('عُقد في الاجتماع 1', html)
        self.assertIn('يحسم هذا القرار', html)
        self.assertIn('يبقي هذا القرار مفتوحًا', html)
        for english in ('Resolves this decision', 'Keeps this decision open', 'Left to decide'):
            self.assertNotIn(english, html)
