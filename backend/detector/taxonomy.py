"""Pressure-tactic taxonomy. One source of truth for the classifier, the rules layer,
the UI labels, the "say this" replies, and the briefs given to the data writers.

Paraphrased from the warning signs that financial regulators publish for investment
scams (urgency, secrecy, guaranteed returns, ...); no text is copied from them.
"""

from dataclasses import dataclass
from typing import Literal

TacticId = Literal["urgency", "scarcity", "social_proof", "secrecy", "guarantee", "fomo_regret", "skip_checks", "authority"]


@dataclass(frozen=True)
class Tactic:
    id: TacticId
    label: str  # shown to Eszter
    definition: str  # for labelers and the LLM baseline
    not_this: str  # the honest look-alike that must NOT be labeled
    say_this: str  # first-person reply, tenor-ui copy rules
    priority: int  # suggestion priority (see pipeline/suggestions.py)


TACTICS: tuple[Tactic, ...] = (
    Tactic(
        "urgency",
        "Rushing you",
        "Pushes a decision now: a deadline today or within hours, a price 'locked' until a time, 'decide before we hang up'.",
        "A real, distant deadline stated calmly with no push (e.g. a tax-year date, 'no rush').",
        "I don't make decisions on the same day. Can you email me the details first?",
        80,
    ),
    Tactic(
        "scarcity",
        "“Rare chance”",
        "Says the opportunity is rare, exclusive or limited: only a few places, a select group of clients, 'not offered to the public'.",
        "Plain product facts such as 'this account has no minimum'.",
        "If it's a good investment, it will still be there next week.",
        58,
    ),
    Tactic(
        "social_proof",
        "“Everyone's doing it”",
        "Uses what other people supposedly do or buy to push the listener: 'most of my clients take 10,000', 'thousands have already joined'.",
        "Neutral information without a push, e.g. 'some customers start with a monthly amount, then adjust'.",
        "What other people buy doesn't matter to me. I decide for myself.",
        62,
    ),
    Tactic(
        "secrecy",
        "Keeping it secret",
        "Asks the listener not to tell or consult family, friends, the bank or an adviser, or to keep the deal quiet.",
        "Normal privacy, e.g. 'I can't discuss your account with anyone else'.",
        "I always talk to my family about money. I'll call you back after that.",
        88,
    ),
    Tactic(
        "guarantee",
        "Promises no risk",
        "Promises returns or says there is no risk: 'guaranteed', 'risk-free', 'can't lose', 'a sure thing', 'it will double'.",
        "A legal deposit protection stated factually (e.g. 'deposits are insured up to the legal limit'), or 'past returns don't guarantee future results'.",
        "No one can guarantee a share price. Can you put that promise in writing?",
        85,
    ),
    Tactic(
        "fomo_regret",
        "Fear of missing out",
        "Plays on regret or missing out: 'people who waited regretted it', 'don't miss out', 'you'll kick yourself'.",
        "Neutral history without pressure, e.g. 'markets have gone up and down over time'.",
        "I'm comfortable missing a chance rather than rushing.",
        60,
    ),
    Tactic(
        "skip_checks",
        "Skipping the checks",
        "Discourages paperwork, written details or verification: 'no time for paperwork', 'I'll confirm by phone', 'you don't need to read it'.",
        "Offering to send documents or saying 'take your time to read it'.",
        "I'll only go ahead once I have everything in writing.",
        78,
    ),
    Tactic(
        "authority",
        "Borrowed authority",
        "Leans on vague experts, insiders or famous names to persuade: 'our analysts say', 'insiders know', 'it's the next Apple', 'endorsed by …'.",
        "Naming a specific, checkable source of a fact (e.g. 'the fund's factsheet lists the fee').",
        "Which document can I read that shows this?",
        55,
    ),
)

BY_ID: dict[str, Tactic] = {t.id: t for t in TACTICS}
TACTIC_IDS: tuple[str, ...] = tuple(t.id for t in TACTICS)


def labeling_guide() -> str:
    """The definitions as plain text, for data writers and the LLM baseline."""
    lines = []
    for t in TACTICS:
        lines.append(f"- {t.id}: {t.definition} NOT this: {t.not_this}")
    return "\n".join(lines)
