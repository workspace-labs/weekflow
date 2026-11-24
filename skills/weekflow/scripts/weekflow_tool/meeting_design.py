"""Resolve a project's Ready values into a stable meeting design."""

from dataclasses import dataclass, field, replace
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
import re

from .arabic import REQUIRED_GLYPHS
from .meeting_design_colors import (
    BADGE_ROLES, COLOR_NAMES, HEX_COLOR, STUDIO_ANSWER_TINT, STUDIO_COLORS,
    contrast, palette_is_readable, readable_palette,
)
from .meeting_design_fonts import (
    ARABIC_FAMILY, ARABIC_ROLES,
    FONT_DIGEST, FONT_DIR, FONT_LIMIT, FONT_ROLES, FROZEN_FONT_TARGET, STUDIO_FAMILIES,
    WEIGHTS, OversizedFile, embedded_fonts, font_codepoints, font_filename, frozen_font_path,
    is_frozen_font, read_frozen_font, read_regular,
)
from .storage import Refusal


DESIGN_FILE = Path("DESIGN.md")
PROJECT_FONTS = Path("docs/fonts")
STUDIO_RADIUS = 20
FONT_NAMES = {"heading": "Heading font", "text": "Text font"}
FAMILY = re.compile(r"[A-Za-z0-9]+(?: +[A-Za-z0-9]+)*")
FALLBACK = re.compile(r'[A-Za-z0-9 -]+|"[A-Za-z0-9 -]+"')
RADIUS = re.compile(r"0*([0-9]{1,2})px")
FONTS = {role for roles in FONT_ROLES.values() for role in roles}
READY_NAMES = {"--radius", *(f"--color-{role}" for role in STUDIO_COLORS),
               *(f"--font-{role}" for role in FONT_ROLES), "--font-arabic"}
READY = re.compile(r"^##[ \t]+(?:Ready values|القيم الجاهزة)[ \t]*$")
FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})(.*)$")
ROOT_RULE = re.compile(r"\s*:root\s*\{(.*)\}\s*", re.DOTALL)
COMMENT = re.compile(r"""(?P<quoted>"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*')|/\*.*?(?:\*/|\Z)""",
                     re.DOTALL)
DECLARATION = re.compile(r"\s*(--[a-z-]+)\s*:\s*([^;]*?)\s*;\s*")
HEADER_COMMENTS = re.compile(r"(?:\s*<!--.*?-->)*\s*", re.DOTALL)
FRONT_MATTER = re.compile(r"^---[ \t]*\n.*?^(?:---|\.\.\.)[ \t]*(?:\n|\Z)", re.DOTALL | re.MULTILINE)
TITLE = re.compile(r"^#[ \t]+[^\n]*(?:\n|\Z)")
STAMP = re.compile(r"^>\s*(?:v[0-9]+\s*[·–—-]\s*)?(Approved|Draft)(?=\s|$)", re.IGNORECASE)
ARABIC_STAMP = re.compile(r"^>\s*الإصدار[ \t]+[0-9]+\s*[·–—-]\s*(معتمد|مسودة)(?=\s|$)")
VERSION_STAMP = re.compile(r"^>\s*v[0-9]+\b", re.IGNORECASE)
DERIVED_COLORS = ("main_text", "answer_tint", "answer_text")
PALETTE_KEYS = {"colors", "badge_inks", *DERIVED_COLORS}
SNAPSHOT_KEYS = {"radius", "font_families", "fonts", *PALETTE_KEYS}
PDF_PAPERS = ("design", "white")
PDF_LAYOUT_C = "c"
PDF_LAYOUT_C_REVISED = "c-2"
PDF_LAYOUTS = (PDF_LAYOUT_C, PDF_LAYOUT_C_REVISED)
PAGE_LAYOUT_A = "a"


