"""Replace a personal name without changing what the meeting decided."""

from datetime import date
from html import unescape
import json
from pathlib import Path
import re

from .arabic_names import arabic_name_matcher
from .changes import CHANGES, read_changes, recorded_change_deciders
from .client_pdf import PdfRendererUnavailable, render_pdf
from .content import read_picture_removal_answers
from .corrections import (
    CORRECTIONS, DETAILS, add_corrections, correction_details, read_corrections, validate_correction_text,
)
from .lock_transaction import (
    PICTURE_CHECK_TARGET, PICTURE_HISTORY_TARGET, PICTURE_TARGET, write_redaction, write_transaction,
)
from .meetings import (
    PAGES, WEEKS, confirmed_view, content_file, fresh_view, legacy_copy_file, page_file, pdf_file,
    project_for_week, read_project, read_week, week_file, week_numbers,
)
from .meeting_design import FROZEN_FONT_TARGET, fallback_notice, is_frozen_font, load_design
from .meeting_design_colors import COLOR_CHOICE
from .meeting_design_fonts import with_font_fallback
from .meeting_language import ARABIC_MONTHS, translate
from .page import DESIGN, DESIGN_NOTICES, DOCS_LATER, MONTHS, PICTURE_REMOVAL_ANSWERS, MeetingView, format_date
from .page_html import render_html
from .pdf_artifact import current_pdf, require_current_pdf, stamp_pdf
from .pdf_text import BOLD, DISPLAY, TITLE, validate_meeting_pdf_text, validate_pdf_text
from .picture_bytes import PNG_SIGNATURE
from .promises import PROMISES, read_promises
from .screen_snapshot import PICTURE_SLOTS, read_screen_snapshot, screen_map
from .screens import (
    SCREEN_DIR, SCREENS_FILE, checked_picture, ensure_weekly_ignores, picture_digest,
    read_history, read_screens,
)
from .setup import PROJECT_FILE, project_text_design
from .storage import Refusal, WEEKLY, json_text
from .text_fields import one_line


CHANGE_TEXT = ("what", "reason", "asked_by", "decided_by")
PROMISE_TEXT = ("what", "note")
PROJECT_TEXT = ("project", "client", "meeting_day")
PROJECT_FIELDS = {*PROJECT_TEXT, "attendees", "language", "mode", "scope_approved_on", "planned_end", "pdf_paper",
                  COLOR_CHOICE}
WEEK_FIELDS = {"number", "meeting_date", "held", "attendees", "mode", "answers", "end_before",
               "end_after", "decisions_left", "owner_confirmed_on", "signed_by", "signed_on",
               "locked_on", "language"}
NOTICE_DATE = rf"(?:[0-9]{{1,2}} (?:{'|'.join(MONTHS)})(?: [0-9]{{4}})?|[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}})"
ARABIC_NOTICE_DATE = rf"[0-9]{{1,2}} (?:{'|'.join(ARABIC_MONTHS)}) [0-9]{{4}}"
NOTICE_PREFIX = (rf"(?<!\w)(?:Removed on {NOTICE_DATE} because |Withheld · {NOTICE_DATE} · "
                 rf"|أُزيل في {ARABIC_NOTICE_DATE} بسبب |حُجب · {ARABIC_NOTICE_DATE} · )")
NOTICE_PARTS = re.compile(rf"({NOTICE_PREFIX})", re.IGNORECASE)


class RemovalReasonRefusal(Refusal):
    """A safe field message can be shown even if it uses a word being removed."""


class RemovalChoicesRefusal(Refusal):
    """Show the owner the exact spellings that need a decision."""


