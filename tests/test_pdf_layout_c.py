"""Check Layout C content, placement, and pagination on client PDFs."""

from dataclasses import replace
from datetime import date, timedelta
from io import BytesIO
import subprocess
import sys
import unittest
from unittest.mock import patch
from xml.etree import ElementTree

from test_carryover_render import carryover_view
from test_recorded_meeting import PDFTOTEXT, REPORTLAB, RecordedMeetingFixture
from test_screen_render import screen_view
from test_weekflow import TOOL, cli_date_setup

sys.path.insert(0, str(TOOL.parent))

from weekflow_tool.client_pdf import render_pdf
from weekflow_tool.meeting_design import PDF_LAYOUT_C_REVISED, studio_design, with_pdf_paper
from weekflow_tool.page import MeetingView


def extract(pdf, option="-raw"):
    return subprocess.run(
        [PDFTOTEXT, option, "-", "-"], input=pdf, check=True, capture_output=True,
        timeout=15,
    ).stdout.decode()


def layout_c(view):
    design, _ = with_pdf_paper(studio_design(view.language), "design", layout=PDF_LAYOUT_C_REVISED)
    return replace(view, design=design)


def first_page_words(pdf):
    document = ElementTree.fromstring(extract(pdf, "-bbox"))
    page = document.find(".//{*}page")
    return float(page.attrib["width"]), page.findall(".//{*}word")


def normalise(text):
    # Poppler raw mode follows drawing order but can omit visual word spacing.
    return "".join(text.casefold().split())