@dataclass(frozen=True)
class MeetingDesign:
    colors: dict
    radius: int
    font_names: dict
    fonts: dict
    font_data: dict
    main_text: str
    answer_tint: str
    answer_text: str
    badge_inks: dict
    assets: dict = field(default_factory=dict)
    missing_roles: tuple = ()
    pdf: dict = None
    page_layout: str = None
    source_main: str = field(default=None, compare=False)
    has_project_values: bool = field(default=False, compare=False)

    @property
    def palette(self):
        return dict(colors=dict(self.colors), main_text=self.main_text, answer_tint=self.answer_tint,
                    answer_text=self.answer_text, badge_inks=dict(self.badge_inks))

    @property
    def snapshot(self):
        saved = dict(self.palette, radius=self.radius, font_families=dict(self.font_names),
                     fonts={key: dict(value) for key, value in self.fonts.items()})
        if self.pdf is not None:
            saved["pdf"] = self.pdf
        if self.page_layout is not None:
            saved["page_layout"] = self.page_layout
        return saved

    @property
    def pdf_layout(self):
        return self.pdf.get("layout") if self.pdf is not None else None

    @property
    def pdf_override(self):
        if self.pdf is not None:
            palette = {key: self.pdf[key] for key in PALETTE_KEYS}
            if palette != self.palette:
                return palette
        return None

    def for_pdf(self):
        override = self.pdf_override
        return replace(self, **override) if override else self

    @property
    def font_digests(self):
        return {role: sha256(self.font_data[role]).hexdigest() if role in self.missing_roles
                else value["digest"] for role, value in self.fonts.items()}

    @property
    def language(self):
        return "ar" if "arabic" in self.font_names else "en"

    @property
    def is_studio(self):
        studio_meta, _ = studio_fonts(self.language)
        return (self.colors == STUDIO_COLORS and self.radius == STUDIO_RADIUS
                and self.main_text == self.answer_text == STUDIO_COLORS["main"]
                and self.answer_tint == STUDIO_ANSWER_TINT
                and all(self.badge_ink(role) == STUDIO_COLORS[role] for role in BADGE_ROLES)
                and all(meta["digest"] == studio_meta[role]["digest"] for role, meta in self.fonts.items()))

    def badge_ink(self, role):
        return self.badge_inks[role]


def font_details(data, source):
    return {"digest": sha256(data).hexdigest(), "source": source}


def font_families(language):
    return dict(STUDIO_FAMILIES, arabic=ARABIC_FAMILY) if language == "ar" else STUDIO_FAMILIES


def font_roles(language):
    return dict(FONT_ROLES, arabic=ARABIC_ROLES) if language == "ar" else FONT_ROLES


@lru_cache(maxsize=2)
def studio_fonts(language="en"):
    data = {}
    families = font_families(language)
    for usage, roles in font_roles(language).items():
        family = families[usage]
        for role, weight in zip(roles, WEIGHTS):
            filename = font_filename(family, weight)
            try:
                data[role] = (FONT_DIR / filename).read_bytes()
            except OSError:
                raise Refusal(f"Restore the Weekflow font {filename}.") from None
    details = {role: font_details(contents, "studio") for role, contents in data.items()}
    return details, data


def studio_design(language="en"):
    fonts, data = studio_fonts(language)
    main = STUDIO_COLORS["main"]
    return MeetingDesign(dict(STUDIO_COLORS), STUDIO_RADIUS, dict(font_families(language)),
                         {role: dict(meta) for role, meta in fonts.items()}, dict(data),
                         main, STUDIO_ANSWER_TINT, main, {role: STUDIO_COLORS[role] for role in BADGE_ROLES})


def fallback_notice(design, *, pdf=True):
    roles = ", ".join(design.missing_roles)
    action = "The PDF uses" if pdf else "The PDF will use"
    return (f"The saved project fonts for {roles} could not be restored. "
            f"{action} the Studio fonts for those roles. "
            "Characters they cannot draw appear as Unicode codes.")


def design_stamp(lines):
    header = HEADER_COMMENTS.sub("", "\n".join(lines), count=1)
    front_matter = FRONT_MATTER.match(header)
    if front_matter:
        header = HEADER_COMMENTS.sub("", header[front_matter.end():], count=1)
    title = TITLE.match(header)
    if title:
        header = HEADER_COMMENTS.sub("", header[title.end():], count=1)
    first = header.split("\n", 1)[0].strip()
    match = STAMP.match(first)
    if match:
        return match[1].lower()
    match = ARABIC_STAMP.match(first)
    if match:
        return "draft" if match[1] == "مسودة" else "approved"
    return "unknown" if VERSION_STAMP.match(first) else None