class NameReplacement:
    def __init__(self, name, day, reason, language, *, arabic, also=(), candidates=None):
        self.name, self.day, self.reason, self.language = name, day, reason, language
        self.arabic, self.also, self.candidates = arabic, also, candidates
        self.discovering = candidates is not None
        self.word = re.compile(rf"(?<!\w){re.escape(name)}(?!\w)", re.IGNORECASE)
        self.arabic_matches = arabic if language == "ar" else None
        # Keep old notice wording and its real date while still checking its reason.
        self.matches = re.compile(rf"(?P<notice>{NOTICE_PREFIX})|{self.word.pattern}", re.IGNORECASE)
        display_day = format_date(day, day.year, language)
        prefix = translate(language, "Removed on {date} because {reason}", date=display_day, reason="").rstrip()
        if not self.discovering and self.has_name(prefix) and not self.has_name(display_day):
            prefix = f"حُجب · {display_day} ·" if language == "ar" else f"Withheld · {display_day} ·"
        self.replacement = f"{prefix} {reason}"

    def in_language(self, language):
        if language == self.language:
            return self
        return NameReplacement(self.name, self.day, self.reason, language, arabic=self.arabic,
                               also=self.also, candidates=self.candidates)

    def arabic_spans(self, value):
        for start, end, exact in self.arabic_matches.matches(value):
            if self.discovering:
                if not exact:
                    self.candidates.add(value[start:end])
            elif exact or value[start:end] in self.also:
                yield start, end

    def has_name(self, value):
        if self.arabic_matches is not None:
            return any(self.arabic_spans(value))
        return not self.discovering and bool(self.word.search(value))

    def redact_arabic(self, value):
        parts = []
        previous = 0
        for start, end in self.arabic_spans(value):
            parts.extend((value[previous:start], self.replacement))
            previous = end
        parts.append(value[previous:])
        return "".join(parts)

    def text(self, value):
        if self.arabic_matches is not None:
            return "".join(
                part if index % 2 else self.redact_arabic(part)
                for index, part in enumerate(NOTICE_PARTS.split(value))
            )
        if self.discovering:
            return value
        return self.matches.sub(lambda match: match[0] if match["notice"] else self.replacement, value)

    def row(self, row, fields):
        return dict(row, **{key: self.text(row[key]) for key in fields
                            if isinstance(row.get(key), str)})

    def check_replacement_font(self, font, design=None):
        try:
            validate_pdf_text(self.replacement, "removal reason", font, design=design)
        except Refusal as error:
            raise RemovalReasonRefusal(*error.messages) from None

    def people(self, row):
        attendees = row.get("attendees")
        if isinstance(attendees, list) and all(isinstance(person, str) for person in attendees):
            return dict(row, attendees=[self.text(person) for person in attendees])
        return row

    def content(self, content, location, *, saved, design=None):
        if not isinstance(content, dict):
            raise Refusal(f"Restore the meeting content in {location}.")
        updated = self.row(content, ("headline",))
        if saved and updated.get("headline") != content.get("headline"):
            self.check_replacement_font(TITLE, design)
        groups = {"finished": ("text",), "next_week": ("text",), "needs": ("text",)}
        if saved:
            groups.update(meeting_changes=CHANGE_TEXT, meeting_promises=PROMISE_TEXT, corrections=DETAILS)
        metadata = {"source_digests", "missed_meetings", "corrections_frozen", "prior_needs_unavailable",
                    "prior_decisions_unavailable", DESIGN, DESIGN_NOTICES}
        if not saved:
            metadata = set()
        if "latin_names" in content:
            metadata.add("latin_names")
            names = content["latin_names"]
            if not isinstance(names, list) or not all(isinstance(value, str) for value in names):
                raise Refusal(f"Restore the tool and person names in {location}.")
            updated["latin_names"] = [value for value in names if not self.has_name(value)]
        if "stage" in content:
            updated.update(self.docs_content(content, location, saved=saved))
            metadata.update(("stage", "document", "decisions", "settled"))
            if saved:
                metadata.update(("stage_meetings", "form_still_open"))
        if saved and read_picture_removal_answers(content) is not None:
            metadata.add(PICTURE_REMOVAL_ANSWERS)
        if saved and "meeting_screens" in content:
            updated["meeting_screens"] = [self.screen(row, design=design, saved=True)
                                          for row in read_screen_snapshot(content)]
            metadata.add("meeting_screens")
        self.check_extra(content, {"headline", "received", "app_ran", *groups, *metadata}, location)
        for group, fields in groups.items():
            if group not in content:
                continue
            rows = content[group]
            if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
                raise Refusal(f"Restore the meeting content in {location}.")
            for position, item in enumerate(rows, 1):
                if group == "finished":
                    source = item.get("source")
                    if isinstance(source, str) and self.has_name(source):
                        raise Refusal(f"The finished-work source path for item {position} in {location} "
                                      "contains the name.")
                    self.check_extra(item, {"text", "source"}, location)
                elif group == "needs":
                    self.check_extra(item, {"text", "by"}, location)
                elif group == "next_week":
                    self.check_extra(item, {"text"}, location)
            updated[group] = [self.row(row, fields) for row in rows]
        if "received" in content:
            if not isinstance(content["received"], list) or not all(
                isinstance(value, str) for value in content["received"]
            ):
                raise Refusal(f"Restore the meeting content in {location}.")
            updated["received"] = [self.text(value) for value in content["received"]]
        return updated

    def docs_content(self, content, location, *, saved):
        sections = []
        for section in docs_rows(content, "document", location):
            self.check_extra(section, {"title", "sentences"}, location)
            updated = self.row(section, ("title",))
            updated["sentences"] = []
            for item in docs_rows(section, "sentences", location):
                self.check_extra(item, {"text", "source"}, location)
                source = item.get("source")
                if isinstance(source, str) and source != "owner" and self.has_name(source):
                    raise Refusal(f"A document source path in {location} contains the name.")
                updated["sentences"].append(self.row(item, ("text",)))
            sections.append(updated)

        decisions = []
        for decision in docs_rows(content, "decisions", location):
            self.check_extra(decision, {"id", "question", "why", "options", "said"}, location)
            updated = self.row(decision, ("question", "why"))
            options = self.docs_texts(decision.get("options"), location)
            if len(options) != len({option.casefold() for option in options}):
                raise Refusal(f"Removing the name would make two options the same in {location}.")
            updated["options"] = options
            if "said" in decision:
                updated["said"] = []
                for entry in docs_rows(decision, "said", location):
                    self.check_extra(entry, {"who", "what"}, location)
                    updated["said"].append(self.row(entry, ("who", "what")))
            decisions.append(updated)
        updated = {"document": sections, "decisions": decisions}
        if "settled" in content:
            updated["settled"] = self.docs_texts(content["settled"], location)
        if saved and "form_still_open" in content:
            updated["form_still_open"] = self.docs_texts(content["form_still_open"], location)
        return updated

    def docs_texts(self, values, location):
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise Refusal(f"Restore the meeting content in {location}.")
        return [self.text(value) for value in values]

    def screen(self, row, *, design=None, saved=False):
        updated = self.row(row, ("name",))
        if saved and updated["name"] != row["name"]:
            self.check_replacement_font(BOLD, design)
        for slot in PICTURE_SLOTS:
            picture = row.get(slot)
            if isinstance(picture, dict) and "removed" in picture:
                updated[slot] = self.row(picture, ("removed",))
        return updated

    def check_extra(self, row, fields, location):
        if self.contains({key: value for key, value in row.items() if key not in fields}):
            raise Refusal(f"An unsupported field in {location} contains the name.")

    def contains(self, value):
        if isinstance(value, str):
            return self.has_name(value)
        if isinstance(value, dict):
            return any(self.contains(key) or self.contains(item) for key, item in value.items())
        if isinstance(value, list):
            return any(self.contains(item) for item in value)
        return False


