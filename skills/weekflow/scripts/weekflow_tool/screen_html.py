"""Print the offline screen map using native in-page disclosure controls."""

from base64 import b64encode
from functools import partial
from html import escape

from .meeting_language import translate
from .screen_display import (
    app_notice, empty_screen_text, new_picture, picture_caption, picture_slots,
    screen_counts, state_label,
)


def screen_picture(view, row, position, picture):
    label = partial(translate, view.language)
    position_html = f'<strong class="screen-position">{label(position)}</strong>' if position else ""
    caption, taken = picture_caption(row, picture, view.language)
    photo = ""
    if picture["data"] is not None:
        content = picture["data"]
        kind = "png" if content.startswith(b"\x89PNG\r\n\x1a\n") else "jpeg"
        source = b64encode(content).decode("ascii")
        description = "Screenshot of {screen}" if picture["kind"] == "screenshot" else "Design of {screen}"
        alt = escape(label(description, screen=row["name"]), quote=True)
        photo = (f'<img class="screen-image" src="data:image/{kind};base64,{source}" '
                 f'alt="{alt}" decoding="async">')
    caption_html = escape(caption, quote=True)
    if taken:
        caption_html += f' <time datetime="{picture["taken_on"]}">{taken}</time>'
    if new_picture(view, picture, position):
        caption_html += f' <strong class="screen-new">{label("New")}</strong>'
    return (f'<span class="screen-picture">{position_html}{photo}'
            f'<span class="screen-caption">{caption_html}</span></span>')


def screen_card(view, row):
    identifier = f'screen-{row["id"]}'
    name = escape(row["name"], quote=True)
    state = state_label(row["state"], view.language)
    label = partial(translate, view.language)
    appearance = " screen-unbuilt" if row["state"] == "not built" else ""
    slots = picture_slots(row)
    if slots:
        pictures = "".join(screen_picture(view, row, position, picture) for position, picture in slots)
        layout = " screen-pair" if len(slots) == 2 else ""
        body = f'<span class="screen-pictures{layout}">{pictures}</span>'
    else:
        body = f'<span class="screen-caption screen-empty">{empty_screen_text(row, view.language)}</span>'
    return (f'<details class="screen-card{appearance}">'
            f'<summary tabindex="0" aria-labelledby="{identifier}-name {identifier}-action">'
            '<span class="screen-head">'
            f'<strong class="screen-name" id="{identifier}-name">{name}</strong>'
            f'<span class="screen-state">{state}</span></span>'
            f'<span class="screen-action" id="{identifier}-action">'
            f'<span class="screen-open">{label("Open screen")}</span>'
            f'<span class="screen-close">{label("Close screen")}</span></span>'
            f'{body}</summary></details>')


def render_screen_map(view):
    notice = app_notice(view)
    notice_html = f'<p class="screen-notice">{notice}</p>' if notice else ""
    if not view.screen_map:
        return notice_html
    counts = "".join(f'<div><dt>{label}</dt><dd>{count}</dd></div>'
                     for count, label in screen_counts(view))
    cards = "".join(screen_card(view, row) for row in view.screen_map)
    heading = translate(view.language, "Screen map")
    return ('<section class="screen-map" aria-labelledby="screen-map-heading">'
            f'<h3 id="screen-map-heading">{heading}</h3>'
            f'{notice_html}<dl class="counts">{counts}</dl>'
            f'<div class="screen-grid">{cards}</div></section>')
