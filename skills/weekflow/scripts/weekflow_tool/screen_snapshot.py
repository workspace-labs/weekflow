"""Freeze the screen map for a meeting and verify the files it shows."""

from .screens import (
    STATES, checked_picture, picture_details, picture_digest, picture_relative, read_saved_picture,
    read_screens, screen_id, screen_name,
)
from .storage import Refusal, iso_date
from .text_fields import one_line


PICTURE_SLOTS = ("picture", "previous_picture")
ROW_FIELDS = {"id", "order", "name", "state", *PICTURE_SLOTS}
PICTURE_FIELDS = {"file", "digest", "kind", "taken_on", "new", "checked_on"}


def read_app_ran(data):
    value = data.get("app_ran")
    if "app_ran" in data and type(value) is not bool:
        raise Refusal("Set app_ran to true or false in the meeting content.")
    return value


def read_screen_snapshot(data):
    app_ran = read_app_ran(data)
    if "meeting_screens" not in data:
        return []
    rows = data["meeting_screens"]
    if app_ran is None or not isinstance(rows, list) or not rows:
        raise Refusal("Restore the screen map saved for the meeting.")
    ids, last_order = set(), 0
    for row in rows:
        if not isinstance(row, dict) or set(row) != ROW_FIELDS:
            raise Refusal("Restore the screen map saved for the meeting.")
        code = screen_id(row["id"])
        name, state, order = (row[key] for key in ("name", "state", "order"))
        if (code in ids or name != screen_name(name, check_font=False) or state not in STATES.values()
                or type(order) is not int or order <= last_order):
            raise Refusal("Restore the screen map saved for the meeting.")
        ids.add(code)
        last_order = order
        for slot in PICTURE_SLOTS:
            picture = row[slot]
            if picture is not None:
                validate_snapshot_picture(code, slot, picture, app_ran)
    return rows


def validate_snapshot_picture(screen_id, slot, picture, app_ran):
    message = f"Restore the saved picture details for screen {screen_id}."
    if not isinstance(picture, dict) or set(picture) - {"removed", "unavailable"} != PICTURE_FIELDS:
        raise Refusal(message)
    saved = picture["file"]
    picture_relative(saved, screen_id)
    if picture_details(saved) != (picture["kind"], picture["taken_on"]):
        raise Refusal(message)
    digest = picture["digest"]
    if digest != picture_digest(saved):
        raise Refusal(message)
    if picture["checked_on"] is not None:
        iso_date(picture["checked_on"], f"The owner check for {saved}")
    if "unavailable" in picture and (picture["unavailable"] is not True or "removed" in picture
                                     or picture["new"] is not False or picture["checked_on"] is not None):
        raise Refusal(message)
    if "removed" in picture:
        notice = picture["removed"]
        if not isinstance(notice, str) or not notice or notice != one_line(notice):
            raise Refusal(message)
    if (type(picture["new"]) is not bool or
            (picture["new"] and (not app_ran or slot != "picture"
                                 or picture["kind"] != "screenshot" or "removed" in picture))):
        raise Refusal(message)


def picture_snapshot(reference):
    kind, taken_on = picture_details(reference)
    digest = picture_digest(reference)
    return {"file": reference, "digest": digest, "kind": kind, "taken_on": taken_on,
            "new": False, "checked_on": None}


def prepare_picture(files, picture):
    """Freeze an unavailable slot only when preparing a new page."""
    reference = picture["file"]
    data = read_saved_picture(files, reference, allow_missing=True)
    if data is None:
        picture.update(unavailable=True, new=False, checked_on=None)
    else:
        picture.pop("unavailable", None)
        if picture["checked_on"] is None:
            picture["checked_on"] = checked_picture(files, reference, picture["digest"])
    return data


def screen_snapshot(files, content, prior_content, last_held_date):
    rows = read_screens(files)
    app_ran = content.get("app_ran")
    if rows and app_ran is None:
        raise Refusal("Set app_ran to true or false in the meeting content when there are screens.")
    earlier = {row["id"]: row["picture"] for row in read_screen_snapshot(prior_content or {})}
    snapshot, pictures, warnings = [], {}, []
    for row in rows:
        current = previous = None
        expected_kind = "design" if row["state"] == "not built" else "screenshot"
        if row.get("picture") and row["picture_kind"] == expected_kind:
            current = picture_snapshot(row["picture"])
        if current is not None:
            shown = earlier.get(row["id"])
            if shown is not None and "removed" in shown:
                shown = None
            changed = shown is None or current["digest"] != shown["digest"]
            if changed:
                if shown is not None:
                    previous = dict(shown, new=False)
                elif row.get("previous_picture"):
                    previous = picture_snapshot(row["previous_picture"])
                if previous and (current["digest"] == previous["digest"]
                                 or (expected_kind == "design" and previous["kind"] != "design")):
                    previous = None
                current["new"] = bool(app_ran and current["taken_on"] and last_held_date
                                      and current["taken_on"] > last_held_date)
        for position, picture in (("current", current), ("earlier", previous)):
            if picture is None:
                continue
            data = prepare_picture(files, picture)
            if data is not None:
                pictures[picture["file"]] = data
            else:
                name, reference = row["name"], picture["file"]
                action = f" Save a new picture for {name}." if position == "current" else ""
                warnings.append(f"The {position} picture for {name} is no longer available ({reference}).{action}")
        snapshot.append({key: row[key] for key in ("id", "order", "name", "state")}
                        | {"picture": current, "previous_picture": previous})
    return snapshot, pictures, warnings


def picture_view(files, picture, prepared_pictures):
    if picture is None:
        return None
    removed = picture.get("removed")
    unavailable = picture.get("unavailable", False)
    data = None
    if removed is None and not unavailable:
        reference = picture["file"]
        data = (read_saved_picture(files, reference) if prepared_pictures is None
                else prepared_pictures[reference])
    return dict(data=data, removed=removed, unavailable=unavailable,
                **{key: picture[key] for key in ("kind", "taken_on", "new")})


def screen_map(files, content, *, prepared_pictures=None):
    return [dict(id=row["id"], name=row["name"], state=row["state"],
                 current=picture_view(files, row["picture"], prepared_pictures),
                 previous=picture_view(files, row["previous_picture"], prepared_pictures))
            for row in read_screen_snapshot(content)]


def require_screen_checks(files, content):
    unchecked = {}
    for row in read_screen_snapshot(content):
        for slot in PICTURE_SLOTS:
            picture = row[slot]
            if picture is None or "removed" in picture or "unavailable" in picture:
                continue
            saved = picture["file"]
            if not (picture["checked_on"] or checked_picture(files, saved, picture["digest"])):
                unchecked[saved] = (f'Ask the owner to check the picture for {row["name"]}. Then run '
                                    f'screen-check <project> --id {row["id"]} --file {saved}')
    if unchecked:
        raise Refusal(*unchecked.values())
