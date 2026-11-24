"""Check saved client text against the fonts each meeting uses."""

from functools import lru_cache
from unicodedata import bidirectional

from .arabic import display, is_latin, is_mark, visual
from .meeting_design_fonts import ARABIC_ROLES, FONT_DIR, STUDIO_FAMILIES, font_codepoints, font_filename
from .storage import Refusal
from .text_fields import one_line, validate_arabic_text


BODY = "WeekflowInstrumentRegular"
BOLD = "WeekflowInstrumentBold"
TITLE = "WeekflowBricolageBold"
DISPLAY = "WeekflowBricolageRegular"
FONT_FILES = {
    BODY: font_filename(STUDIO_FAMILIES["text"], "Regular"),
    BOLD: font_filename(STUDIO_FAMILIES["text"], "Bold"),
    TITLE: font_filename(STUDIO_FAMILIES["heading"], "Bold"),
    DISPLAY: font_filename(STUDIO_FAMILIES["heading"], "Regular"),
}
FONT_ROLES = {BODY: "body", BOLD: "bold", TITLE: "title", DISPLAY: "display"}


@lru_cache(maxsize=None)
def font_coverage(font):
    filename = FONT_FILES[font]
    try:
        return font_codepoints((FONT_DIR / filename).read_bytes())
    except (OSError, ValueError):
        raise Refusal(f"Restore the Weekflow PDF font {filename}.") from None


def validate_arabic_font(value, field, font, design, allow_fallback):
    bold = font in (TITLE, BOLD)
    arabic = ARABIC_ROLES[bold]
    latin = "bold" if bold else "body"
    coverage = {role: font_codepoints(design.font_data[role]) for role in (arabic, latin)}
    missing = set(design.missing_roles) if allow_fallback else set()
    text = display(one_line(value))
    for character, index in visual(text):
        if is_latin(character):
            roles = (latin,)
        elif bidirectional(character) in ("R", "AL") or is_mark(character):
            roles = (arabic,)
        else:
            roles = (arabic, latin)
        if not any(ord(character) in coverage[role] or role in missing for role in roles):
            raise Refusal(f"The PDF font cannot draw U+{ord(text[index]):04X} in {field}.")


def validate_pdf_text(value, field, font=BODY, *, design=None, allow_fallback=False):
    if design is not None and design.language == "ar":
        validate_arabic_font(value, field, font, design, allow_fallback)
        return
    if allow_fallback and design is not None and FONT_ROLES[font] in design.missing_roles:
        # The replacement PDF identifies any unsupported character by its Unicode code.
        return
    if design is None or design.is_studio:
        glyphs = font_coverage(font)
    else:
        glyphs = font_codepoints(design.font_data[FONT_ROLES[font]])
    for character in one_line(value):
        if ord(character) not in glyphs:
            raise Refusal(f"The PDF font cannot draw U+{ord(character):04X} in {field}.")


def validate_meeting_pdf_text(view, *, allow_fallback=False):
    from .meeting_design import PDF_LAYOUTS
    from .page import HEADINGS
    from .screen_display import picture_slots

    def check(value, field, font=BODY):
        validate_pdf_text(value, field, font, design=view.design, allow_fallback=allow_fallback)

    def check_words(value, field, font=BODY):
        if view.project.get("language") == "ar" and not allow_fallback:
            names = (view.project["project"], view.project["client"], *view.attendees,
                     *view.content.get("latin_names", ()))
            validate_arabic_text(value, field, names)
        check(value, field, font)

    # The canvas draws the footer directly, outside the paragraph glyph checks.
    if view.project.get("language", "en") == "en":
        check("Weekly meeting Page 0123456789", "the PDF footer")
        for title in HEADINGS[0 if view.is_docs else 1:]:
            check(title, "the meeting step headings", TITLE)
    check(view.project["project"], "project", DISPLAY)
    if view.design.pdf_layout in PDF_LAYOUTS:
        check(view.project["project"], "project", TITLE)
    check(view.project["client"], "client")
    for position, attendee in enumerate(view.attendees, 1):
        check(attendee, f"attendees item {position}")
    check(view.content["headline"], "headline", TITLE)
    for key in ("finished", "next_week", "needs"):
        for position, row in enumerate(view.content.get(key, ()), 1):
            check(row["text"], f"{key} item {position}")
    if view.is_docs:
        from .docs_presentation import sentence_parts

        for question in view.content.get("settled", ()):
            check(question, "a settled question")
        for section in view.content["document"]:
            check(section["title"], "document section title", BOLD)
            for sentence in section["sentences"]:
                visible = "".join(sentence_parts(sentence["text"], lambda _: ""))
                check(visible, "document sentence")
        for decision in view.content["decisions"]:
            identifier = decision["id"]
            check(decision["question"], f"question for {identifier}", BOLD)
            check(decision["question"], f"question for {identifier}")
            check(decision["why"], f"reason for {identifier}")
            for option in decision["options"]:
                check(option, f"option for {identifier}")
            for said in decision.get("said", ()):
                check(said["who"], f"who spoke for {identifier}")
                check(said["what"], f"what was said for {identifier}")
        for answer in view.week.get("answers", ()):
            if "decided_by" in answer:
                check(answer["decided_by"], f'decided-by for {answer["id"]}')
    for row in view.changes:
        change_id = row["id"]
        check_words(row["what"], f"what for {change_id}", BOLD)
        check(row["what"], f"what for {change_id}")
        check_words(row["reason"], f"reason for {change_id}")
        check(row["asked_by"], f"asked-by for {change_id}")
    for change_id, decider in view.build_deciders.items():
        check(decider, f"decided-by for {change_id}")
    for row in view.screen_map:
        check_words(row["name"], "screen name", BOLD)
        for _, picture in picture_slots(row):
            if picture["removed"]:
                check(picture["removed"], "the picture removal notice")
    for row in view.content.get("meeting_promises", ()):
        check_words(row["what"], f'what for promise {row["id"]}', BOLD)
        if "note" in row:
            check_words(row["note"], f'note for promise {row["id"]}')
    for row in view.content.get("corrections", ()):
        check_words(row["what"], f'what for correction {row["id"]}', BOLD)
        check_words(row["reason"], f'reason for correction {row["id"]}')
        check(row["by"], f'by for correction {row["id"]}')
