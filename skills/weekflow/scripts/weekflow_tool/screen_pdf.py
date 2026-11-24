"""Draw the saved screen map in the client copy."""

from io import BytesIO

from .client_pdf import paragraph
from .meeting_language import translate
from .screen_display import (
    app_notice, empty_screen_text, new_picture, picture_caption, picture_slots,
    screen_counts, state_label,
)
from .storage import Refusal


def screen_map_story(view, styles):
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import Flowable, Spacer

    inset = 10
    gap = 8
    colors = view.design.colors
    radius = round(view.design.radius * 0.6)
    language = getattr(view, "language", "en")

    class ScreenCard(Flowable):
        def __init__(self, row):
            super().__init__()
            self.unbuilt = row["state"] == "not built"
            self.name = row["name"]
            self.title = paragraph(self.name, styles["label"], "the screen name")
            self.status = paragraph(state_label(row["state"], language), styles["quiet"], "the screen mark")
            self.pictures = []
            for position, picture in picture_slots(row):
                text, taken = picture_caption(row, picture, language)
                if taken:
                    text = f"{text} {taken}"
                if new_picture(view, picture, position):
                    text += " · " + translate(language, "New")
                label = (paragraph(translate(language, position), styles["cell"], "the picture position")
                         if position else None)
                caption = paragraph(text, styles["cell"], "the picture caption")
                data = picture["data"]
                self.pictures.append((label, data, caption))
            self.empty = (
                None if self.pictures
                else paragraph(empty_screen_text(row, language), styles["quiet"], "the empty screen note")
            )

        def image_box(self, data, width):
            if data is None:
                return None, 0, 0
            try:
                reader = ImageReader(BytesIO(data))
                image_width, image_height = reader.getSize()
            except (OSError, ValueError, SyntaxError):
                raise Refusal(f"The picture for {self.name} could not be drawn in the PDF.") from None
            scale = min((width - 2) / image_width, 148 / image_height)
            return reader, image_width * scale, image_height * scale

        def wrap(self, width, height):
            self.width = width
            inner = width - 2 * inset
            self.title_height = self.title.wrap(inner, height)[1]
            self.status_height = self.status.wrap(inner, height)[1]
            self.columns = []
            self.column_width = (inner - gap) / 2 if len(self.pictures) == 2 else inner
            for label, data, caption in self.pictures:
                label_height = label.wrap(self.column_width, height)[1] + 3 if label else 0
                caption_height = caption.wrap(self.column_width, height)[1]
                reader, image_width, image_height = self.image_box(data, self.column_width)
                self.columns.append((label, label_height, reader, image_width, image_height,
                                     caption, caption_height))
            if self.columns:
                # Align both picture tops, even when one slot holds a removal notice.
                self.label_height = max(column[1] for column in self.columns)
                body_height = self.label_height + max(
                    (column[4] + 3 if column[2] else 0) + column[6] for column in self.columns
                )
            else:
                body_height = self.empty.wrap(inner, height)[1]
            self.height = 2 * inset + self.title_height + self.status_height + gap + body_height
            if self.height > 735:
                raise Refusal(f"The screen card for {self.name} is too tall to print on one page.")
            return self.width, self.height

        def draw(self):
            canvas = self.canv
            canvas.saveState()
            canvas.setStrokeColor(colors["quiet"] if self.unbuilt else colors["lines"])
            canvas.setFillColor(colors["card"] if self.unbuilt else colors["background"])
            if self.unbuilt:
                canvas.setDash(3, 3)
            canvas.roundRect(0, 0, self.width, self.height, radius, stroke=1, fill=1)
            canvas.restoreState()

            y = self.height - inset - self.title_height
            self.title.drawOn(canvas, inset, y)
            y -= self.status_height
            self.status.drawOn(canvas, inset, y)
            y -= gap
            if self.empty:
                self.empty.drawOn(canvas, inset, inset)
                return
            for index, column in enumerate(self.columns):
                label, label_height, reader, image_width, image_height, caption, caption_height = column
                position = len(self.columns) - index - 1 if language == "ar" else index
                x = inset + position * (self.column_width + gap)
                if label:
                    label.drawOn(canvas, x, y - label_height + 3)
                top = y - self.label_height
                if reader:
                    left = x + (self.column_width - image_width) / 2
                    try:
                        canvas.drawImage(reader, left, top - image_height, image_width, image_height,
                                         mask="auto")
                    except (OSError, ValueError, SyntaxError):
                        raise Refusal(f"The picture for {self.name} could not be drawn in the PDF.") from None
                    top -= image_height + 3
                caption.drawOn(canvas, x, top - caption_height)

    notice = app_notice(view)
    if not view.screen_map:
        return [paragraph(notice, styles["notice"], "the app notice")] if notice else []
    story = [paragraph(translate(language, "Screen map"), styles["label"], "the screen map heading")]
    if notice:
        story.append(paragraph(notice, styles["notice"], "the app notice"))
    counts = " · ".join(f"{label}: {count}" for count, label in screen_counts(view))
    story.append(paragraph(counts, styles["body"], "the screen counts"))
    for row in view.screen_map:
        story.extend((ScreenCard(row), Spacer(1, gap)))
    return story
