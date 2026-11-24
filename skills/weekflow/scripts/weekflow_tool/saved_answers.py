"""Read only the answers selected on the confirmed meeting page."""

import json
import os
from pathlib import Path
from stat import S_ISREG

from .page import ANSWERS, DOCS_LATER
from .storage import Refusal


LIMIT = 64 * 1024
VALUES = {key for key, _ in ANSWERS}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Repeated key")
        result[key] = value
    return result


def read_answers_file(filename):
    try:
        path = Path(filename)
        if not S_ISREG(path.lstat().st_mode):
            raise OSError
        flags = (os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
                 | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(os.open(path, flags), "rb") as stream:
            if not S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise OSError
            data = stream.read(LIMIT + 1)
    except (OSError, ValueError):
        raise Refusal("Choose a readable regular answers file.") from None
    if len(data) > LIMIT:
        raise Refusal("Use an answers file of 64 KB or less.")
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=unique_object)
    except (ValueError, RecursionError):
        raise Refusal("Use valid JSON with unique keys from Save answers.") from None


def selected_answers(args, view):
    if args.answers is not None:
        saved = read_answers_file(args.answers)
        if not isinstance(saved, dict) or set(saved) != {"week", "fingerprint", "answers"}:
            raise Refusal("The answers file must contain only week, fingerprint and answers.")
        if type(saved["week"]) is not int or saved["week"] != view.week["number"]:
            raise Refusal("Use an answers file for this meeting number.")
        if saved["fingerprint"] not in view.answer_fingerprints:
            raise Refusal("Use answers saved from the confirmed meeting page.")
        answers = saved["answers"]
        if not isinstance(answers, dict):
            raise Refusal("Save answers as an object from decision IDs to answers.")
    else:
        answers = {}
        for entry in [] if args.answer == [""] else args.answer:
            change_id, separator, value = entry.partition("=")
            if not separator or not change_id or change_id in answers:
                example = "D-001=option" if view.is_docs else "C-001=yes"
                raise Refusal(f"Give each manual answer once in the form {example}.")
            answers[change_id] = value
    if view.is_docs:
        return checked_docs_answers(answers, view.content["decisions"])
    known = {change["id"] for change in view.changes}
    if not answers.keys() <= known:
        raise Refusal("Give answers only for decisions on the confirmed meeting page.")
    if any(not isinstance(answer, str) or answer not in VALUES for answer in answers.values()):
        raise Refusal("Use yes, later or no for each answer.")
    return answers


def checked_docs_answers(answers, decisions):
    known = {decision["id"]: decision["options"] for decision in decisions}
    if not answers.keys() <= known.keys():
        raise Refusal("Give answers only for decisions on the confirmed meeting page.")
    for identifier, answer in answers.items():
        if not isinstance(answer, str) or (answer != DOCS_LATER and answer not in known[identifier]):
            raise Refusal(f"Use a shown option or later for {identifier}.")
    return answers
