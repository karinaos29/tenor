"""Requests for private details, and the digits of an answer. Rules only, no model.

Two jobs for the secret guard (pipeline/safety.py):
- `find_request(sentence)`: does this sentence ask for a code, PIN, password, card
  details, a recovery phrase, control of the computer, or identity details? A request
  needs an asking cue ("read me", "can you tell me", "what's your") next to the thing
  asked for, so "we sent you a code" alone isn't one. Warnings and refusals
  ("we will never ask for your PIN", "I don't give out codes") are skipped.
- `code_run(text)`: the longest run of code characters in a text, counting digits,
  digit words ("four seven two"), "double seven" and single letters, so an answer
  being read out is noticed after the first few characters.

No secret is ever kept: callers get the kind of request and a count, never the digits.
"""

import re
from dataclasses import dataclass

from pipeline.events import SecretKind, SecretLevel

_I = re.IGNORECASE


@dataclass(frozen=True)
class SecretInfo:
    kind: SecretKind
    level: SecretLevel  # stop: never read it out; check: find out who's calling first
    label: str  # shown to Eszter: "The caller asked for your <label>."


INFO: dict[str, SecretInfo] = {
    i.kind: i
    for i in (
        SecretInfo("one_time_code", "stop", "one-time code"),
        SecretInfo("pin", "stop", "PIN"),
        SecretInfo("password", "stop", "password"),
        SecretInfo("card", "stop", "card details"),
        SecretInfo("recovery_phrase", "stop", "recovery phrase"),
        SecretInfo("remote_access", "stop", "access to your computer"),
        SecretInfo("account_number", "check", "account number"),
        SecretInfo("identity", "check", "personal details"),
    )
}

# Asking for something to be said, read or handed over. Not "enter" or "type": an honest
# caller may ask her to type a code into her own app, which doesn't give it to them.
_ASK = re.compile(
    r"\b(?:read|tell|give|say|repeat|confirm|share|provide|verify|spell)\b(?:\s+(?:it|that|them|this))?\s+(?:to\s+)?(?:me|us|out|back)\b"
    r"|\b(?:can|could|would|will)\s+you\s+(?:please\s+|just\s+)?(?:read|tell|give|say|repeat|confirm|share|provide|verify|spell|let\s+me\s+know)\b"
    r"|\b(?:please|just)\s+(?:read|tell|give|say|repeat|confirm|share|provide|verify|spell)\b"
    r"|\bwhat(?:'s|\s+is|\s+are)\s+(?:your|the)\b"
    r"|\b(?:i|we)(?:'ll|\s+will)?(?:\s+(?:just|only|also|still|really))?\s+need\b"
    r"|\b(?:can|could|may)\s+(?:i|we)\s+(?:have|get|take)\b"
    r"|\bsend\s+(?:me|us)\b",
    _I,
)

# What is asked for, per kind. Order matters: the first match names the request
# ("social security number" is identity, not a security code).
_OBJECTS: list[tuple[SecretKind, re.Pattern[str]]] = [
    ("recovery_phrase", re.compile(r"\b(?:seed|recovery|secret|backup)\s+(?:phrase|words)\b|\bprivate\s+key\b|\b(?:twelve|twenty[- ]four|12|24)\s+words\b", _I)),
    ("card", re.compile(
        r"\bcard\s+(?:number|details)\b|\bnumbers?\s+on\s+(?:the\s+(?:front|back)\s+of\s+)?your\s+card\b"
        r"|\b(?:cvv|cvc|csc|cv2)\b|\b(?:security\s+(?:code|number)|three\s+digits|3\s+digits)\s+on\s+the\s+back\b"
        r"|\b(?:expiry|expiration)\s+date\b|\blast\s+(?:four|4)\s+(?:digits|numbers)\s+of\s+your\s+card\b",
        _I,
    )),
    ("identity", re.compile(
        r"\b(?:social\s+security|national\s+insurance|passport|driver'?s\s+licen[cs]e|tax\s+id|id)\s+number\b"
        r"|\b(?:ssn|date\s+of\s+birth|mother'?s\s+maiden\s+name)\b",
        _I,
    )),
    ("one_time_code", re.compile(
        r"\b(?:one[- ]time|verification|security|confirmation|authori[sz]ation|access|login|text|sms|activation)\s+(?:code|number|passcode)\b"
        r"|\b(?:code|numbers?|digits)\s+(?:that\s+|which\s+)?(?:we|i|they|the\s+bank)\s+(?:just\s+)?(?:sent|texted|messaged)\b"
        r"|\b(?:code|numbers?|digits)\s+(?:in|on|from)\s+(?:the|that|your)\s+(?:text|message|sms|phone|screen|email|app)\b"
        r"|\b(?:\w+[- ])?digit\s+code\b|\bthe\s+code\b",
        _I,
    )),
    ("pin", re.compile(r"\bpin(?:\s+(?:number|code))?\b", _I)),
    ("password", re.compile(r"\b(?:password|passcode|pass\s+word|passphrase|login\s+details|online\s+banking\s+(?:details|login))\b", _I)),
    ("account_number", re.compile(r"\b(?:account|routing|sort|iban|bank)\s+(?:number|code|details)\b", _I)),
]

# Asking for control of the computer needs no separate asking cue: the ask is the request.
_REMOTE = re.compile(
    r"\b(?:download|install|open|get)\b.{0,30}\b(?:anydesk|any\s+desk|teamviewer|team\s+viewer|quick\s?support|ultraviewer|remote\s+(?:access|desktop|support)\s+(?:app|program|tool))\b"
    r"|\b(?:give|let)\s+(?:me|us)\s+(?:have\s+)?(?:remote\s+)?(?:access\s+to|into|control\s+of)\s+your\s+(?:computer|laptop|pc|phone|screen)\b"
    r"|\b(?:share|show\s+me)\s+your\s+screen\b"
    r"|\b(?:connect|log\s+in)\s+to\s+your\s+(?:computer|laptop|pc)\b",
    _I,
)

