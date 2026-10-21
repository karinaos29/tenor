"""Build the decision memo from the call's facts. Deterministic: no LLM here.

Every item links to its moment in the call (`t`) and names its source. Tenor never
says buy or sell; the memo lays out what was offered, what didn't match, and the
pressure, and leaves the decision to the reader.
"""

from dataclasses import dataclass, field
from datetime import datetime

from detector.taxonomy import BY_ID
from pipeline.events import (
    Claim,
    Memo,
    MemoItem,
    MemoSection,
    Offer,
    ResearchItem,
    RiskUpdated,
    Suggestion,
    TacticFlag,
    Utterance,
    utc_now,
)

STATUS_LABEL = {
    "false": "Doesn't match data",
    "verified": "Matches data",
    "not_found": "No evidence found",
    "unverifiable": "Couldn't verify",
    "checking": "Not checked",
}
STATUS_TONE = {"false": "danger", "verified": "ok", "not_found": "warn", "unverifiable": "neutral", "checking": "neutral"}
LEVEL_TONE = {"low": "ok", "medium": "warn", "high": "danger", "critical": "danger"}
HEADLINE = {
    "critical": "This call showed several serious warning signs.",
    "high": "This call showed warning signs worth taking seriously.",
    "medium": "Some things on this call are worth checking before you decide.",
    "low": "Tenor didn't notice pressure or claims that contradict the data.",
}
NOTE = (
    "Tenor checks what the caller said against data and points out pressure. It doesn't tell you whether to "
    "invest; the decision is yours. Facts come from the sources named; nothing here was guessed."
)


@dataclass
class CallRecord:
    call_id: str = ""
    started_at: datetime = field(default_factory=utc_now)
    ended_at: datetime | None = None
    source: str = "mic"
    replay_id: str | None = None
    utterances: dict[str, Utterance] = field(default_factory=dict)  # final lines, in order
    user_indices: set[int] | None = None
    offer: Offer | None = None
    claims: dict[str, Claim] = field(default_factory=dict)
    research: dict[str, ResearchItem] = field(default_factory=dict)
    flags: list[TacticFlag] = field(default_factory=list)
    say_this: dict[str, Suggestion] = field(default_factory=dict)
    risk: RiskUpdated | None = None

    def role(self, u: Utterance) -> str:
        if self.user_indices is None:
            return u.speaker
        return "user" if u.speaker_index in self.user_indices else "caller"

    def t_of(self, utterance_id: str | None) -> float | None:
        u = self.utterances.get(utterance_id or "")
        return u.t_start if u else None


def clock(t: float | None) -> str:
    if t is None:
        return ""
    return f"{int(t // 60)}:{int(t % 60):02d}"


def _claim_item(c: Claim, t: float | None) -> MemoItem:
    label = STATUS_LABEL.get(c.status, c.status)
    if c.metric in ("price_change", "return") and c.claimed_value is not None:
        text = f"Claimed {c.claimed_value:+g}% {c.period or ''}".strip() + (f" ({c.subject})" if c.subject else "")
        data = f"Data: {c.actual_value:+g}% ({c.note})" if c.actual_value is not None else (c.note or "")
    elif c.metric == "price" and c.claimed_value is not None:
        text = f"Offered {c.subject or ''} at ${c.claimed_value:.2f} a share".replace("  ", " ")
        data = f"Market price: ${c.actual_value:.2f} ({c.note})" if c.actual_value is not None else (c.note or "")
    elif c.metric == "guarantee":
        text = "Promised a guaranteed return" + (f" ({c.claimed_value:+g}% {c.period or ''})".rstrip() if c.claimed_value else "")
        data = c.note or ""
    else:
        text = f"“{c.text}”"
        data = c.note or ""
    return MemoItem(text=text, detail=f"{label}. {data}".strip(), t=t, source=c.source or "", tone=STATUS_TONE.get(c.status, "neutral"))  # type: ignore[arg-type]


