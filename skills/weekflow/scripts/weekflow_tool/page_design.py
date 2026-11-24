"""Embed the meeting fonts and apply checked colours to the offline page."""

from base64 import b64encode

from .meeting_design_colors import contrast
from .meeting_design_fonts import PROJECT_FAMILIES, STUDIO_FAMILIES


PROJECT_TEXT = PROJECT_FAMILIES["text"]
PROJECT_HEADING = PROJECT_FAMILIES["heading"]


def font_faces(design, *, docs=False, language="en"):
    body = STUDIO_FAMILIES["text"] if design.is_studio else PROJECT_TEXT
    heading = STUDIO_FAMILIES["heading"] if design.is_studio else PROJECT_HEADING
    faces = [(body, 400, "body"), (body, 700, "bold"), (heading, 700, "title")]
    # Keep old Studio docs pages exact when the heading uses the bundled faces.
    old_docs_faces = docs and design.is_studio and design.fonts["display"]["source"] == "studio"
    if not old_docs_faces:
        faces.append((heading, 400, "display"))
    if language == "ar":
        faces.extend((("Meeting Arabic", 400, "arabic-regular"), ("Meeting Arabic", 700, "arabic-bold")))
    for family, weight, role in faces:
        data = b64encode(design.font_data[role]).decode("ascii")
        yield (f'@font-face {{font-family:"{family}";font-weight:{weight};'
               f'src:url("data:font/ttf;base64,{data}") format("truetype");}}')


def project_design_css(design):
    if design.page_layout == "a":
        tint = design.answer_tint
        text, quiet = (design.colors[role] if contrast(design.colors[role], tint) >= 4.5 else design.answer_text
                       for role in ("text", "quiet"))
        yield (f":root {{ --color-answer-tint: {tint}; --color-answer-text: {design.answer_text}; "
               f"--color-tint-text: {text}; --color-tint-quiet: {quiet}; "
               f"--color-main-text: {design.main_text}; }}")
    if design.is_studio:
        return
    properties = [
        *(f"--color-{role}: {value};" for role, value in sorted(design.colors.items())),
        f"--color-main-text: {design.main_text};",
        f"--color-answer-tint: {design.answer_tint};",
        f"--color-answer-text: {design.answer_text};",
        f'--font-heading: "{PROJECT_HEADING}", Georgia, serif;',
        f'--font-text: "{PROJECT_TEXT}", system-ui, sans-serif;',
        f"--radius: {design.radius}px;",
    ]
    yield ":root {\n  " + "\n  ".join(properties) + "\n}"
    yield """.delivery-date, .week-here, .date-moved, .docs-header strong,
.docs-stages li[aria-current="step"] span, .screen-state, .screen-new, .screen-action {
  color: var(--color-main-text);
}"""