@unittest.skipUnless(REPORTLAB, "ReportLab is required for the delivery date panel")
class DateTrackPositionTests(unittest.TestCase):
    def assert_labels_fit(self, centers, label_widths, width):
        boxes = sorted((center - size / 2, center + size / 2)
                       for center, size in zip(centers, label_widths))
        self.assertEqual(len(boxes), len(label_widths))
        self.assertGreaterEqual(boxes[0][0], -1e-9)
        self.assertLessEqual(boxes[-1][1], width + 1e-9)
        for left, right in zip(boxes, boxes[1:]):
            self.assertLess(left[1], right[0])

    def test_wide_label_positions_fit_and_mirror_at_close_and_yearlong_gaps(self):
        from weekflow_tool.pdf_date_track import date_track_positions

        start = date(2026, 2, 26).toordinal()
        width = 470
        for gap in (0, 1, 2, 14, 365):
            # Check crowding both around today and around the planned delivery date.
            for span in ((0, gap), (0, 14, 14 + gap), (0, gap, gap + 14)):
                with self.subTest(gap=gap, days=span):
                    days = [start + offset for offset in span]
                    label_widths = (90, 65, 108)[:len(days)]
                    dots, labels, breakpoint = date_track_positions(days, label_widths, width)
                    mirrored_dots, mirrored_labels, mirrored_break = date_track_positions(
                        days, label_widths, width, rtl=True,
                    )

                    self.assertEqual(len(dots), len(days))
                    self.assertGreaterEqual(min(dots), 0)
                    self.assertLessEqual(max(dots), width)
                    for index, (dot, label) in enumerate(zip(dots, labels)):
                        self.assertAlmostEqual(dot + mirrored_dots[index], width)
                        self.assertAlmostEqual(label + mirrored_labels[index], width)
                    if breakpoint is None:
                        self.assertIsNone(mirrored_break)
                    else:
                        self.assertAlmostEqual(breakpoint + mirrored_break, width)
                    self.assert_labels_fit(labels, label_widths, width)
                    self.assert_labels_fit(mirrored_labels, label_widths, width)

    def test_drawn_axis_keeps_dots_on_line_and_marks_adjusted_spacing(self):
        from reportlab.lib.colors import HexColor
        from reportlab.pdfgen.canvas import Canvas
        from weekflow_tool.client_pdf import pdf_styles, register_fonts
        from weekflow_tool.pdf_date_track import DateTrack
        from weekflow_tool.pdf_layout_c import MeetingPdfLayout

        base = carryover_view()
        meeting_date = date(2026, 11, 8)
        width = 475.14
        long_gaps = [(planned, planned + move) for planned in (30, 120, 365) for move in (1, 2)]
        cases = [(planned, current, True) for planned, current in long_gaps]
        cases += [(2, 4, False), (3, 4, False), (14, 21, False), (0, 0, False), (0, 1, False),
                  (-1, 0, False), (-124, -122, True)]

        for planned, current, squeezed in cases:
            track_positions = []
            for language in ("en", "ar"):
                with self.subTest(planned=planned, current=current, language=language):
                    view = layout_c(replace(
                        base, project=dict(base.project, language=language),
                        week=dict(base.week, meeting_date=meeting_date.isoformat(),
                                  end_before=(meeting_date + timedelta(days=planned)).isoformat(),
                                  end_after=(meeting_date + timedelta(days=current)).isoformat()),
                    ))
                    fonts = register_fonts(view.design)
                    styles = pdf_styles(view.design, fonts, language=language)
                    track = DateTrack(MeetingPdfLayout(view, styles, width, 750))
                    track.wrap(width, 750)
                    canvas = Canvas(BytesIO())
                    grey = HexColor(view.design.colors["lines"])
                    main = HexColor(view.design.colors["main"])
                    strokes = []
                    line = canvas.line

                    def capture_line(x1, y1, x2, y2):
                        strokes.append((canvas._strokeColorObj, x1, y1, x2, y2))
                        line(x1, y1, x2, y2)

                    with patch.object(canvas, "line", side_effect=capture_line), \
                            patch.object(canvas, "lines", wraps=canvas.lines) as marks, \
                            patch.object(canvas, "circle", wraps=canvas.circle) as circles:
                        track.drawOn(canvas, 0, 0)

                    dots = [call.args[:2] for call in circles.call_args_list]
                    self.assertEqual(len(dots), 3 if planned != current else 2)
                    self.assertEqual({y for _, y in dots}, {track.track_y})
                    self.assertTrue(all(y1 == y2 == track.track_y for _, _, y1, _, y2 in strokes))
                    self.assert_labels_fit(track.centers, track.label_widths, width)
                    first, last = min(x for x, _ in dots), max(x for x, _ in dots)
                    sorted_dots = sorted(x for x, _ in dots)
                    self.assertTrue(all(b - a >= 11.3 for a, b in zip(sorted_dots, sorted_dots[1:])))
                    grey_segments = sorted((min(a, b), max(a, b)) for ink, a, _, b, _ in strokes if ink == grey)
                    main_segments = [(a, b) for ink, a, _, b, _ in strokes if ink == main]
                    if planned != current:
                        [(a, b)] = main_segments
                        self.assertEqual((a, b), (dots[1][0], dots[2][0]))
                        self.assertGreaterEqual(abs(b - a) + 1e-9, .25 * (last - first))
                        if not squeezed and 0 not in (planned, current):
                            share = (current - planned) / (max(0, planned, current) - min(0, planned, current))
                            self.assertAlmostEqual(abs(b - a), share * (last - first))
                    else:
                        self.assertEqual(main_segments, [])
                    if squeezed:
                        self.assertEqual(len(grey_segments), 2)
                        gap_start, gap_end = grey_segments[0][1], grey_segments[1][0]
                        self.assertLess(gap_start, gap_end)
                        outside = min(dots[1][0], dots[2][0]), max(dots[1][0], dots[2][0])
                        self.assertTrue(gap_end < outside[0] or gap_start > outside[1])
                        [call] = marks.call_args_list
                        self.assertEqual(len(call.args[0]), 2)
                        for x1, _, x2, _ in call.args[0]:
                            self.assertTrue(gap_start < x1 < gap_end and gap_start < x2 < gap_end)
                    else:
                        self.assertEqual(len(grey_segments), 1)
                        marks.assert_not_called()
                    track_positions.append(dots)
            if len(track_positions) == 2:
                en_dots, ar_dots = track_positions
                for (en_x, _), (ar_x, _) in zip(en_dots, ar_dots):
                    self.assertAlmostEqual(en_x + ar_x, width)


