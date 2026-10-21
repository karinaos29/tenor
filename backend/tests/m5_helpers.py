"""Shared helpers for the M5 (memo) tests: a scam-like and an honest-like call record."""

from datetime import UTC, datetime, timedelta

from memo.builder import CallRecord
from memo.store import MemoStore
from pipeline.events import (
    Claim, Offer, RiskReason, RiskUpdated, Suggestion, TacticFlag, Term, TermChange, Utterance,
)

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def utt(id, text, t, speaker="caller", idx=1) -> Utterance:
    return Utterance(id=id, speaker=speaker, speaker_index=idx, text=text, t_start=t, t_end=t + 2, is_final=True)


def term(display, t=None, source="call") -> Term:
    return Term(display=display, said=display, t=t, utterance_id="u1", source=source)


def flag(id, tactic, severity, quote, utt_id="u1") -> TacticFlag:
    return TacticFlag(id=id, tactic=tactic, label=tactic, quote=quote, severity=severity, utterance_id=utt_id, score=1.0, source="rule")


def say(id, text, priority) -> Suggestion:
    return Suggestion(id=id, kind="say_this", title=f"T{id}", text=text, priority=priority, status="ready", reason="r")


def scam_record(**over) -> CallRecord:
    old = term("5,000 shares", 3.0)
    new = term("10,000 shares", 65.0)
    offer = Offer(
        caller_name=term("Daniel", 5.0), firm=term("Harlow Capital", 8.0), instrument=term("Kestrel Motors · KSTL", 12.0),
        price=term("$0.42", 20.0), quantity=new, total=term("$4,200", source="computed"), payment=term("Wire transfer", 40.0),
        history=[TermChange(field="quantity", old=old, new=new)],
    )
    claims = {
        "ok": Claim(id="ok", text="a fine thing", metric="other", utterance_id="u2", status="verified", source="S"),
        "nf": Claim(id="nf", text="it was on the news", metric="event", utterance_id="u2", status="not_found", note="none"),
        "f": Claim(id="f", text="up forty percent", metric="price_change", claimed_value=40.0, period="this quarter", subject="KSTL",
                   utterance_id="u3", status="false", actual_value=-12.5, source="Test data", note="last 13 weeks"),
    }
    r = CallRecord(
        call_id="c1", started_at=T0, ended_at=T0 + timedelta(seconds=90), source="replay", replay_id="scam",
        utterances={
            "u1": utt("u1", "Hello", 1.0), "u2": utt("u2", "Great news", 70.0), "u3": utt("u3", "Up forty percent", 125.0),
            "u4": utt("u4", "Hi", 130.0, "user", 0),
        },
        offer=offer, claims=claims,
        flags=[flag("f1", "urgency", "mild", "today only", "u1"), flag("f2", "secrecy", "strong", "keep it quiet", "u2"),
               flag("f3", "urgency", "strong", "act now", "u3")],
        say_this={str(i): say(str(i), f"Question {i}?", i) for i in range(1, 9)},
        risk=RiskUpdated(score=82, level="critical", reasons=[RiskReason(label="Claim doesn't match data", points=40)]),
    )
    for k, v in over.items():
        setattr(r, k, v)
    return r


def honest_record() -> CallRecord:
    return CallRecord(
        call_id="c2", started_at=T0, ended_at=T0 + timedelta(seconds=30),
        utterances={"u1": utt("u1", "Hello", 1.0)},
        claims={"v": Claim(id="v", text="t", metric="price", claimed_value=10.0, utterance_id="u1", status="verified", actual_value=10.0, source="S", note="n")},
        risk=RiskUpdated(score=5, level="low", reasons=[]),
    )


def tmp_store(tmp_path) -> MemoStore:
    return MemoStore(tmp_path / "t.sqlite")
