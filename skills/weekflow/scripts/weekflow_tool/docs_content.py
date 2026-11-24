"""Verify docs meeting words and decisions and retain the facts they came from."""

from hashlib import sha256
from html import unescape
from pathlib import Path, PureWindowsPath
import re
import unicodedata

from . import arabic_scope
from .documents import has_project_docs, read_meeting_form
from .meeting_language import translate
from .page import DOCS_LATER
from .storage import Refusal, WEEKLY
from .text_fields import arabic_words, one_line, required_text, validate_arabic_text, without_direction_marks


DECISION_ID = r"D-(?!0+\b)[0-9]{3,}"
DECISION_MARKER = re.compile(r"\{(" + DECISION_ID + r")\}")
VALID_ID = re.compile(DECISION_ID)
SCOPE_ROW = "10. the decision"
SCOPE_SUBJECT = r"(?:scope|project|prd|build|requirements document)"
SCOPE_OBJECT = re.compile(rf"\b{SCOPE_SUBJECT}\b")
SCOPE_STATUS = re.compile(
    r"\b(?:approved|accepted|authori[sz]ed|endorsed|signed(?:\s+off)?|"
    r"green\s+lit|locked|confirmed|rejected|stopped|cancelled|canceled|ended|abandoned|halted)\b"
)
SCOPE_ACTION = re.compile(
    r"\b(?:approv(?:e|es|ing)|accept(?:s|ing)?|authori[sz](?:e|es|ing)|"
    r"endors(?:e|es|ing)|sign(?:s|ing)?(?:\s+off)?|green\s+light|"
    r"lock(?:s|ing)?|confirm(?:s|ing)?|reject(?:s|ing)?|stopping|stops?|"
    r"cancel(?:s|l?ing)?|end(?:s|ing)?(?!\s+of\b)|abandon(?:s|ing)?|halt(?:s|ing)?|"
    r"(?:approval|acceptance|authori[sz]ation)\s+(?:of|for))\b"
    rf"|{SCOPE_STATUS.pattern}"
)
SCHEDULING_TARGET = (
    r"(?:(?:the|this|our|your)\s+)?"
    rf"(?:{SCOPE_SUBJECT}\s+(?:date|venue)s?|"
    rf"(?:date|venue)s?\s+(?:of|for)\s+(?:(?:the|this|our|your)\s+)?{SCOPE_SUBJECT})"
)
SCHEDULING_CONFIRMATION = re.compile(rf"confirm\s+{SCHEDULING_TARGET}")
SCHEDULING_DECISION_NOUN = r"(?:approval|acceptance|cancell?ation)"
SCHEDULING_DECISION_LABEL = re.compile(
    rf"{SCHEDULING_DECISION_NOUN}\s+(?:of|for)\s+{SCHEDULING_TARGET}"
    rf"|{SCHEDULING_TARGET}\s+{SCHEDULING_DECISION_NOUN}"
)
BARE_SCOPE_COMMAND = re.compile(
    r"^(?:(?:yes|no)\s+)?(?:approve(?:d)?|stop(?:ped)?|reject(?:ed)?|cancel(?:led)?|"
    r"sign off|go ahead|proceed|no go|changes first|stop work|end the work|approve or stop)$"
)
ANNOTATED_SCOPE_COMMAND = re.compile(
    r"^(?:approve(?:d)?|stop(?:ped)?|reject(?:ed)?|sign off)\s*[:(—–-]"
)
ADVANCE_SCOPE_COMMAND = re.compile(
    r"\b(?:go ahead|move forward|proceed|continue|move\s+(?:to|into))\s+"
    r"(?:(?:on|with|to|into)\s+)?(?:(?:this|the)\s+)?(?:project|build|prd)\b"
    r"|\b(?:start|begin)\s+(?:the\s+)?build(?:ing)?\b"
    r"|\b(?:do not|don t)\s+(?:proceed|go ahead|move forward)\b"
    r"|\bgive\s+(?:the\s+)?go ahead\b"
)
INFO_QUESTION = re.compile(r"^(?:who|when|why|what|how|where|which)\b")
BLOCK_MARK = re.compile(r"^\s*(?:#{1,6}\s+|[-+*]\s+|[0-9]+[.)]\s+)")
QUOTE_MARK = re.compile(r"^(?:\s*>\s*)+")
LINK = re.compile(r"(?<!\\)!?\[([^]\n]+)\]\((?:[^()\n]|\([^()\n]*\))*\)")
EMPHASIS = re.compile(r"(?<!\\)(\*{1,3}|_{1,3}|~~|\x60+)(?=\S)(.*?)(?<=\S)(?<!\\)\1")
ESCAPED_MARK = re.compile(r"""\\([!"#$%&'()*+,\-./:;<=>?@\[\]\\^_`{|}~])""")
DOCUMENT_SUFFIXES = {".md", ".markdown", ".txt", ".rst", ".adoc", ".org"}
DOCUMENT_BLOCK = re.compile(r"\n(?:[ \t]*\n+|(?=[ \t]*(?:#{1,6}\s|[-+*]\s|[0-9]+[.)]\s|\|)))")
# A standalone ? or ... or an inline (who?) can be the placeholder.
DOCUMENT_SENTENCE = re.compile(
    r"""\S.*?(?:(?<![\s.!?(\[])(?!\?+[)\]]\s+[a-z])[.!?]+["'”’)\]]*(?=\s|$)|$)"""
)
# Times can end a sentence. Keep their period inside the sentence when the
# next word is a lowercase continuation or the document's TBD placeholder.
DOCUMENT_INLINE_ABBREVIATION = re.compile(
    r"\b(?:(?i:mr|mrs|mx|dr|prof|rev|e\.g|i\.e)|Ms)\.(?=\s+\S)"
    r"|\b(?i:a\.m|p\.m)\.(?=\s+(?:[a-z]|TBD\b))"
)
ARABIC_SENTENCE_END = re.compile(
    r"""(?<![\s(\[])(?:[؟؛]+["'»”’)\]]*|[.!?]+["'»”’)\]]*(?=\s|$|[^\W\d_]))"""
)