@unittest.skipUnless(REPORTLAB and PDFTOTEXT, "ReportLab and pdftotext are required for Layout C PDFs")
class BuildLayoutCTests(RecordedMeetingFixture, unittest.TestCase):
    def assert_order(self, document, labels):
        offset = 0
        for label in labels:
            text = normalise(label)
            position = document.find(text, offset)
            self.assertGreaterEqual(position, 0, f"Missing or out of order: {label}\n{document}")
            offset = position + len(text)

    def pdf_text(self, pdf):
        return normalise(extract(pdf))

    def test_very_long_project_name_can_flow_across_pages(self):
        base = carryover_view()
        project = dict(base.project, project="StartTitle " + "Bakery " * 900 + "EndTitle")
        view = layout_c(replace(base, project=project))

        drawn = extract(render_pdf(view))

        self.assertGreaterEqual(len([page for page in drawn.split("\f") if page.strip()]), 2)
        self.assert_order(normalise(drawn), ("StartTitle", "EndTitle", view.content["headline"], "Running Date"))

    def test_notices_screen_pictures_carryovers_and_empty_states_survive(self):
        carryover = carryover_view()
        view = layout_c(replace(carryover, screen_map=screen_view().screen_map[:1]))
        pdf = render_pdf(view)
        actual = self.pdf_text(pdf)
        for words in (
            "Corner Bakery", "Weekly meeting 4", "the bread menu is ready.",
            "Attendees: the owner", "Delivery date", "Today", "On time",
            "Prepared for the meeting. No decisions are recorded.",
            "No meeting was held on 5 March.", "Screen map", "Bread & rolls",
            "Earlier", "Current", "4 March 2026", "11 March 2026",
            "No finished work is listed.", "What we promised last week",
            "Show the pickup form", "Done", "Add the allergy menu", "Not finished",
            "Needs review.", "Corrections and removals", "Use <b>rolls</b> & bread",
            "Correction for week 2 on 6 March.", "Use the printed menu",
            "Removal for week 1 on 7 March.", "Privacy request", "Your decisions",
            "No decisions are waiting.", "What we need from the client",
            "Nothing is needed from the client.", "No items are planned for next week.",
            "What we agreed", "Running Date", "New delivery date", "Client signature",
            "Page 1",
        ):
            with self.subTest(words=words):
                self.assertIn(normalise(words), actual)
        self.assert_order(actual, ("Delivery date", "Screen map", "See it",
                                   "What we promised last week", "Corrections and removals",
                                   "Next week", "Your decisions", "What we agreed"))
        self.assert_order(actual, (
            "Prepared for the meeting. No decisions are recorded.",
            "No meeting was held on 5 March.", "See it",
        ))
        self.assertGreaterEqual(pdf.count(b"/Subtype /Image"), 2)
        self.assertNotIn(normalise("needed because the delivery date moved"), actual)

    def test_recorded_change_shows_its_card_table_byline_and_required_signature(self):
        self.start()
        self.command("change", "--what", "Offer a later pickup slot", "--reason",
                     "The shop stays open longer", "--asked-by", "Avery Holt", "--days", "2",
                     setup=cli_date_setup("2026-02-24"))
        self.prepare()
        self.command("record", "--answer", "C-001=yes", "--attendee", "the owner",
                     "--attendee", "the manager", "--decided-by", "Mira Holt")
        drawn = self.pdf_text(self.client_copy())

        self.assert_order(drawn, (
            "Corner Bakery", "Weekly meeting 3", "The bread menu is ready.", "Delivery date",
            "See it", "Oat bread and spice buns", "Next week", "Show the pickup form",
            "Your decisions", "C-001", "Offer a later pickup slot", "The shop stays open longer",
            "Yes, now", "Raised by Avery Holt on 24 February", "What we need from the client",
            "Pickup times", "Due 1 March", "What we agreed", "Running Date",
            "Planned delivery date", "Offer a later pickup slot", "Decided by Mira Holt on 26 February",
            "New delivery date", "Client signature", "Date",
        ))
        self.assert_order(drawn, ("New delivery date",
                                  "Client signature · needed because the delivery date moved"))
        self.assertEqual(drawn.count(normalise("Corner Bakery · Weekly meeting 3")), 2)
        self.assertIn("planned", drawn)
        self.assertIn(normalise("now, +2 days"), drawn)
        self.assertNotIn(normalise("no decisions are recorded"), drawn)

    def test_long_build_keeps_each_list_in_order_and_prints_the_following_table(self):
        self.start()
        self.add_change()
        done = [f"DoneItem{number:03d}" for number in range(1, 44)]
        upcoming = [f"NextItem{number:03d}" for number in range(1, 29)]
        data = self.read_json(self.draft)
        data["finished"] = [{"text": f"{key} verified menu and pickup instructions.",
                             "source": "app/menu.py"} for key in done]
        data["next_week"] = [{"text": f"{key} check customer form and order confirmation."}
                             for key in upcoming]
        self.write_json(self.draft, data)
        self.prepare()
        self.record_manual("C-001=no")

        pdf = self.client_copy()
        pages = [page for page in extract(pdf).split("\f") if page.strip()]
        self.assertGreaterEqual(len(pages), 2)
        actual = self.pdf_text(pdf)
        self.assert_order(actual, ("See it", *done, "Next week", *upcoming,
                                   "Your decisions", "What we need from the client",
                                   "What we agreed", "Running Date", "Client signature"))
        for label in done + upcoming:
            self.assertEqual(actual.count(normalise(label)), 1, label)

    def test_arabic_mirrors_header_columns_and_date_labels(self):
        from reportlab.pdfgen.canvas import Canvas

        draw_rect = Canvas.rect
        edges = []

        def capture_rect(canvas, x, y, width, height, stroke=1, fill=0):
            if width == 4 and height > 20 and stroke == 0 and fill == 1:
                edges.append(canvas.absolutePosition(x, y)[0])
            draw_rect(canvas, x, y, width, height, stroke=stroke, fill=fill)

        base = carryover_view()
        common = {
            "project": dict(base.project, project="Nordmark"),
            "week": dict(base.week, held=True, attendees=["Mira"], end_after="2026-03-28",
                         answers=[{"id": "C-001", "answer": "yes"}]),
        }
        build_text = {
            "en": ("The bread menu", "MenuProof is ready", "PickupProof", "The shop opens late"),
            "ar": ("قائمة الخبز", "جهزت قائمة MenuProof", "خيار PickupProof", "يفتح المخبز مساءً"),
        }
        for language, (headline, finished, decision, reason) in build_text.items():
            with self.subTest(language=language):
                view = MeetingView(
                    project=dict(common["project"], language=language),
                    week=common["week"], content={"headline": headline,
                          "finished": [{"text": finished}], "next_week": [], "needs": []},
                    changes=[{"id": "C-001", "date": "2026-03-10", "what": decision,
                              "reason": reason, "asked_by": "Mira", "days_added": 2}],
                    evidence=[],
                )
                edges.clear()
                with patch.object(Canvas, "rect", capture_rect):
                    width, words = first_page_words(render_pdf(layout_c(view)))

                def first_word(value):
                    return min((word for word in words if word.text.strip("·") == value),
                               key=lambda word: float(word.attrib["yMin"]))

                def x(value):
                    word = first_word(value)
                    return (float(word.attrib["xMin"]) + float(word.attrib["xMax"])) / 2

                def side(value):
                    if language == "ar":
                        self.assertGreater(x(value), width / 2, value)
                    else:
                        self.assertLess(x(value), width / 2, value)

                side("Nordmark")
                side("MenuProof")
                [edge_x] = edges
                if language == "ar":
                    self.assertLess(x("PickupProof"), width / 2)
                    self.assertGreater(edge_x, x("PickupProof"))
                else:
                    self.assertGreater(x("PickupProof"), width / 2)
                    self.assertLess(edge_x, x("PickupProof"))

                top_project = first_word("Nordmark")
                top_date = first_word("2026")
                self.assertLess(abs(float(top_project.attrib["yMin"]) -
                                    float(top_date.attrib["yMin"])), 10)
                if language == "ar":
                    self.assertLess(float(top_date.attrib["xMin"]), width / 2)
                else:
                    self.assertGreater(float(top_date.attrib["xMin"]), width / 2)

                # The day numbers occur in both the timeline and Running Date
                # table. Select the earliest occurrences after the top-line date.
                def panel_day(value):
                    return min((word for word in words if word.text == value
                                and float(word.attrib["yMin"]) > 90),
                               key=lambda word: float(word.attrib["yMin"]))

                def timeline_x(value):
                    return float(panel_day(value).attrib["xMin"])

                if language == "ar":
                    self.assertGreater(timeline_x("12"), timeline_x("26"))
                    self.assertGreater(timeline_x("26"), timeline_x("28"))
                else:
                    self.assertLess(timeline_x("12"), timeline_x("26"))
                    self.assertLess(timeline_x("26"), timeline_x("28"))


if __name__ == "__main__":
    unittest.main()
