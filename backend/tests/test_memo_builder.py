"""memo/builder.py: sections, summary and memo from a CallRecord."""

import re

from memo.builder import HEADLINE, CallRecord, build_memo, clock, facts_text, sections, template_summary
from memo.writer import FORBIDDEN
from pipeline.events import Offer, RiskUpdated
from tests.m5_helpers import honest_record, scam_record, term

IDS = ["glance", "who", "offer", "claims", "pressure", "questions", "steps"]


def by_id(secs):
    return {s.id: s for s in secs}


def test_order_and_ids():
    assert [s.id for s in sections(scam_record())] == IDS


def test_empty_record_has_empty_texts():
    secs = by_id(sections(CallRecord(call_id="x")))
    for sid in ["glance", "who", "offer", "claims", "pressure", "questions"]:
        assert secs[sid].items == [] and secs[sid].empty
    assert len(secs["steps"].items) == 4


def test_offer_terms_with_said_at_and_was():
    items = by_id(sections(scam_record()))["offer"].items
    texts = {i.text: i for i in items}
    q = texts["Quantity: 10,000 shares"]
    assert q.detail == "was 5,000 shares" and q.source == "said at 1:05" and q.tone == "warn" and q.t == 65.0
    assert texts["Price: $0.42"].source == "said at 0:20" and texts["Price: $0.42"].detail == ""
    assert texts["Total: $4,200"].source == "price × quantity"


def test_claims_sorted_false_first_with_labels_and_t():
    items = by_id(sections(scam_record()))["claims"].items
    assert [i.detail.split(".")[0] for i in items] == ["Doesn't match data", "No evidence found", "Matches data"]
    assert items[0].t == 125.0 and items[0].tone == "danger"
    assert "Data: -12.5%" in items[0].detail


def test_pressure_grouped_strong_first_with_count():
    items = by_id(sections(scam_record()))["pressure"].items
    assert len(items) == 2
    assert items[0].source == "Strong" and items[1].source == "Strong"  # both tactics have a strong flag
    urgency = next(i for i in items if "(2 times)" in i.text)
    assert urgency.detail == "“today only”" and urgency.t == 1.0
    assert all("(" not in i.text for i in items if i is not urgency)


def test_mild_only_tactic_sorts_after_strong():
    r = scam_record()
    r.flags = [r.flags[0], r.flags[1]]  # urgency mild only, secrecy strong
    items = by_id(sections(r))["pressure"].items
    assert [i.source for i in items] == ["Strong", "Mild"]


def test_questions_top_six_by_priority():
    items = by_id(sections(scam_record()))["questions"].items
    assert [i.text for i in items] == [f"“Question {n}?”" for n in (8, 7, 6, 5, 4, 3)]


def test_risky_payment_adds_step():
    steps = by_id(sections(scam_record()))["steps"].items
    assert len(steps) == 5 and "wire transfer" in steps[1].text.lower() and steps[1].tone == "warn"
    safe = scam_record(offer=Offer(payment=term("Card")))
    assert len(by_id(sections(safe))["steps"].items) == 4


def test_roles_recomputed_from_user_indices():
    r = scam_record(user_indices={1})
    memo = build_memo(r, "s", "template")
    roles = {u.id: u.speaker for u in memo.transcript}
    assert roles == {"u1": "user", "u2": "user", "u3": "user", "u4": "caller"}
    assert build_memo(scam_record(), "s", "template").transcript[0].speaker == "caller"  # no indices: as emitted


def test_template_summary_scam_and_honest():
    s = template_summary(scam_record())
    assert "Daniel from Harlow Capital called about KSTL." in s
    assert "1 of the caller's claims didn't match" in s and "rushing you" in s and "Overall risk: critical." in s
    h = template_summary(honest_record())
    assert "Nothing the caller said contradicted" in h and "pressure" not in h
    assert not FORBIDDEN.search(s) and not FORBIDDEN.search(h)


def test_headline_per_risk_level():
    for level, text in HEADLINE.items():
        r = scam_record(risk=RiskUpdated(score=1, level=level, reasons=[]))
        assert build_memo(r, "s", "template").headline == text
    assert build_memo(CallRecord(call_id="x"), "s", "template").headline.startswith("Here's what Tenor heard")


def test_facts_text_contains_the_numbers():
    r = scam_record()
    f = facts_text(r, sections(r))
    for n in ["82", "10,000", "0.42", "4,200", "40", "12.5"]:
        assert n in f


def test_duration_and_clock():
    assert build_memo(scam_record(), "s", "template").duration_s == 90.0
    assert clock(65) == "1:05" and clock(None) == ""
    assert re.fullmatch(r"\d+:\d\d", clock(3599))