# Warnings and refusals look like requests: "We will never ask for your PIN",
# "Don't share that code with anyone", "I don't give out my password".
_NEGATED = re.compile(
    r"\b(?:never|don'?t|do\s+not|won'?t|will\s+not|wouldn'?t|shouldn'?t|should\s+not|can'?t|cannot|not)\s+"
    r"(?:\w+\s+){0,3}?(?:ask|share|give|tell|read|say|send|disclose|reveal|need|request|type|enter|confirm|provide|repeat|hand)\b"
    r"|\b(?:no\s+one|nobody|no-one)\b.{0,40}\b(?:ask|need|call)"
    r"|\bkeep\s+(?:it|that|this|them|your\s+\w+)\s+(?:to\s+yourself|private|secret|safe)\b",
    _I,
)


# "Can you read it to me?" after "We sent you a code": the ask points back at a detail
# mentioned just before. The pointer must end the ask ("read it to me", "read them out"),
# so "confirm that you got it" and a half-heard "to confirm it, see" don't count.
_ASK_POINTER = re.compile(
    r"\b(?:read|tell|give|say|repeat|confirm|share|provide|spell)\s+(?:me\s+|us\s+)?"
    r"(?:it|that|them|those|this(?:\s+code)?|the\s+numbers?|the\s+digits|the\s+letters)\b"
    r"(?=\s*(?:(?:to|for)\s+(?:me|us)\b|out\b|back\b|please\b|now\b|[?.!]|$))"
    r"|\bwhat\s+(?:does|did)\s+it\s+say\b|\bwhat\s+it\s+says\b",
    _I,
)

# Clauses: a refusal in one ("don't tell your son") mustn't hide a request in the next.
_CLAUSE = re.compile(r"[,;:]|\b(?:but|so|then)\b", _I)


@dataclass(frozen=True)
class Request:
    kind: SecretKind
    end: int  # where the request ends in the sentence; an answer starts after it


def _clauses(sentence: str) -> list[tuple[int, str]]:
    out, start = [], 0
    for m in _CLAUSE.finditer(sentence):
        out.append((start, sentence[start : m.start()]))
        start = m.end()
    out.append((start, sentence[start:]))
    return [(s, c) for s, c in out if c.strip()]


def _object(clause: str) -> tuple[SecretKind, int] | None:
    for kind, pattern in _OBJECTS:
        if m := pattern.search(clause):
            return kind, m.end()
    return None


def find_request(sentence: str, recent: SecretKind | None = None) -> Request | None:
    """The private detail this sentence asks for, or None. `recent` is a detail mentioned
    shortly before (see `mentioned`), for asks that point back at it."""
    for start, clause in _clauses(sentence):
        if _NEGATED.search(clause):
            continue
        if m := _REMOTE.search(clause):
            return Request("remote_access", start + m.end())
        ask = _ASK.search(clause)
        obj = _object(clause)
        if ask and obj:
            return Request(obj[0], start + max(obj[1], ask.end()))
        # What follows the pointer is read from the whole sentence: the clause split drops commas.
        if recent is not None and (p := _ASK_POINTER.search(sentence[start:])) and p.start() < len(clause):
            return Request(recent, start + p.end())
    return None


def mentioned(sentence: str) -> SecretKind | None:
    """A private detail talked about, outside a warning ("we just sent you a code"; not
    "we will never ask for your code, your PIN or your password")."""
    if _NEGATED.search(sentence):
        return None
    for _, clause in _clauses(sentence):
        if not _NEGATED.search(clause) and (obj := _object(clause)):
            return obj[0]
    return None


# --- the answer being read out ----------------------------------------------------------

_DIGIT_WORDS = {"zero", "oh", "o", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "niner"}
_REPEAT = {"double": 2, "triple": 3}
_JOINERS = {"and", "then", "dash", "hyphen", "space"}
_TOKEN = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)*|\d+|[^\sA-Za-z\d]")
_SEPARATORS = {",", "-", ".", "/", "–", "—"}


def code_run(text: str) -> int:
    """The longest run of code characters in `text`.

    "It says four, seven, two" -> 3; "4729" -> 4; "double seven three" -> 3;
    "one moment please" -> 1; "a six digit code" -> 1.
    """
    best = run = 0
    repeat = 1
    tokens = _TOKEN.findall(text)
    for i, tok in enumerate(tokens):
        low = tok.lower()
        if tok.isdigit():
            run += len(tok) * repeat
        elif low in _DIGIT_WORDS and (low not in {"o", "oh"} or _next_is_code(tokens, i) or run > 0):
            run += repeat
        elif low in _REPEAT and _next_is_code(tokens, i):
            repeat = _REPEAT[low]
            continue
        elif len(tok) == 1 and tok.isalpha() and tok.upper() not in {"A", "I"} and (run > 0 or _next_is_code(tokens, i)):
            run += repeat  # a spelled-out letter inside a code: "B 7 4"
        elif tok in _SEPARATORS or (low in _JOINERS and run > 0):
            continue
        else:
            run = 0
        repeat = 1
        best = max(best, run)
    return best


def _next_is_code(tokens: list[str], i: int) -> bool:
    for tok in tokens[i + 1 :]:
        if tok in _SEPARATORS:
            continue
        return tok.isdigit() or tok.lower() in _DIGIT_WORDS - {"o", "oh"} or (len(tok) == 1 and tok.isalpha() and tok.upper() not in {"A", "I"})
    return False