def ready_block(lines):
    fence = None
    for index, line in enumerate(lines):
        marker = FENCE.fullmatch(line)
        if fence:
            if closes_fence(marker, fence):
                fence = None
        elif marker:
            fence = marker[1]
        elif READY.fullmatch(line):
            return css_block(lines[index + 1:])
    return ""


def closes_fence(marker, opening):
    return (marker and marker[1][0] == opening[0] and len(marker[1]) >= len(opening)
            and not marker[2].strip())


def css_block(lines):
    first = next((index for index, line in enumerate(lines) if line.strip()), None)
    if first is None:
        return ""
    marker = FENCE.fullmatch(lines[first])
    if not marker or marker[2].strip().lower() not in ("css", ""):
        return ""
    for index in range(first + 1, len(lines)):
        if closes_fence(FENCE.fullmatch(lines[index]), marker[1]):
            root = ROOT_RULE.fullmatch("\n".join(lines[first + 1:index]))
            return root[1] if root else ""
    return ""


def css_values(block):
    selected = {}
    uncommented = COMMENT.sub(lambda match: match["quoted"] or " " + "\n" * match[0].count("\n"), block)
    for line in uncommented.splitlines():
        declaration = DECLARATION.fullmatch(line)
        if declaration and declaration[1] in READY_NAMES:
            name, value = declaration.groups()
            selected[name] = value if name not in selected else ""
    return selected


def first_family(value):
    first, *fallbacks = (family.strip() for family in value.split(","))
    if first.startswith('"') and first.endswith('"'):
        first = first[1:-1]
    if not FAMILY.fullmatch(first) or not all(FALLBACK.fullmatch(item) for item in fallbacks):
        return None
    return " ".join(first.split())


def usable_values(values, language):
    colors = {role: value.upper() for role in STUDIO_COLORS
              if HEX_COLOR.fullmatch(value := values.get(f"--color-{role}", ""))}
    radius = RADIUS.fullmatch(values.get("--radius", ""))
    radius = int(radius[1]) if radius and int(radius[1]) <= 32 else None
    families = {role: family for role in font_roles(language)
                if (family := first_family(values.get(f"--font-{role}", ""))) is not None}
    return colors, radius, families


def project_font_pair(files, family, *, arabic=False):
    pair = []
    try:
        for weight in WEIGHTS:
            data = read_regular(files, PROJECT_FONTS / font_filename(family, weight), FONT_LIMIT)
            if data is None:
                return None
            glyphs = font_codepoints(data)
            if arabic and not all(ord(glyph) in glyphs for glyph in REQUIRED_GLYPHS):
                return None
            pair.append(data)
    except (OSError, Refusal, ValueError):
        return None
    return pair


def frozen_copy(files, target):
    files.write_path(target)
    try:
        return read_regular(files, target, FONT_LIMIT)
    except OversizedFile:
        return None


def new_font_asset(files, digest, data):
    target = frozen_font_path(digest)
    try:
        return {} if frozen_copy(files, target) == data else {target: data}
    except (OSError, Refusal, ValueError):
        raise Refusal("Restore the saved meeting font in docs/weekly/pages/fonts and try again.") from None


def apply_families(files, families, studio):
    names = dict(studio.font_names)
    fonts, data = dict(studio.fonts), dict(studio.font_data)
    assets, messages = {}, []
    for usage, requested in families.items():
        pair = project_font_pair(files, requested, arabic=(usage == "arabic"))
        if pair is None:
            label = "Arabic font" if usage == "arabic" else FONT_NAMES[usage]
            messages.append(f"{label} files are missing or unusable. The Studio font is used.")
            continue
        names[usage] = requested
        for role, contents in zip(font_roles(studio.language)[usage], pair):
            data[role] = contents
            fonts[role] = font_details(contents, "project")
            assets.update(new_font_asset(files, fonts[role]["digest"], contents))
    return names, fonts, data, assets, messages