def append_changed(writes, relative, before, after):
    if before != after:
        writes.append((relative, json_text(after)))


def docs_rows(content, key, location):
    rows = content.get(key, [])
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise Refusal(f"Restore the meeting content in {location}.")
    return rows


def known_picture_metadata(files, relative):
    name = relative.as_posix()
    try:
        if PICTURE_HISTORY_TARGET.fullmatch(name):
            read_history(files)
            return True
        if PICTURE_CHECK_TARGET.fullmatch(name):
            reference = "screens/" + relative.stem
            return checked_picture(files, reference, picture_digest(reference)) is not None
    except Refusal:
        # Inspect any unexpected contents rather than treating them as managed metadata.
        pass
    return False


def check_other_weekly_files(files, known, handled, scrub, writes, retire):
    """Include the input draft files the skill told the agent to keep under pages."""
    handled = handled | {Path(relative) for relative, _ in writes} | set(retire)
    for path in sorted(files.path(WEEKLY).rglob("*")):
        relative = path.relative_to(files.root)
        if path.is_symlink():
            raise Refusal("Replace links under docs/weekly with local files before removing a name.")
        name = relative.as_posix()
        if FROZEN_FONT_TARGET.fullmatch(name) and is_frozen_font(files, relative):
            continue
        managed_asset = any(pattern.fullmatch(name) for pattern in (
            PICTURE_TARGET, PICTURE_CHECK_TARGET, PICTURE_HISTORY_TARGET,
        )) or relative in {SCREEN_DIR / ".checked", SCREEN_DIR / ".history"}
        if relative not in known and not managed_asset and scrub.has_name(path.name):
            raise Refusal("A file or folder name under docs/weekly contains the name to remove.")
        if relative in handled or not path.is_file():
            continue
        if managed_asset and known_picture_metadata(files, relative):
            continue
        suffix = path.suffix.casefold()
        raw_bytes = path.read_bytes()
        if PICTURE_TARGET.fullmatch(name) and raw_bytes.startswith((PNG_SIGNATURE, b"\xff\xd8\xff")):
            continue
        if suffix == ".pdf" or raw_bytes.startswith(b"%PDF-"):
            if scrub.discovering:
                continue
            raise Refusal("A PDF under docs/weekly has no matching week record.")
        raw = raw_bytes.decode("utf-8-sig", errors="replace")
        if suffix == ".json" or path.name.startswith(".weekflow-"):
            try:
                data = json.loads(raw)
            except (ValueError, RecursionError):
                data = None
            if (relative not in known and relative.parent == PAGES and suffix == ".json"
                    and isinstance(data, dict) and "headline" in data):
                updated = scrub.content(data, "an input draft in docs/weekly/pages", saved=False)
                append_changed(writes, relative, data, updated)
                continue
            if scrub.contains(data):
                raise Refusal("An extra file under docs/weekly still contains the name.")
        if scrub.has_name(unescape(raw) if suffix == ".html" else raw):
            raise Refusal("An extra file under docs/weekly still contains the name.")


