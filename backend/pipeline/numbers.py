"""Turn spoken numbers into digits while remembering where each character came from.

Deepgram's smart_format usually writes digits ("10,000 shares", "3PM"), but not
always, and scripts are written in words. Rules run on the normalized text; spans
map back to the original words so the UI can underline exactly what was said.

    norm = normalize("the shares are forty-two cents each")
    norm.text                       # "the shares are 42 cents each"
    norm.original_span(15, 17)      # (15, 24) -> "forty-two"
"""

import re
from dataclasses import dataclass

UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}  # fmt: skip
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
SCALES = {"hundred": 100, "thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000}
ORDINALS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8,
    "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12, "thirteenth": 13, "fourteenth": 14,
    "fifteenth": 15, "sixteenth": 16, "seventeenth": 17, "eighteenth": 18, "nineteenth": 19,
    "twentieth": 20, "thirtieth": 30,
}  # fmt: skip
NUMBER_WORDS = set(UNITS) | set(TENS) | set(SCALES)

_WORD = re.compile(r"[A-Za-z]+(?:-[A-Za-z]+)*")
_FRACTIONS = [
    (re.compile(r"\ba quarter (?=percent|per cent|%)", re.I), "0.25 "),
    (re.compile(r"\bhalf a (?=percent|per cent|%)", re.I), "0.5 "),
    (re.compile(r"\b(\d+) hundredths of a (?=percent|per cent)", re.I), None),
    (re.compile(r"\b(\d+) tenths of a (?=percent|per cent)", re.I), None),
]


@dataclass
class Normalized:
    text: str
    _origin: list[tuple[int, int]]  # per normalized char: (start, end) in the original

    def original_span(self, start: int, end: int) -> tuple[int, int]:
        if start >= end:
            return (self._origin[start][0], self._origin[start][0]) if start < len(self._origin) else (0, 0)
        return self._origin[start][0], self._origin[end - 1][1]


class _Builder:
    def __init__(self) -> None:
        self.parts: list[str] = []
        self.origin: list[tuple[int, int]] = []

    def keep(self, original: str, start: int) -> None:
        self.parts.append(original)
        self.origin.extend((start + i, start + i + 1) for i in range(len(original)))

    def replace(self, new: str, start: int, end: int) -> None:
        self.parts.append(new)
        self.origin.extend((start, end) for _ in new)

    def build(self) -> Normalized:
        return Normalized("".join(self.parts), self.origin)


def _value(words: list[str]) -> int | None:
    """Parse e.g. ["forty", "two"], ["ten", "thousand"], ["twenty", "one", "hundred"]."""
    total, current, seen = 0, 0, False
    for word in words:
        if word in UNITS:
            current += UNITS[word]
        elif word in TENS:
            current += TENS[word]
        elif word == "hundred":
            current = max(current, 1) * 100
        elif word in SCALES:
            total += max(current, 1) * SCALES[word]
            current = 0
        else:
            return None
        seen = True
    return total + current if seen else None


def _words_to_digits(text: str) -> Normalized:
    out = _Builder()
    tokens = [(m.group(0), m.start(), m.end()) for m in _WORD.finditer(text)]
    pos = 0
    i = 0
    while i < len(tokens):
        word, start, end = tokens[i]
        parts = word.lower().split("-")
        if word.lower() in ORDINALS or (len(parts) == 2 and parts[0] in TENS and parts[1] in ORDINALS):
            value = ORDINALS.get(word.lower()) or TENS[parts[0]] + ORDINALS[parts[1]]
            out.keep(text[pos:start], pos)
            out.replace(str(value), start, end)
            pos = end
            i += 1
            continue
        # "a hundred", "a thousand"
        lead_a = word.lower() == "a" and i + 1 < len(tokens) and tokens[i + 1][0].lower() in SCALES
        if not (all(p in NUMBER_WORDS for p in parts) or lead_a):
            i += 1
            continue
        j, words, seq_end = i, [], end
        if lead_a:
            words, j = ["one"], i + 1
        while j < len(tokens):
            w, s, e = tokens[j]
            if j > i and text[seq_end:s].strip():
                break  # punctuation between words ends the number
            sub = w.lower().split("-")
            if (
                w.lower() == "and"
                and words
                and words[-1] in SCALES
                and j + 1 < len(tokens)
                and all(p in NUMBER_WORDS for p in tokens[j + 1][0].lower().split("-"))
            ):
                seq_end = e
                j += 1  # "one hundred and fifty" is one number; "five and six" is two
                continue
            if not all(p in NUMBER_WORDS for p in sub):
                break
            words.extend(sub)
            seq_end = e
            j += 1
        value = _value(words)
        if value is None:
            i += 1
            continue
        out.keep(text[pos:start], pos)
        out.replace(str(value), start, seq_end)
        pos = seq_end
        i = j
    out.keep(text[pos:], pos)
    return out.build()


def normalize(text: str) -> Normalized:
    norm = _words_to_digits(text)
    # Fractions of a percent ("a quarter percent", "three hundredths of a percent").
    for pattern, fixed in _FRACTIONS:
        while m := pattern.search(norm.text):
            if fixed is not None:
                replacement = fixed
            else:
                divisor = 100 if "hundredth" in m.group(0).lower() else 10
                replacement = f"{int(m.group(1)) / divisor:g} "
            start, end = norm.original_span(m.start(), m.end())
            origin = norm._origin[: m.start()] + [(start, end)] * len(replacement) + norm._origin[m.end() :]
            norm = Normalized(norm.text[: m.start()] + replacement + norm.text[m.end() :], origin)
    return norm