def prepare_design(files, language="en"):
    studio = studio_design(language)
    try:
        data = read_regular(files, DESIGN_FILE)
        if data is None:
            return studio, []
        lines = data.decode("utf-8-sig").splitlines()
    except (OSError, Refusal, ValueError):
        return studio, ["DESIGN.md could not be read."]
    stamp = design_stamp(lines)
    if stamp == "draft":
        return studio, ["DESIGN.md is a Draft."]
    if stamp not in (None, "approved"):
        return studio, ["DESIGN.md does not have an Approved stamp."]

    values = css_values(ready_block(lines))
    colors, radius, families = usable_values(values, language)
    missing = [name for role, name in COLOR_NAMES.items() if role not in colors]
    missing.extend(name for role, name in FONT_NAMES.items() if role not in families)
    if language == "ar" and "--font-arabic" in values and "arabic" not in families:
        missing.append("Arabic font")
    if radius is None:
        missing.append("Radius")
    if not colors and radius is None and not families:
        return studio, ["DESIGN.md has no usable Ready values."]
    messages = [f"{name} is missing or invalid in DESIGN.md. The Studio value is used." for name in missing]
    palette, color_messages = readable_palette({**STUDIO_COLORS, **colors})
    names, fonts, data, assets, font_messages = apply_families(files, families, studio)
    design = MeetingDesign(radius=STUDIO_RADIUS if radius is None else radius,
                           font_names=names, fonts=fonts, font_data=data, assets=assets,
                           source_main=colors.get("main"),
                           has_project_values=bool(colors or radius is not None
                                                   or any(meta["source"] == "project" for meta in fonts.values())),
                           **palette)
    return design, [*messages, *color_messages, *font_messages]


def with_pdf_paper(design, paper, *, layout):
    if paper is None:
        background = design.colors["background"]
        if contrast("#FFFFFF", background) > contrast("#000000", background):
            raise Refusal("Choose the PDF paper with --pdf-paper design or --pdf-paper white.")
        paper = "design"
    messages = []
    palette = design.palette
    if paper == "white" and not design.is_studio:
        main = design.source_main or STUDIO_COLORS["main"]
        palette, _ = readable_palette(dict(STUDIO_COLORS, main=main))
        adjusted = palette["colors"]["main"]
        if adjusted != main:
            messages.append(f"PDF Main changed from {main} to {adjusted} for readable contrast.")
    pdf = dict(palette, paper=paper)
    if layout is not None:
        pdf["layout"] = layout
    return replace(design, pdf=pdf), messages


def saved_pdf_layout(snapshot):
    pdf = snapshot.get("pdf") if isinstance(snapshot, dict) else None
    layout = pdf.get("layout") if isinstance(pdf, dict) else None
    return layout if layout in PDF_LAYOUTS else None


def matching_values(values, keys, pattern):
    return (isinstance(values, dict) and values.keys() == keys
            and all(isinstance(value, str) and pattern.fullmatch(value) for value in values.values()))


def valid_palette(saved):
    return (matching_values(saved["colors"], STUDIO_COLORS.keys(), HEX_COLOR)
            and matching_values(saved["badge_inks"], set(BADGE_ROLES), HEX_COLOR)
            and matching_values({key: saved[key] for key in DERIVED_COLORS}, set(DERIVED_COLORS), HEX_COLOR)
            and palette_is_readable(saved["colors"], saved["main_text"], saved["answer_tint"],
                                    saved["answer_text"], saved["badge_inks"]))


