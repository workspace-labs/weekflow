"""Adjust meeting colours for contrast while keeping the project's palette."""

from functools import lru_cache
import re

from .storage import Refusal


STUDIO_COLORS = {
    "background": "#FFFFFF", "card": "#F4F4F8", "text": "#17171C",
    "quiet": "#53535E", "main": "#4436C9", "on-main": "#FFFFFF",
    "lines": "#DEDEE6", "error": "#B3261E",
}
COLOR_NAMES = {
    "background": "Background", "card": "Card", "text": "Text", "quiet": "Quiet",
    "main": "Main", "on-main": "On main", "lines": "Lines", "error": "Error",
}
STUDIO_ANSWER_TINT = "#EAE7FA"
BADGE_ROLES = ("main", "quiet", "error")
INK_MINIMUMS = {"text": 4.5, "quiet": 4.5, "error": 4.5, "main": 3}
HEX_COLOR = re.compile(r"#[0-9A-Fa-f]{6}")
COLOR_CHOICE = "meeting_colors"
CHOICE_ROLES = ("main", "background", "text")


def valid_color_choice(choice):
    return (choice == "standard" or isinstance(choice, dict) and "main" in choice
            and choice.keys() <= set(CHOICE_ROLES)
            and all(isinstance(value, str) and HEX_COLOR.fullmatch(value) for value in choice.values()))


def given_color_choice(args):
    values = {role: getattr(args, f"{role}_color") for role in CHOICE_ROLES}
    values = {role: value for role, value in values.items() if value is not None}
    if values and "main" not in values:
        raise Refusal("Give --main-color before giving a background or text colour.")
    for role, value in values.items():
        if not HEX_COLOR.fullmatch(value):
            raise Refusal(f"Give --{role}-color as a #RRGGBB colour.")
    return {role: value.upper() for role, value in values.items()} if values else args.colors


def rgb(color):
    return tuple(int(color[index:index + 2], 16) for index in (1, 3, 5))


def blend(start, end, amount):
    return tuple(base + (ink - base) * amount for base, ink in zip(rgb(start), rgb(end)))


def mix(start, end, amount):
    return "#" + "".join(f"{round(channel):02X}" for channel in blend(start, end, amount))


def linear(channel):
    channel /= 255
    if channel <= 0.04045:
        return channel / 12.92
    return ((channel + 0.055) / 1.055) ** 2.4


@lru_cache(maxsize=2048)
def luminance(color):
    red, green, blue = map(linear, rgb(color) if isinstance(color, str) else color)
    return red * 0.2126 + green * 0.7152 + blue * 0.0722


def contrast(left, right):
    low, high = sorted((luminance(left), luminance(right)))
    return (high + 0.05) / (low + 0.05)


def tone(color, fits):
    if fits(color):
        return color
    for step in range(1, 256):
        for end in ("#000000", "#FFFFFF"):
            candidate = mix(color, end, step / 255)
            if fits(candidate):
                return candidate
    return None


def readable_ink(color, surfaces, ratio):
    return tone(color, lambda candidate: all(contrast(candidate, base) >= ratio for base in surfaces))


def base_inks(colors, card):
    surfaces = (colors["background"], card)
    inks = {role: readable_ink(colors[role], surfaces, ratio) for role, ratio in INK_MINIMUMS.items()}
    inks["main_text"] = readable_ink(colors["main"], surfaces, 4.5)
    return inks


def adjust_surfaces(colors):
    """Move Card only if two different surfaces leave no common readable ink."""
    background = colors["background"]
    card = colors["card"]
    for step in range(256):
        candidate = mix(card, background, step / 255)
        inks = base_inks(colors, candidate)
        if all(ink is not None for ink in inks.values()):
            return candidate, inks
    raise RuntimeError("No contrast on a shared meeting surface.")


def answer_tint(background, main):
    if (background, main) == (STUDIO_COLORS["background"], STUDIO_COLORS["main"]):
        return STUDIO_ANSWER_TINT
    return mix(background, main, 0.10)


def badge_contrast(background, ink):
    return contrast(ink, blend(background, ink, 0.10))


def readable_palette(values):
    colors = dict(values)
    # With a midtone surface, even black or white ink can have too little
    # contrast after its own colour is blended into the badge background.
    colors["background"] = tone(colors["background"], lambda candidate: any(
        badge_contrast(candidate, ink) >= 4.5 for ink in ("#000000", "#FFFFFF")))
    colors["card"], inks = adjust_surfaces(colors)
    main_text = inks.pop("main_text")
    colors.update(inks)
    colors["on-main"] = readable_ink(colors["on-main"], (colors["main"],), 4.5)

    background = colors["background"]
    tint = answer_tint(background, colors["main"])
    answer = readable_ink(colors["main"], (tint,), 4.5)
    badges = {role: tone(colors[role], lambda ink: badge_contrast(background, ink) >= 4.5)
              for role in BADGE_ROLES}

    changes = [(COLOR_NAMES[role], values[role], new) for role, new in colors.items()]
    changes.extend((name, colors["main"], new) for name, new in
                   (("Main text", main_text), ("Answer text", answer)))
    changes.extend((f"{COLOR_NAMES[role]} badge text", colors[role], new) for role, new in badges.items())
    messages = [f"{name} changed from {old} to {new} for readable contrast."
                for name, old, new in changes if old != new]
    return dict(colors=colors, main_text=main_text, answer_tint=tint, answer_text=answer,
                badge_inks=badges), messages


def chosen_palette(choice):
    values = {**STUDIO_COLORS, **choice}
    background = values["background"]
    ink = readable_ink(values["text"], (background,), 4.5)
    values.update(card=mix(background, ink, .05), quiet=mix(background, ink, .72),
                  lines=mix(background, ink, .17))
    return readable_palette(values)


def palette_is_readable(colors, main_text, tint, answer_text, badges):
    background, card = colors["background"], colors["card"]
    return (all(contrast(colors[name], base) >= ratio for name, ratio in INK_MINIMUMS.items()
                for base in (background, card))
            and contrast(colors["on-main"], colors["main"]) >= 4.5
            and all(contrast(main_text, base) >= 4.5 for base in (background, card))
            and contrast(answer_text, tint) >= 4.5
            and all(badge_contrast(background, ink) >= 4.5 for ink in badges.values()))