def rebuild_locked(files, project, original, week, updated_content, surviving, writes, deciders):
    number = week["number"]
    content = dict(updated_content)
    changes = content.pop("meeting_changes", []) if original.is_docs else content.pop("meeting_changes")
    view = MeetingView(project_for_week(project, week), week, content, changes, original.evidence,
                       legacy_carryover_dates=original.legacy_carryover_dates,
                       screen_map=screen_map(files, content), design=original.design, build_deciders=deciders)
    validate_meeting_pdf_text(view, allow_fallback=True)
    if page_file(number) in surviving:
        markup = render_html(view, legacy_build_fonts=original.legacy_build_fonts)
        writes.append((page_file(number), with_font_fallback(markup, view.design.missing_roles)))
    if pdf_file(number) in surviving:
        writes.append((pdf_file(number), stamp_pdf(render_pdf(view), view)))


def verify_untouched_copies(files, week, surviving, verified, *, previously_removed=False):
    number = week["number"]
    page = page_file(number)
    pdf = pdf_file(number)
    if pdf in surviving:
        view = confirmed_view(files, week, allow_missing_page=True, recover_fonts=bool(week.get("locked_on")))
        font_repair_needed = bool(view.design.assets or view.design.missing_roles) or view.restored_page is not None
        # An older removal may have left the original stamped PDF when the fonts were lost.
        if previously_removed and font_repair_needed:
            if current_pdf(files, view) is None:
                require_current_pdf(files, view, allow_stale=True)
                return view
        else:
            require_current_pdf(files, view)
        verified.update(surviving)
    elif page in surviving:
        try:
            # Verify the saved HTML even when the draft needs its embedded fonts.
            fresh_view(files, week, snapshot_only=True, recover_fonts=True)
        except Refusal:
            # Check an unmatched HTML file as an extra artifact below.
            return
        verified.add(page)


def plan_locked_copies(files, project, week, updated_week, content, surviving, writes, unchecked, font_assets,
                       *, deciders, original=None):
    number = week["number"]
    copies = {page_file(number): "HTML", pdf_file(number): "PDF"}
    for relative in surviving:
        files.write_path(relative)
    if surviving and content is None:
        # Preserve the originals. The final scan should not treat them as unrelated artifacts.
        unchecked.update(surviving)
        labels = " and ".join(label for relative, label in copies.items() if relative in surviving)
        return [f"Week {number} copies ({labels}) could not be checked and may still hold the name. "
                "The saved content is missing."]
    notices = []
    if surviving:
        retry = original is not None
        original = original or confirmed_view(files, week, allow_missing_page=True, recover_fonts=True)
        font_assets.update(original.design.assets)
        pdf = pdf_file(number)
        try:
            rebuild_locked(files, project, original, updated_week, content, surviving, writes, deciders)
        except PdfRendererUnavailable:
            if not original.design.missing_roles:
                raise
            unchecked.add(pdf)
            notices.append(f"Week {number} copy (PDF) could not be rebuilt and may still hold the name. "
                           "The reportlab package is required.")
        else:
            if retry:
                notices.append(f"Rebuilt the PDF for week {number} from its redacted record.")
            if pdf in surviving and original.design.missing_roles:
                notices.append(f"Week {number}. {fallback_notice(original.design)}")
    missing = [label for relative, label in copies.items() if relative not in surviving]
    if missing:
        notices.append(f"Week {number} copies could not be rebuilt: {', '.join(missing)}.")
    return notices


