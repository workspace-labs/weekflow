"""Remove saved picture bytes and replace their places in the meeting history."""

from base64 import b64decode, b64encode
from dataclasses import replace
from datetime import date
from hashlib import sha256
from pathlib import Path
import re

from .client_pdf import render_pdf
from .corrections import CORRECTIONS, add_corrections, correction_details, read_corrections, validate_correction_text
from .lock_transaction import PICTURE_TARGET, write_redaction, write_transaction
from .meetings import content_file, fresh_view, page_file, pdf_file, read_week, week_numbers
from .meeting_design import fallback_notice, load_design
from .meeting_design_fonts import with_font_fallback
from .meeting_language import translate
from .page import DESIGN, PICTURE_REMOVAL_ANSWERS, format_date
from .page_html import render_html
from .pdf_artifact import require_current_pdf, stamp_pdf
from .pdf_text import validate_pdf_text
from .removal import append_changed, removal_receipt
from .screen_snapshot import PICTURE_SLOTS, read_screen_snapshot, screen_map
from .screens import (
    SCREENS_FILE, SCREEN_DIR, check_relative, ensure_weekly_ignores, picture_digest, picture_relative,
    read_saved_picture, read_screens,
)
from .setup import project_text_design
from .storage import Refusal, WEEKLY


PICTURE_DATA_URL = re.compile(rb"data:image/(?:png|jpeg);base64,([A-Za-z0-9+/=]+)")


def saved_picture_reference(files, argument, screen_id):
    path = Path(argument)
    if path.is_absolute():
        try:
            path = path.relative_to(files.root)
        except ValueError:
            raise Refusal("Give a saved picture inside this project's docs/weekly/screens.") from None
    if path.parent == SCREEN_DIR or path.parent == Path("screens") or len(path.parts) == 1:
        reference = "screens/" + path.name
        picture_relative(reference, screen_id)
        return reference
    raise Refusal("Give a saved picture path under docs/weekly/screens.")


def matching_picture_references(files, digest, data):
    matches = set()
    directory = files.path(SCREEN_DIR)
    if not directory.exists():
        return matches, data
    for path in directory.iterdir():
        match = PICTURE_TARGET.fullmatch(path.relative_to(files.root).as_posix())
        if match and match["digest"] == digest:
            reference = "screens/" + path.name
            saved = read_saved_picture(files, reference)
            if data is None:
                data = saved
            matches.add(reference)
    return matches, data


def remove_live_references(row, references):
    updated = dict(row)
    if row["picture"] in references:
        updated.update(picture="", picture_kind="", taken_on="", owner_checked_on="")
    if row["previous_picture"] in references:
        updated["previous_picture"] = ""
    return updated


def remove_from_snapshot(content, digest, notice, references):
    rows = read_screen_snapshot(content)
    changed = False
    replacements = []
    for row in rows:
        updated = dict(row)
        for slot in PICTURE_SLOTS:
            picture = row[slot]
            if picture and picture["digest"] == digest and "removed" not in picture:
                references.add(picture["file"])
                replacement = dict(picture, new=False, removed=notice)
                replacement.pop("unavailable", None)
                updated[slot] = replacement
                changed = True
        replacements.append(updated)
    return dict(content, meeting_screens=replacements) if changed else content


def existing_copies(files, number):
    copies = {}
    for relative, label in ((page_file(number), "HTML"), (pdf_file(number), "PDF")):
        if files.write_path(relative).exists():
            copies[relative] = label
    return copies


def rebuild_copies(files, week, updated, copies, writes, font_assets):
    """Keep the old rendering choices and update only the saved picture slots."""
    number = week["number"]
    try:
        original = fresh_view(files, week, snapshot_only=True, allow_missing_page=True,
                              recover_fonts=week.get("language") == "ar")
        content = dict(updated)
        content.pop("meeting_changes")
        view = replace(original, content=content, screen_map=screen_map(files, content))
    except (OSError, Refusal):
        if not week.get("locked_on"):
            raise
        return list(copies)

    html, pdf = page_file(number), pdf_file(number)
    if week.get("owner_confirmed_on") and not week.get("locked_on") and html in copies:
        history = original.answers_after_picture_removal(view)
        updated[PICTURE_REMOVAL_ANSWERS] = history
        view = replace(view, content=dict(view.content, **{PICTURE_REMOVAL_ANSWERS: history}))
    if html in copies:
        writes.append((html, with_font_fallback(render_html(view), view.design.missing_roles)))
    if pdf in copies:
        try:
            require_current_pdf(files, original)
        except (OSError, Refusal):
            if not week.get("locked_on"):
                raise
            return [pdf]
        # The saved facts are available. A renderer failure must leave the
        # removal pending so the owner can retry before the source is retired.
        writes.append((pdf, stamp_pdf(render_pdf(view), view)))
    font_assets.update(view.design.assets)
    return []


def picture_checker(data, digest):
    if data is not None:
        encoded = b64encode(data)
        return lambda stored: data in stored or encoded in stored

    def matches_lost_picture(stored):
        if sha256(stored).hexdigest() == digest:
            return True
        for match in PICTURE_DATA_URL.finditer(stored):
            try:
                candidate = b64decode(match[1], validate=True)
            except ValueError:
                continue
            if sha256(candidate).hexdigest() == digest:
                return True
        return False

    return matches_lost_picture


def contains_picture(path, matches_picture):
    return path.is_file() and matches_picture(path.read_bytes())