def plain_markdown(value, *, blocks=True):
    if blocks:
        value = "\n".join(BLOCK_MARK.sub("", QUOTE_MARK.sub("", line)) for line in value.splitlines())
    value = LINK.sub(r"\1", value)
    value = EMPHASIS.sub(r"\2", value)
    return one_line(unescape(ESCAPED_MARK.sub(r"\1", value)))


def scope_wording(value):
    plain = unicodedata.normalize("NFKC", plain_markdown(value))
    plain = "".join(char for char in plain if unicodedata.category(char) != "Cf").casefold()
    words = one_line(re.sub(r"[^\w]+", " ", plain))
    if (BARE_SCOPE_COMMAND.fullmatch(words) or ANNOTATED_SCOPE_COMMAND.match(plain)
            or ADVANCE_SCOPE_COMMAND.search(words) or SCHEDULING_DECISION_LABEL.fullmatch(words)):
        return True

    # Allow a standalone scheduling confirmation. Mixed choices still get checked.
    if SCHEDULING_CONFIRMATION.fullmatch(words):
        return False
    scope = SCOPE_OBJECT.search(words)
    if not scope:
        return False
    action = SCOPE_ACTION.search(words)
    return bool(SCOPE_STATUS.search(words, scope.end()) or
                (action and SCOPE_OBJECT.search(words, action.end())))


def arabic_scope_wording(value):
    plain = plain_markdown(value)
    words = arabic_words(plain).casefold()
    return bool(arabic_scope.scope_wording(plain) or (
        SCOPE_ACTION.search(words) and arabic_scope.SUBJECT.search(words)))