def validate_snapshot(saved, language="en"):
    message = "Restore the design saved with the meeting."
    if (not isinstance(saved, dict) or saved.keys() - {"pdf", "page_layout"} != SNAPSHOT_KEYS
            or ("page_layout" in saved and saved["page_layout"] != PAGE_LAYOUT_A)):
        raise Refusal(message)
    roles = font_roles(language)
    fonts_expected = FONTS if language == "en" else FONTS | set(ARABIC_ROLES)
    if (not valid_palette(saved)
            or not matching_values(saved["font_families"], roles.keys(), FAMILY)
            or type(saved["radius"]) is not int or not 0 <= saved["radius"] <= 32
            or not isinstance(saved["fonts"], dict) or saved["fonts"].keys() != fonts_expected):
        raise Refusal(message)
    fonts = saved["fonts"]
    for details in fonts.values():
        if (not isinstance(details, dict) or details.keys() != {"digest", "source"}
                or not isinstance(details["digest"], str) or not FONT_DIGEST.fullmatch(details["digest"])
                or details["source"] not in ("studio", "project")):
            raise Refusal(message)
    for first, second in roles.values():
        if fonts[first]["source"] != fonts[second]["source"]:
            raise Refusal(message)
    if "pdf" in saved:
        pdf = saved["pdf"]
        if (not isinstance(pdf, dict) or pdf.keys() - {"layout"} != PALETTE_KEYS | {"paper"}
                or ("layout" in pdf and pdf["layout"] not in PDF_LAYOUTS)
                or pdf["paper"] not in PDF_PAPERS or not valid_palette(pdf)):
            raise Refusal(message)
        if pdf["paper"] == "design" and any(pdf[key] != saved[key] for key in PALETTE_KEYS):
            raise Refusal(message)
        if pdf["paper"] == "white" and any(pdf["colors"][key] != value for key, value in STUDIO_COLORS.items()
                                          if key not in ("main", "on-main")):
            raise Refusal(message)


def recovery_fonts(files, wanted, page):
    """Find exact saved bytes without consulting the live design or trusting the page as markup."""
    found = {}

    def collect(data):
        if data is not None and (digest := sha256(data).hexdigest()) in wanted - found.keys():
            font_codepoints(data)
            found[digest] = data

    try:
        directory = files.path(PROJECT_FONTS)
        paths = sorted(directory.glob("*.ttf")) if not directory.is_symlink() else []
    except (OSError, Refusal):
        paths = []
    for path in paths:
        try:
            collect(read_regular(files, path.relative_to(files.root), FONT_LIMIT))
        except (OSError, Refusal, ValueError):
            continue
        if wanted == found.keys():
            return found
    if page is not None:
        try:
            markup = read_regular(files, page)
        except (OSError, Refusal, ValueError):
            markup = None
        for data in embedded_fonts(markup or b""):
            try:
                collect(data)
            except ValueError:
                continue
            if wanted == found.keys():
                break
    return found


def load_design(files, saved, *, language="en", recover_fonts=False, page=None):
    if saved is None:
        if language == "en":
            return studio_design()
        raise Refusal("Restore the design saved with the meeting.")
    validate_snapshot(saved, language)
    studio = studio_design(language)
    data, unavailable, assets = {}, {}, {}
    for role, details in saved["fonts"].items():
        if details["source"] == "studio":
            if details != studio.fonts[role]:
                raise Refusal("Restore the Studio font saved with the meeting.")
            data[role] = studio.font_data[role]
        else:
            digest = details["digest"]
            try:
                if not recover_fonts:
                    data[role] = read_frozen_font(files, digest)
                    continue
                contents = frozen_copy(files, frozen_font_path(digest))
                if contents is None or sha256(contents).hexdigest() != digest:
                    unavailable[role] = digest
                    continue
                font_codepoints(contents)
                data[role] = contents
            except (OSError, Refusal, ValueError):
                raise Refusal(f"Restore the saved {role} font in docs/weekly/pages/fonts and try again.") from None
    missing = []
    if unavailable:
        recovered = recovery_fonts(files, set(unavailable.values()), page)
        for role, digest in unavailable.items():
            if digest in recovered:
                data[role] = assets[frozen_font_path(digest)] = recovered[digest]
            else:
                data[role] = studio.font_data[role]
                missing.append(role)
    return MeetingDesign(colors=saved["colors"], radius=saved["radius"], font_names=saved["font_families"],
                         fonts=saved["fonts"], font_data=data, main_text=saved["main_text"],
                         answer_tint=saved["answer_tint"], answer_text=saved["answer_text"],
                         badge_inks=saved["badge_inks"], assets=assets, missing_roles=tuple(missing),
                         pdf=saved.get("pdf"), page_layout=saved.get("page_layout"))