def plan_removal(files, scrub, day, details):
    project = read_project(files)
    scrub.check_extra(project, PROJECT_FIELDS, "the project setup")
    updated_project = scrub.people(scrub.row(project, PROJECT_TEXT))
    project_name_changed = updated_project["project"] != project["project"]
    project_changed = updated_project != project
    writes, retire, font_assets = [], [], {}
    append_changed(writes, PROJECT_FILE, project, updated_project)

    screens = read_screens(files)
    append_changed(writes, SCREENS_FILE, screens, [scrub.screen(row) for row in screens])

    changes = read_changes(files)
    updated_changes = [scrub.row(row, CHANGE_TEXT) for row in changes]
    append_changed(writes, CHANGES, changes, updated_changes)
    changed_changes = [row for row, updated in zip(changes, updated_changes) if row != updated]
    related = {row.get("decided_week") for row in changed_changes}
    staged = {row["id"] for row, updated in zip(changes, updated_changes)
              if not row.get("decided_week") and row.get("decided_by") != updated.get("decided_by")}

    promises = read_promises(files)
    updated_promises = [scrub.row(row, PROMISE_TEXT) for row in promises]
    append_changed(writes, PROMISES, promises, updated_promises)
    for row, updated in zip(promises, updated_promises):
        if row["what"] != updated["what"]:
            related.add(row["made_week"])
        if row != updated and row.get("checked_week"):
            related.add(row["checked_week"])

    corrections = read_corrections(files)
    previously_removed = {row["week"] for row in corrections if row["kind"] == "removal"}
    updated_corrections = [scrub.row(row, DETAILS) for row in corrections]
    related.update(row["week"] for row, updated in zip(corrections, updated_corrections) if row != updated)

    verified = {Path(PROJECT_FILE), CORRECTIONS, PROMISES, Path(CHANGES), SCREENS_FILE}
    unchecked = set()
    known = {*verified, PAGES, PAGES / "fonts", WEEKS, SCREEN_DIR}
    changed, locked, notices = [], [], []
    checked_details = False
    for number in week_numbers(files):
        week_path, content_path = week_file(number), content_file(number)
        verified.update((week_path, content_path))
        known.update((week_path, content_path, page_file(number), pdf_file(number), legacy_copy_file(number)))
        week = read_week(files, number)
        scrub.check_extra(week, WEEK_FIELDS, f"week {number}")
        content = files.read_json(content_path, optional=True)
        language = week.get("language", "en")
        local_scrub = scrub.in_language(language)
        updated_week = local_scrub.people(local_scrub.row(week, ("signed_by",)))
        design = None
        locked_meeting = week.get("locked_on") and week["held"]
        if not scrub.discovering and isinstance(content, dict) and DESIGN in content:
            design = load_design(files, content[DESIGN], language=language,
                                 recover_fonts=True, page=page_file(number))
        updated_content = (None if content is None else
                           local_scrub.content(content, f"week {number}", saved=True, design=design))
        if week["mode"] == "docs" and week.get("answers"):
            updated_week["answers"] = [
                answer if answer["answer"] == DOCS_LATER else local_scrub.row(answer, ("answer", "decided_by"))
                for answer in week["answers"]
            ]
        affected = (updated_week != week or updated_content != content or number in related
                    or (project_changed and (content is not None or week["held"]))
                    or (week["held"] and any(answer["id"] in staged for answer in week["answers"])))
        copies = {page_file(number), pdf_file(number)}
        surviving = {relative for relative in copies if files.path(relative).exists()}
        orphaned = locked_meeting and content is None and bool(surviving)
        if scrub.discovering:
            # Saved snapshots supply the copy text. Inspect extra HTML only if it cannot be verified.
            if orphaned or pdf_file(number) in surviving:
                verified.update(surviving)
            else:
                verify_untouched_copies(files, week, surviving, verified)
            continue
        if orphaned or (affected and locked_meeting):
            notices.extend(plan_locked_copies(files, updated_project, week, updated_week,
                                              updated_content, surviving, writes, unchecked, font_assets,
                                              deciders=recorded_change_deciders(updated_changes, updated_week)))
        if not affected:
            if not orphaned:
                original = verify_untouched_copies(
                    files, week, surviving, verified, previously_removed=number in previously_removed,
                )
                if original is not None:
                    notices.extend(plan_locked_copies(files, project, week, week, content, surviving,
                                                      writes, unchecked, font_assets,
                                                      deciders=original.build_deciders, original=original))
            continue
        if content is not None:
            validate_correction_text(details, design)
            if project_name_changed:
                local_scrub.check_replacement_font(DISPLAY, design)
            checked_details = True
        changed.append(number)
        if week.get("locked_on"):
            locked.append(number)
        elif week["held"] or "answers" in week:
            raise Refusal(f"Week {number} is recorded. Lock it before removing a name.")
        else:
            if updated_content is not None and week.get("owner_confirmed_on"):
                updated_content["corrections_frozen"] = True
            updated_week = dict(updated_week, owner_confirmed_on="")
            retire.extend((page_file(number), pdf_file(number)))
        retire.append(legacy_copy_file(number))
        append_changed(writes, week_path, week, updated_week)
        append_changed(writes, content_path, content, updated_content)

    if not scrub.discovering:
        if not checked_details:
            design = project_text_design(files, project)
            validate_correction_text(details, design)
            if project_name_changed:
                scrub.check_replacement_font(DISPLAY, design)
        updated_corrections = add_corrections(updated_corrections, locked, kind="removal", day=day, details=details)
        append_changed(writes, CORRECTIONS, corrections, updated_corrections)
    check_other_weekly_files(files, known, verified | unchecked | font_assets.keys(), scrub, writes, retire)
    return changed, writes, retire, notices, font_assets