def read_decisions(data, questions, *, validate_scope, arabic=False, allowed_latin=()):
    values = data.get("decisions", [])
    if not isinstance(values, list):
        raise Refusal("Write decisions as a list in the meeting content file.")
    decisions = []
    used_ids = set()
    used_questions = set()
    for item in values:
        identifier = item.get("id") if isinstance(item, dict) else None
        if not isinstance(identifier, str) or not VALID_ID.fullmatch(identifier) or identifier in used_ids:
            raise Refusal("Give each decision its own ID, like D-001.")
        raw = item.get("question")
        question = required_text(raw, f"the question for {identifier}")
        wording = plain_markdown(question, blocks=False).casefold()
        scope_question = (arabic_scope.is_scope_question(wording) if arabic else
                          wording.rstrip("?.") == SCOPE_ROW or (
                              not INFO_QUESTION.match(wording) and scope_wording(question)))
        if validate_scope and scope_question:
            raise Refusal(f"Leave the scope decision outside weekflow: {question!r}.")
        if questions is not None and raw not in questions:
            raise Refusal(f"Use the exact question from Still open for {identifier}: {question!r}.")
        if questions is not None:
            question = raw
        if question in used_questions:
            raise Refusal(f"Give the question {question!r} only once.")
        why = required_text(item.get("why"), f"why {identifier} is open")
        if arabic and validate_scope:
            validate_arabic_text(question, f"the question for {identifier}", allowed_latin)
            validate_arabic_text(why, f"why {identifier} is open", allowed_latin)
        options = decision_options(item.get("options"), identifier, validate_scope=validate_scope,
                                   arabic=arabic, allowed_latin=allowed_latin)
        decision = {"id": identifier, "question": question, "why": why, "options": options}
        if "said" in item:
            speakers = read_speakers(item["said"], identifier)
            if arabic and validate_scope:
                for speaker in speakers:
                    validate_arabic_text(speaker["who"], f"who spoke for {identifier}", allowed_latin)
                    validate_arabic_text(speaker["what"], f"what was said for {identifier}", allowed_latin)
            decision["said"] = speakers
        used_ids.add(identifier)
        used_questions.add(question)
        decisions.append(decision)
    return decisions, used_ids


def decision_options(values, identifier, *, validate_scope, arabic=False, allowed_latin=()):
    if not isinstance(values, list) or not 2 <= len(values) <= 4:
        raise Refusal(f"Give two to four options for {identifier}.")
    options = [required_text(value, f"an option for {identifier}") for value in values]
    labels = {option.casefold() for option in options}
    if len(labels) != len(options):
        raise Refusal(f"Use different options for {identifier}.")
    arabic_later = arabic and any(arabic_words(option) == arabic_words(translate("ar", "Decide next week"))
                                 for option in options)
    if labels & {DOCS_LATER, "decide next week"} or arabic_later:
        raise Refusal(f"Leave Decide next week to the tool for {identifier}.")
    if validate_scope:
        for option in options:
            if scope_wording(option) or arabic and arabic_scope_wording(option):
                raise Refusal(f"An option cannot approve or stop the scope: {option!r} for {identifier}.")
            if arabic:
                validate_arabic_text(option, f"an option for {identifier}", allowed_latin)
    return options


def read_speakers(rows, identifier):
    if not isinstance(rows, list) or not rows or any(not isinstance(row, dict) for row in rows):
        raise Refusal(f"Write said for {identifier} as a list of who and what.")
    return [{"who": required_text(row.get("who"), f"who spoke for {identifier}"),
             "what": required_text(row.get("what"), f"what was said for {identifier}")}
            for row in rows]


def source_path(value, sentence):
    relative = PureWindowsPath(value)
    if (relative.anchor or ".." in relative.parts or ":" in value or
            relative.is_relative_to(PureWindowsPath(WEEKLY)) or
            not relative.name or relative.name.startswith(".")):
        raise Refusal(f"Give an existing project document for {sentence!r}.")
    return relative


