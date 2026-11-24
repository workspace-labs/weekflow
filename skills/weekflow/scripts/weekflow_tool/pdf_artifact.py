"""Recognize the client PDF for the current record without ReportLab."""

from hashlib import sha256
import json
import re

from .meetings import pdf_file
from .storage import Refusal


EOF = b"\n%%EOF\n"
MARKER = re.compile(rb"\n% Weekflow ([0-9a-f]{64}) ([0-9a-f]{64})\n%%EOF\n\Z")
FONT_FALLBACK = b"\n% Weekflow Studio font fallback"


def record_digest(view, *, legacy=False):
    total = view.decisions_left if view.is_docs else view.end_after.isoformat()
    record = (view.fingerprint, view.week["held"], view.attendees,
              view.week.get("answers", []), total)
    override = view.design.pdf_override
    if override is not None:
        record += (override,)
    layout = view.design.pdf_layout
    if layout is not None:
        record += (layout,)
    if view.build_deciders and not legacy:
        record += (view.build_deciders,)
    return sha256(json.dumps(record, sort_keys=True).encode("ascii")).hexdigest().encode("ascii")


def stamp_pdf(data, view):
    # This comment follows startxref, so adding it leaves PDF object offsets intact.
    if not data.startswith(b"%PDF-") or not data.endswith(EOF):
        raise Refusal("The PDF could not be finished.")
    if view.design.missing_roles:
        data = data[:-len(EOF)] + FONT_FALLBACK + EOF
    checksum = sha256(data).hexdigest().encode("ascii")
    return data[:-len(EOF)] + b"\n% Weekflow " + record_digest(view) + b" " + checksum + EOF


def current_pdf(files, view, *, allow_stale=False):
    path = files.write_path(pdf_file(view.week["number"]))
    if path.is_file():
        data = path.read_bytes()
        marker = MARKER.search(data)
        receipts = {record_digest(view)}
        if view.week.get("locked_on") and view.build_deciders:
            receipts.add(record_digest(view, legacy=True))
        if marker and (allow_stale or marker[1] in receipts):
            original = data[:marker.start()] + EOF
            if original.startswith(b"%PDF-") and sha256(original).hexdigest().encode("ascii") == marker[2]:
                return data
    return None


def used_font_fallback(data):
    marker = MARKER.search(data)
    return bool(marker and data[:marker.start()].endswith(FONT_FALLBACK))


def require_current_pdf(files, view, *, allow_stale=False):
    if current_pdf(files, view, allow_stale=allow_stale) is None:
        raise Refusal("Make the current PDF with client-copy first.")