def check_other_files(files, handled, weekly_copies, matches_picture):
    for path in files.path(WEEKLY).rglob("*"):
        relative = path.relative_to(files.root)
        if path.is_symlink():
            raise Refusal("Replace links under docs/weekly with local files before removing a picture.")
        if relative in handled or not path.is_file():
            continue
        stored = path.read_bytes()
        if matches_picture(stored):
            raise Refusal(f"An extra file still holds the picture: {relative.as_posix()}.")
        if relative not in weekly_copies and (path.suffix.casefold() == ".pdf"
                                               or stored.startswith(b"%PDF-")):
            raise Refusal(f"An extra PDF cannot be checked for the picture: {relative.as_posix()}.")


def picture_warning(number, files, copies, why):
    labels = " and ".join(copies[relative] for relative in files)
    return f"Week {number} copies ({labels}) could not be rebuilt and may still hold the picture. {why}"


def unchanged_copies(files, week, copies, matches_picture):
    """Recognize copies of a different snapshot before allowing them to stay."""
    number = week["number"]
    page, pdf = page_file(number), pdf_file(number)
    affected = page in copies and contains_picture(files.path(page), matches_picture)
    unmatched = [page] if affected else []
    if pdf in copies:
        try:
            original = fresh_view(files, week, snapshot_only=True, allow_missing_page=True)
            require_current_pdf(files, original)
        except (OSError, Refusal):
            unmatched.append(pdf)
    return affected, unmatched


def update_week(files, number, digest, day, references, matches_picture, writes, details, font_assets):
    week = read_week(files, number)
    language = week.get("language", "en")
    notice = translate(language, "Removed on {date} because {reason}",
                       date=format_date(day, day.year - 1, language), reason=details["reason"])
    locked = bool(week["held"] and week.get("locked_on"))
    copies = existing_copies(files, number)
    relative = content_file(number)
    try:
        content = files.read_json(relative, optional=True)
        if content is not None and not isinstance(content, dict):
            raise Refusal(f"Restore the saved content for week {number}.")
        updated = remove_from_snapshot(content, digest, notice, references) if content is not None else None
    except Refusal:
        if not locked:
            raise
        content = updated = None

    if content is None and copies:
        if not locked:
            raise Refusal(f"Restore the saved content for week {number} before removing the picture.")
        affected = contains_picture(files.path(page_file(number)), matches_picture)
        if affected:
            validate_correction_text(details, project_text_design(files))
        return affected, locked, copies, list(copies), "The saved content is unavailable."
    if updated == content:
        affected, preserved = unchanged_copies(files, week, copies, matches_picture)
        if preserved and not locked:
            raise Refusal(f"Restore the copies for week {number} before removing the picture.")
        if affected:
            validate_correction_text(details, project_text_design(files))
        return affected, locked, copies, preserved, "The copies do not match the saved content."
    design = load_design(files, content.get(DESIGN), language=language,
                         recover_fonts=language == "ar", page=page_file(number))
    validate_correction_text(details, design)
    validate_pdf_text(notice, "the picture removal notice", design=design)
    copy_writes = []
    preserved = rebuild_copies(files, week, updated, copies, copy_writes, font_assets) if copies else []
    append_changed(writes, relative, content, updated)
    writes.extend(copy_writes)
    warning = ""
    if copies and not preserved and design.missing_roles:
        warning = fallback_notice(design, pdf=pdf_file(number) in copies)
    return True, locked, copies, preserved, warning


def remove_picture(files, args):
    screens = read_screens(files)
    if not any(row["id"] == args.id for row in screens):
        raise Refusal("Give an existing screen ID.")
    reference = saved_picture_reference(files, args.file, args.id)
    selected = read_saved_picture(files, reference, allow_missing=True)
    digest = picture_digest(reference)
    references, data = matching_picture_references(files, digest, selected)
    if selected is not None and reference not in references:
        raise Refusal("Use the exact saved picture filename.")
    for row in screens:
        for slot in PICTURE_SLOTS:
            if row[slot] and picture_digest(row[slot]) == digest:
                references.add(row[slot])
    matches_picture = picture_checker(data, digest)

    details = correction_details(args, check_fonts=False)
    day = date.today()

    writes, changed, locked_weeks, warnings = [], [], [], []
    font_assets = {}
    kept, weekly_copies = set(), set()
    append_changed(writes, SCREENS_FILE, screens, [remove_live_references(row, references) for row in screens])
    for number in week_numbers(files):
        affected, locked, copies, preserved, why = update_week(
            files, number, digest, day, references, matches_picture, writes, details, font_assets,
        )
        weekly_copies.update(copies)
        if affected:
            changed.append(number)
            if locked:
                locked_weeks.append(number)
        if preserved:
            kept.update(preserved)
            warnings.append(picture_warning(number, preserved, copies,
                                            why or "The saved files or confirmed copy are unavailable."))
        elif why:
            warnings.append(why)

    if reference not in references:
        raise Refusal("Choose a known saved picture for this screen.")
    if not changed:
        validate_correction_text(details, project_text_design(files))
    retire = [relative for saved in sorted(references)
              for relative in (picture_relative(saved), check_relative(saved))]
    before = read_corrections(files)
    after = add_corrections(before, locked_weeks, kind="removal", day=day.isoformat(), details=details)
    append_changed(writes, CORRECTIONS, before, after)
    for relative, replacement in writes:
        stored = replacement.encode("utf-8") if isinstance(replacement, str) else replacement
        if matches_picture(stored):
            raise Refusal(f"The replacement for {relative.as_posix()} still holds the picture.")
    handled = kept | set(retire) | {relative for relative, _ in writes}
    check_other_files(files, handled, weekly_copies, matches_picture)
    if any(relative.suffix in (".html", ".pdf") for relative, _ in writes):
        ensure_weekly_ignores(files)
    if font_assets:
        write_transaction(files, font_assets.items())
    write_redaction(files, writes, retire=retire, weeks=changed, warnings=warnings, picture=True)
    return removal_receipt(changed, picture=True) + warnings