def document_sentences(text, *, arabic=False):
    inline_periods = {match.end() for match in DOCUMENT_INLINE_ABBREVIATION.finditer(text)}
    start = 0
    boundaries = ARABIC_SENTENCE_END if arabic else DOCUMENT_SENTENCE
    for sentence in boundaries.finditer(text):
        end = sentence.end()
        if end not in inline_periods:
            yield text[start:end].strip()
            start = end
    if arabic and text[start:].strip():
        yield text[start:].strip()


def live_document(files, relative, sentence, *, arabic=False):
    try:
        path = files.path(Path(*relative.parts))
        target = path.resolve()
        document = target.suffix.casefold() in DOCUMENT_SUFFIXES or (
            target.is_relative_to(files.path("docs").resolve()) and target.suffix.casefold() != ".env"
        )
        if (target.is_relative_to(files.path(WEEKLY).resolve()) or target.name.startswith(".")
                or not document or not path.is_file()):
            raise ValueError
        content = path.read_bytes()
        if b"\x00" in content:
            raise ValueError
        original = content.decode("utf-8-sig").replace("\r\n", "\n")
        if arabic:
            original = without_direction_marks(original)
        sentences = [sentence for block in DOCUMENT_BLOCK.split(original)
                     for sentence in document_sentences(plain_markdown(block), arabic=arabic)]
        return (plain_markdown(original), sentences), sha256(content).hexdigest()
    except (OSError, ValueError, Refusal):
        raise Refusal(f"Read {relative.as_posix()} as a project document for {sentence!r}.") from None


def is_document_quote(sentence, document, *, arabic=False):
    plain = plain_markdown(without_direction_marks(sentence) if arabic else sentence)
    original, sentences = document
    if not DECISION_MARKER.search(plain):
        quote = re.compile(rf"(?<!\w){re.escape(plain)}(?!\w)")
        return bool(plain and any(quote.search(candidate) for candidate in (sentences if arabic else (original,))))

    fragments = []
    for piece in DECISION_MARKER.split(plain)[::2]:
        words = piece.strip()
        if words:
            start = r"(?<!\w)" if re.match(r"\w", words[0]) else ""
            end = r"(?!\w)" if re.match(r"\w", words[-1]) else ""
            fragments.append(re.compile(f"{start}{re.escape(words)}{end}"))

    # Each marker may stand for any text between adjacent literal fragments
    # in one source sentence. Start each search after the previous match.
    for candidate in sentences:
        position = 0
        for index, fragment in enumerate(fragments):
            match = fragment.search(candidate, position)
            if match is None:
                break
            if arabic and index and "،" in candidate[position:match.start()]:
                break
            position = match.end()
        else:
            return bool(fragments)
    return False