def removal_receipt(weeks, *, recovered=False, picture=False):
    if recovered:
        message = "Recovered removal changed weeks" if weeks else "Recovered removal changed no weeks."
    else:
        message = "Changed weeks" if weeks else "No weeks changed."
    if weeks:
        message += " " + ", ".join(str(number) for number in weeks) + "."
    messages = [message, "A PDF already sent cannot be recalled. Ask the client to replace it."]
    if not picture:
        messages.append("Earlier Git commits may still hold the name.")
    return messages


def check_name_choices(candidates, also, keep):
    chosen = also | keep
    messages = []
    if chosen - candidates:
        messages.append("Use --also and --keep only for listed words.")
    if also & keep:
        messages.append("Use only one of --also or --keep for each word.")
    if candidates - chosen:
        messages.append("Decide each possible Arabic name form with --also or --keep.")
    if messages:
        raise RemovalChoicesRefusal(*messages, *(f"Possible word: {word!r}." for word in sorted(candidates)))


def remove_name(files, args):
    name = one_line(args.name)
    if not name:
        raise Refusal("Give the exact name with --name.")
    details = correction_details(args, check_fonts=False)
    day = date.today()
    project = read_project(files)
    arabic = arabic_name_matcher(name)
    also, keep = set(args.also), set(args.keep)
    scrub = NameReplacement(name, day, details["reason"], project["language"], arabic=arabic, also=also)
    # Removal details must not introduce a possible spelling into saved correction text.
    has_name = scrub.has_name if scrub.arabic_matches is None else (
        lambda value: any(scrub.arabic_matches.matches(value))
    )
    if any(has_name(value) for value in details.values()):
        raise Refusal("Use removal details that leave out the name.")

    try:
        candidates = set()
        if arabic is not None:
            discovery = NameReplacement(name, day, details["reason"], project["language"],
                                        arabic=arabic, candidates=candidates)
            plan_removal(files, discovery, day.isoformat(), details)
        check_name_choices(candidates, also, keep)
        changed, writes, retire, notices, font_assets = plan_removal(files, scrub, day.isoformat(), details)
        if any(Path(relative).suffix in (".html", ".pdf") for relative, _ in writes):
            ensure_weekly_ignores(files)
        if font_assets:
            write_transaction(files, font_assets.items())
        write_redaction(files, writes, retire=retire, weeks=changed, warnings=notices)
    except (RemovalChoicesRefusal, RemovalReasonRefusal):
        raise
    except Refusal as error:
        # A preflight refusal from a content reader can describe a user-supplied field.
        if any(scrub.has_name(message) for message in error.messages):
            raise Refusal("Check the saved files before trying the removal again.") from None
        raise

    return removal_receipt(changed) + notices
