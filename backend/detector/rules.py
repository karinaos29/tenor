"""High-precision rules per tactic: the backup layer next to the classifier.

Deliberately narrow (few false alarms); the classifier provides recall. Each rule
skips the honest look-alikes named in the taxonomy ("past returns don't guarantee",
insured deposits, calm distant deadlines).
"""

import re

_I = re.IGNORECASE

RULES: dict[str, list[re.Pattern[str]]] = {
    "urgency": [
        re.compile(r"\b(?:only|just)\b.{0,30}\b(?:until|till|before)\b.{0,20}\b(?:today|tonight|\d{1,2}\s?(?:[ap]\.?\s?m\b|o'?clock))", _I),
        re.compile(r"\bdecide (?:now|today|right now|before we hang up)\b", _I),
        re.compile(r"\bprice (?:is )?(?:only )?locked\b", _I),
        re.compile(r"\b(?:this|the) (?:offer|price|window) (?:ends|closes|expires) (?:today|tonight|in (?:an|one|two|\d+) hours?)\b", _I),
        re.compile(r"\bwon'?t last (?:long|past today|beyond today)\b", _I),
    ],
    "scarcity": [
        re.compile(r"\b(?:rare|exclusive|once[- ]in[- ]a[- ]lifetime|limited) (?:opportunity|chance|offer|allocation)\b", _I),
        re.compile(r"\bonly (?:a (?:few|handful of)|\d+) (?:places|spots|slots|clients|investors|people)\b", _I),
        re.compile(r"\bnot (?:available|offered|open) to the (?:general )?public\b", _I),
        re.compile(r"\b(?:small|select|limited) (?:number|group|circle) of (?:select |chosen )?(?:clients|investors|people)\b", _I),
    ],
    "social_proof": [
        re.compile(r"\b(?:most|many|all|lots) of (?:my|our) (?:clients|customers|investors)\b.{0,40}\b(?:are|have|take|taking|bought|buying|went|invested|chose|choosing)\b", _I),
        re.compile(r"\b(?:thousands|hundreds) (?:of (?:people|investors|families) )?(?:have )?(?:already )?(?:joined|invested|signed up|bought in)\b", _I),
        re.compile(r"\beveryone(?:'s| is) (?:buying|getting in|doing (?:it|this)|investing)\b", _I),
    ],
    "secrecy": [
        re.compile(r"\bkeep (?:this|it|the deal) (?:between us|quiet|to yourself|confidential|secret)\b", _I),
        re.compile(r"\b(?:don'?t|do not|no need to|better not) (?:tell|mention (?:it|this) to|talk to|discuss (?:it|this) with|ask)\b.{0,30}\b(?:family|son|daughter|husband|wife|kids|children|friends?|bank|adviser|advisor|anyone)\b", _I),
        re.compile(r"\b(?:family|families|relatives|bank staff|banks?|advisers?) (?:often |usually |just )?(?:don'?t|won'?t|never) understand\b", _I),
    ],
    "guarantee": [
        re.compile(r"\bguarantee[ds]?\b", _I),
        re.compile(r"\brisk[- ]free\b", _I),
        re.compile(r"\bno risk\b", _I),
        re.compile(r"\bsure thing\b", _I),
        re.compile(r"\bcan'?t (?:lose|go wrong|fail)\b", _I),
        re.compile(r"\bwill (?:double|triple)\b", _I),
    ],
    "fomo_regret": [
        re.compile(r"\b(?:regret(?:ted|s)? it|kick (?:yourself|themselves)|miss(?:ing)? out|miss the boat|left behind)\b", _I),
        re.compile(r"\b(?:people|clients|those|everyone) who waited\b", _I),
    ],
    "skip_checks": [
        re.compile(r"\b(?:no|isn'?t|there'?s no) (?:time|need) for (?:the |any )?(?:paperwork|forms|documents)\b", _I),
        re.compile(r"\b(?:don'?t|do not) (?:need|have) to read\b", _I),
        re.compile(r"\bconfirm (?:it |everything |the shares |the order )?by phone\b", _I),
        re.compile(r"\bskip (?:the )?(?:paperwork|forms|checks)\b", _I),
        re.compile(r"\bno need to (?:check|verify|ask anyone)\b", _I),
    ],
    "authority": [
        re.compile(r"\bour (?:top |senior |own )?(?:analysts|experts|insiders?|research team)\b.{0,25}\b(?:say|says|predict|expect|believe|think|are certain)\b", _I),
        re.compile(r"\binsiders? (?:know|say|are buying)\b", _I),
        re.compile(r"\bthe next (?:apple|amazon|tesla|google|microsoft|nvidia|bitcoin)\b", _I),
        re.compile(r"\bendorsed by\b", _I),
    ],
}

# Honest look-alikes that cancel a rule match for that tactic.
EXCEPTIONS: dict[str, re.Pattern[str]] = {
    "guarantee": re.compile(
        r"\b(?:don'?t|do not|doesn'?t|does not|not|never|no one can|nobody can|can'?t|cannot)\s+(?:\w+\s+)?guarantee"
        r"|\binsured\b|\bup to the (?:legal )?limit\b|\bby law\b|\bdeposit (?:protection|insurance)\b",
        _I,
    ),
    "urgency": re.compile(r"\bno (?:rush|pressure|hurry)\b|\btake your time\b", _I),
    "fomo_regret": re.compile(r"\bwon'?t miss out\b|\bno need to worry about missing\b", _I),
}


def rule_tactics(sentence: str) -> set[str]:
    """Tactics whose rules match this sentence, minus honest look-alikes."""
    hits = set()
    for tactic, patterns in RULES.items():
        if any(p.search(sentence) for p in patterns):
            exception = EXCEPTIONS.get(tactic)
            if exception is None or not exception.search(sentence):
                hits.add(tactic)
    return hits