def read_document(files, sections, known, *, check_live_proof, arabic=False, allowed_latin=()):
    if not isinstance(sections, list):
        raise Refusal("Write document as a list of titled sections in the meeting content file.")
    document = []
    sources = []
    digests = []
    seen = set()
    documents = {}
    for section in sections:
        if not isinstance(section, dict):
            raise Refusal("Give each document section a title and sentences.")
        title = required_text(section.get("title"), "a document section title")
        if arabic and check_live_proof:
            validate_arabic_text(title, "a document section title", allowed_latin)
        rows = section.get("sentences")
        if not isinstance(rows, list) or not rows:
            raise Refusal(f"Write the sentences for {title!r} as a list.")
        sentences = []
        for row in rows:
            if not isinstance(row, dict):
                raise Refusal(f"Give each sentence in {title!r} text and a source.")
            sentence = required_text(row.get("text"), f"a sentence in {title!r}")
            source = row.get("source")
            required_text(source, f"the source for {sentence!r}")
            markers = set(DECISION_MARKER.findall(sentence))
            remaining = DECISION_MARKER.sub("", sentence)
            if "{" in remaining or "}" in remaining:
                raise Refusal(f"Use markers like {{D-001}} in {sentence!r}.")
            if not markers <= known:
                raise Refusal(f"Use a listed decision for each marker in {sentence!r}.")
            if not any(char.isalnum() for char in remaining):
                raise Refusal(f"Put the decision inside a real sentence: {sentence!r}.")
            if arabic and check_live_proof:
                validate_arabic_text(remaining, f"a sentence in {title!r}", allowed_latin)
            seen.update(markers)

            if source == "owner":
                if check_live_proof and has_project_docs(files):
                    raise Refusal(f"Use a project document for {sentence!r}. Use owner only without project docs.")
                digest = sha256(sentence.encode("utf-8")).hexdigest()
            else:
                relative = source_path(source, sentence)
                source = relative.as_posix()
                if check_live_proof:
                    if source not in documents:
                        documents[source] = live_document(files, relative, sentence, arabic=arabic)
                    original, digest = documents[source]
                    if not is_document_quote(sentence, original, arabic=arabic):
                        raise Refusal(f"The sentence {sentence!r} was not found in {source}.")
            if check_live_proof:
                digests.append(digest)
            sources.append(source)
            sentences.append({"text": sentence, "source": source})
        document.append({"title": title, "sentences": sentences})
    if known - seen:
        missing = ", ".join(sorted(known - seen))
        raise Refusal(f"Put each open decision inside a sentence. Missing marker for {missing}.")
    return document, sources, digests


def read_docs_fields(files, data, *, check_live_proof, arabic=False, allowed_latin=()):
    stage = data.get("stage")
    if type(stage) is not int or not 1 <= stage <= 4:
        raise Refusal("Give the meeting stage as a number from 1 to 4.")
    if check_live_proof:
        form = read_meeting_form(files)
        if form.stopped:
            raise Refusal("The project stopped. The meeting form records Stop.")
        if stage < form.latest_stage:
            raise Refusal(f"Use stage {form.latest_stage} or later, as shown in Meetings held.")
        history = {str(key): number for key, number in form.stage_meetings.items()}
        questions = list(form.still_open) if form.exists else None
    else:
        history = data.get("stage_meetings")
        if not isinstance(history, dict) or any(
            key not in ("1", "2", "3", "4") or int(key) > stage or
            type(number) is not int or number < 1 for key, number in history.items()
        ):
            raise Refusal("Restore the saved held meetings.")
        questions = data.get("form_still_open")
        if "form_still_open" in data and (
            not isinstance(questions, list) or
            any(not isinstance(value, str) or not value.strip() for value in questions)
        ):
            raise Refusal("Restore the saved Still open questions.")
    # A dated removal notice can contain approval words without becoming a scope decision.
    decisions, identifiers = read_decisions(data, questions, validate_scope=check_live_proof,
                                             arabic=arabic, allowed_latin=allowed_latin)
    document, sources, digests = read_document(files, data.get("document"), identifiers,
                                               check_live_proof=check_live_proof,
                                               arabic=arabic, allowed_latin=allowed_latin)
    fields = {"stage": stage, "stage_meetings": history, "document": document, "decisions": decisions}
    if questions is not None:
        fields["form_still_open"] = questions
    if "settled" in data:
        settled = data["settled"]
        if not isinstance(settled, list):
            raise Refusal("Write settled as a list of exact earlier questions.")
        for question in settled:
            required_text(question, "a question in settled")
            if arabic and check_live_proof:
                validate_arabic_text(question, "a question in settled", allowed_latin)
        if len(settled) != len(set(settled)):
            raise Refusal("List each question only once in settled.")
        if set(settled).intersection(row["question"] for row in decisions):
            raise Refusal("A question in settled cannot also be a meeting decision.")
        fields["settled"] = settled
    return fields, sources, digests
