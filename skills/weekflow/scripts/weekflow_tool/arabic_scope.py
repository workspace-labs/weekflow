"""Match Arabic scope decisions independently of how their letters were entered."""

import re

from .text_fields import arabic_words, one_line


SUBJECT = re.compile(
    r"\b(?:[وف])?(?:(?:[بكل]?ال|لل)|[بكل])?"
    r"(?:نطاق|مشروع|بناء|تنفيذ|تطوير|متطلبات)(?:ه|ها|هم|نا|كم|ك)?\b|\b(?:prd|scope|project|build)\b"
)
SCOPE_ARTIFACT = re.compile(
    r"\b[وف]?(?:(?:[بكل]?ال|لل)(?:مسوده|وثيقه|خطه)|[بكل]?(?:مسوده|خطه العمل)|موعد التسليم)\b"
)
STOP_ACTION = (
    r"ايقاف|[انيت]وقف|وقف|توقف|توقيف|متوقف|موقوف|انهاء|[انيت]نهي|منهي|تعليق|تعطيل|تجميد|فسخ|اسقاط"
)
ACTION = (
    r"اعتماد|[انيت]عتمد|معتمد|قبول|[انيت]قبل|مقبول|موافق[هت]|[انيت]?وافق|موافق|"
    r"مصادق[هت]|[انيت]?صادق|مصادق|تصديق|[انيت]?صدق|مصدق|اقرار|[انيت]قر|"
    r"اجاز[هت]|اجاز|[انيت]جيز|تفويض|توقيع|امضا[ءوي]|[انيت]?وقع|[انيت]مضي|"
    rf"رفض|[انيت]رفض|مرفوض|الغ(?:اء?)?|[انيت]لغي|ملغي|{STOP_ACTION}"
)
PREFIX = r"[وف]?(?:لل|[لس]?(?:ال)?)"
INFLECTION = r"(?:نا|وا|و|تم|تن|ت|ي|ان|ون|ين|ات)?"
OBJECT = r"(?:هما|هم|ها|ه)"
ENDING = rf"{INFLECTION}{OBJECT}?"
ACTION_WORD = rf"\b{PREFIX}(?:{ACTION}){ENDING}\b"
GREEN_LIGHT = r"(?:(?:[انيت]عطي|اعطاء|منح|[انيت]منح|اعطينا|منحنا) )?الضوء الاخضر"
SCOPE_ACTION = re.compile(rf"{ACTION_WORD}|\b{GREEN_LIGHT}\b")
STOP_WORK = re.compile(rf"\b{PREFIX}(?:{STOP_ACTION}){INFLECTION} (?:عن )?العمل\b")
START_IMPERATIVE = r"ابد(?:ا(?:وا)?|[ويء]وا)"
START_WORK = re.compile(
    rf"\b{PREFIX}(?:(?:بدء|{START_IMPERATIVE}|نبدا) (?:العمل|الان)|(?:باشروا|اكملوا) العمل)\b"
)
PRONOUN_ACTION = re.compile(
    rf"\b{PREFIX}(?:{ACTION}|قبل){INFLECTION}{OBJECT}\b"
    rf"|{ACTION_WORD}(?: (?:النهايي|المبديي)ه?)? (?:عليه|عليها|عليهما)\b"
)
VOCALIZED_APPROVAL = re.compile(r"\b[وف]?(?:ق(?:ُبِ?|َ?بِ)ل|مُ?وَ?ق[َّ]+ع|مُقَ?رّ)")
DAY_BEFORE = re.compile(r"[وف]?قبلها بيوم")
ACCEPTANCE_ACTOR = re.compile(r"^قبل (?:المالك|العميل|المدير|المسؤول|صاحب العمل)\b")
BARE = re.compile(
    rf"(?:(?:نعم|لا|غير|تمت?|جري|حصلت) )?(?:ال)?(?:{ACTION}){ENDING}(?: نهاييا)?"
    rf"|تعديلات اولا|المضي قدما|توقف العمل|{GREEN_LIGHT}"
)
ANNOTATED = re.compile(rf"^(?:(?:غير|لا) )?(?:ال)?(?:{ACTION}){ENDING}\s*[:(—–-]")
ADVANCE = re.compile(
    rf"\b(?:بدء|[وف]?{START_IMPERATIVE}|[وف]?انطلق(?:وا)?|نبدا|باشر|مباشره|"
    r"استمر|تابع|المضي|انتقل|الانتقال|لا تتابع|لا تكمل)\b"
)
BARE_TIMING_PREFIX = re.compile(r"(?:في|عند|قبل|بعد|مع|حتي)(?: (?:ان|تمام))?")
INFORMATION_QUESTION = re.compile(r"^(?:من|متي|لماذا|كيف|اين|اي|ما|ماذا|كم)\b")
DECISION_HEADING = re.compile(r"^10\s*[.)-]?\s*القرار[\s.؟?؛:]*$")


def is_scope_question(value):
    plain = arabic_words(value)
    return bool(DECISION_HEADING.fullmatch(plain) or (
        not INFORMATION_QUESTION.match(plain) and scope_wording(value)))


def scope_wording(value):
    plain = arabic_words(value).casefold()
    words = one_line(re.sub(r"[^\w]+", " ", plain))
    if BARE.fullmatch(words) or ANNOTATED.match(plain):
        return True
    if DAY_BEFORE.fullmatch(words) and not VOCALIZED_APPROVAL.search(value):
        return False
    if _action_outside_timing(PRONOUN_ACTION, words):
        return True
    if _action_outside_timing(STOP_WORK, words) or _action_outside_timing(START_WORK, words):
        return True
    if not SUBJECT.search(words):
        return bool(SCOPE_ARTIFACT.search(words) and _action_outside_timing(SCOPE_ACTION, words))
    if SCOPE_ACTION.search(words) or VOCALIZED_APPROVAL.search(value) or ACCEPTANCE_ACTOR.match(words):
        return True
    # Starting or proceeding with work is also a scope choice. A reference to
    # when work starts is a schedule description.
    return _action_outside_timing(ADVANCE, words)


def _action_outside_timing(pattern, words):
    return any(not BARE_TIMING_PREFIX.fullmatch(words[:match.start()].strip())
               for match in pattern.finditer(words))