def sections(r: CallRecord) -> list[MemoSection]:
    out: list[MemoSection] = []

    glance: list[MemoItem] = []
    if r.risk is not None:
        glance.append(MemoItem(text=f"Risk: {r.risk.level.capitalize()} ({r.risk.score} of 100)", tone=LEVEL_TONE[r.risk.level]))  # type: ignore[arg-type]
        for reason in r.risk.reasons[:4]:
            glance.append(MemoItem(text=reason.label, detail=f"+{reason.points}"))
    out.append(MemoSection(id="glance", title="At a glance", items=glance, empty="Not enough was checked to give a risk level."))

    who: list[MemoItem] = []
    o = r.offer
    if o and o.caller_name:
        who.append(MemoItem(text=f"Caller: {o.caller_name.display}", t=o.caller_name.t, source="From the call"))
    if o and o.firm:
        who.append(MemoItem(text=f"Firm: {o.firm.display}", t=o.firm.t, source="From the call"))
    for item in r.research.values():
        if item.topic == "firm" and item.status == "ready":
            tone = "danger" if item.finding == "not_registered" else ("ok" if item.finding == "registered" else "neutral")
            who.append(MemoItem(text=item.summary, source=item.source, tone=tone))  # type: ignore[arg-type]
    out.append(MemoSection(id="who", title="Who called", items=who, empty="The caller didn't say a name or firm that Tenor could pick up."))

    offer: list[MemoItem] = []
    if o:
        labels = [("instrument", "Investment"), ("price", "Price"), ("quantity", "Quantity"), ("total", "Total"),
                  ("deadline", "Deadline"), ("payment", "Payment"), ("fees", "Fees")]  # fmt: skip
        for name, label in labels:
            term = getattr(o, name)
            if term is None:
                continue
            was = next((h.old.display for h in reversed(o.history) if h.field == name), None)
            detail = f"was {was}" if was else ""
            source = "price × quantity" if term.source == "computed" else f"said at {clock(term.t)}"
            offer.append(MemoItem(text=f"{label}: {term.display}", detail=detail, t=term.t, source=source, tone="warn" if was else "neutral"))
    out.append(MemoSection(id="offer", title="What was offered", items=offer, empty="No offer terms were stated."))

    order = {"false": 0, "not_found": 1, "unverifiable": 2, "verified": 3, "checking": 4}
    claims = sorted(r.claims.values(), key=lambda c: order.get(c.status, 9))
    out.append(
        MemoSection(
            id="claims", title="Claims checked against data",
            items=[_claim_item(c, r.t_of(c.utterance_id)) for c in claims], empty="The caller made no claims Tenor could check.",
        )  # fmt: skip
    )

    by_tactic: dict[str, list[TacticFlag]] = {}
    for f in r.flags:
        by_tactic.setdefault(f.tactic, []).append(f)
    pressure = []
    for tactic, flags in sorted(by_tactic.items(), key=lambda kv: (all(f.severity == "mild" for f in kv[1]), kv[0])):
        strong = any(f.severity == "strong" for f in flags)
        first = flags[0]
        times = f" ({len(flags)} times)" if len(flags) > 1 else ""
        pressure.append(
            MemoItem(
                text=f"{BY_ID[tactic].label}{times}", detail=f"“{first.quote}”", t=r.t_of(first.utterance_id),
                source="Strong" if strong else "Mild", tone="danger" if strong else "warn",
            )  # fmt: skip
        )
    out.append(MemoSection(id="pressure", title="Pressure you were put under", items=pressure, empty="Tenor didn't notice pressure tactics."))

    top = sorted(r.say_this.values(), key=lambda s: -s.priority)[:6]  # the most important ones only
    questions = [MemoItem(text=f"“{s.text}”", detail=s.title) for s in top]
    out.append(MemoSection(id="questions", title="Questions to ask before deciding", items=questions, empty="No questions came up."))

    steps = [
        MemoItem(text="Take your time. A good offer will still be there after you've thought it over."),
        MemoItem(text="Before paying anything, call the firm back on a number you look up yourself, not one they gave you."),
        MemoItem(text="Look the firm up on your financial regulator's website before going further."),
        MemoItem(text="Talk it over with someone you trust: family, a friend, or your bank."),
    ]
    if o and o.payment and o.payment.display in {"Bank transfer", "Wire transfer", "Crypto", "Gift cards"}:
        steps.insert(1, MemoItem(text=f"Money sent by {o.payment.display.lower()} is hard to get back. Ask for written terms first.", tone="warn"))
    out.append(MemoSection(id="steps", title="Steps that can help", items=steps))
    return out


def template_summary(r: CallRecord) -> str:
    o = r.offer
    who = " from ".join(x for x in [o.caller_name.display if o and o.caller_name else None, o.firm.display if o and o.firm else None] if x)
    what = o.instrument.display.split(" · ")[-1] if o and o.instrument else "an investment"
    parts = [f"{who or 'The caller'} called about {what}."]
    false = [c for c in r.claims.values() if c.status == "false"]
    parts.append(f"{len(false)} of the caller's claims didn't match the data." if false else "Nothing the caller said contradicted the data Tenor checked.")
    strong = sorted({BY_ID[f.tactic].label.lower() for f in r.flags if f.severity == "strong"})
    if strong:
        parts.append("Tenor noticed pressure: " + ", ".join(strong) + ".")
    if r.risk is not None:
        parts.append(f"Overall risk: {r.risk.level}.")
    return " ".join(parts)


def facts_text(r: CallRecord, secs: list[MemoSection]) -> str:
    """Everything the summary may quote (for the number guard)."""
    lines = [template_summary(r)]
    for s in secs:
        for i in s.items:
            lines.append(f"{i.text} {i.detail}")
    if r.risk is not None:
        lines.append(f"Risk {r.risk.score}")
    return "\n".join(lines)


def build_memo(r: CallRecord, summary: str, wording: str, secs: list[MemoSection] | None = None) -> Memo:
    secs = secs if secs is not None else sections(r)
    ended = r.ended_at or utc_now()
    transcript = [u.model_copy(update={"speaker": r.role(u)}) for u in r.utterances.values()]
    return Memo(
        call_id=r.call_id, created_at=utc_now(), started_at=r.started_at,
        duration_s=round((ended - r.started_at).total_seconds(), 1), source=r.source,  # type: ignore[arg-type]
        replay_id=r.replay_id, risk_score=r.risk.score if r.risk else None, risk_level=r.risk.level if r.risk else None,
        headline=HEADLINE[r.risk.level] if r.risk else "Here's what Tenor heard on this call.",
        summary=summary, summary_wording=wording, sections=secs, transcript=transcript, note=NOTE,  # type: ignore[arg-type]
    )  # fmt: skip
