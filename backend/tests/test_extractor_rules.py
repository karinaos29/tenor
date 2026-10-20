"""Stage-1 rules: entities and claims, spoken-word and Deepgram smart_format styles."""

import pytest

from pipeline.extractor import event_sentences, extract_rules
from providers.catalog import default_catalog

CAT = default_catalog()


def ents(text, kind):
    return [e for e in extract_rules(text, CAT).entities if e.kind == kind]


def one(text, kind):
    found = ents(text, kind)
    assert len(found) == 1, (text, found)
    return found[0]


# --- price ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "The shares are $0.42 a share.",
        "The shares are 42 cents each.",
        "The shares are 42¢ each.",
        "Right now the shares are forty-two cents each.",
        "Right now the shares are forty two cents each.",
    ],
)
def test_price_per_share(text):
    e = one(text, "price")
    assert e.value == "$0.42 a share"
    assert e.number == pytest.approx(0.42)
    assert e.unit == "USD"


def test_price_said_text_is_original_words():
    e = one("Right now the shares are forty-two cents each.", "price")
    assert e.text == "forty-two cents"


def test_dollar_amount_without_share_context_is_not_a_price():
    assert ents("Exactly, twenty-one hundred dollars.", "price") == []
    assert ents("That is $2,100 in total.", "price") == []


def test_dollars_followed_by_shares_is_not_a_price():
    assert ents("I could sell you $500 shares.", "price") == []


# --- quantity ------------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["Start with 10,000 shares.", "Start with ten thousand shares.", "Start with 10000 shares."])
def test_quantity(text):
    e = one(text, "quantity")
    assert e.value == "10,000 shares" and e.number == 10_000 and e.unit == "shares"


# --- deadline ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "The price is locked until 3PM today.",
        "The price is locked until 3 p.m. today.",
        "The price is locked until three p.m. today.",
    ],
)
def test_deadline_time(text):
    assert one(text, "deadline").value == "Today, 3:00 PM"


def test_deadline_date():
    assert one("Remember, the deadline is April 15th.", "deadline").value == "April 15"
    assert one("The deadline is April fifteenth.", "deadline").value == "April 15"


def test_deadline_cue_must_precede():
    assert ents("You would pay this afternoon by phone.", "deadline") == []
    assert ents("I'll confirm the shares this afternoon, by phone.", "deadline") == []


# --- payment / fees / percent ------------------------------------------------------------------


def test_payment_methods():
    assert one("You'd just make a bank transfer to our account.", "payment").value == "Bank transfer"
    assert one("Pay with gift cards.", "payment").value == "Gift cards"


def test_platform_fee_is_an_offer_fee():
    e = one("Our platform fee is a quarter percent a year.", "fee")
    assert e.value == "0.25% a year" and e.number == pytest.approx(0.25)


def test_expense_ratio_is_a_fee_claim_not_an_offer_fee():
    text = "The fund's expense ratio is three hundredths of a percent a year."
    r = extract_rules(text, CAT)
    assert [e for e in r.entities if e.kind == "fee"] == []
    fees = [c for c in r.claims if c.metric == "fee"]
    assert len(fees) == 1
    assert fees[0].claimed_value == pytest.approx(0.03) and fees[0].unit == "%" and fees[0].period == "a year"


def test_percent_entity():
    e = one("It is up 40% this quarter.", "percent")
    assert e.number == 40


# --- names ---------------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["The ticker is K S T L.", "Call it K S T L.", "It trades as KSTL.", "Kestrel Motors is the company."])
def test_ticker_kstl_resolves(text):
    e = one(text, "ticker")
    assert e.value == "KSTL" and e.detail == "Kestrel Motors"


def test_spelled_ticker_matched_via_catalog():
    e = one("The ticker is K S T L.", "ticker")
    assert e.confidence == "matched" and e.detail == "Kestrel Motors"
    e = one("The ticker is V O O.", "ticker")
    assert e.value == "VOO" and e.confidence == "matched" and e.detail == "Vanguard S&P 500 ETF"


def test_spelled_ticker_without_cue():
    e = one("It is called V O O, a big fund.", "ticker")
    assert e.value == "VOO" and e.confidence == "matched"


def test_unknown_spelled_ticker_is_unsure():
    e = one("The ticker is Z Q X Y.", "ticker")
    assert e.value == "ZQXY" and e.confidence == "unsure" and e.detail is None


def test_company_alias_resolves_to_ticker():
    e = one("We have an opportunity on Kestrel Motors.", "ticker")
    assert (e.value, e.detail, e.confidence) == ("KSTL", "Kestrel Motors", "matched")


def test_firm_alias_resolves_to_canonical_name():
    e = one("I'm calling from Hartwell and Crane.", "firm")
    assert e.value == "Hartwell & Crane" and e.confidence == "matched"
    assert e.text == "Hartwell and Crane"


def test_unknown_firm_is_heard():
    e = one("I'm calling from Acme Capital.", "firm")
    assert e.value == "Acme Capital" and e.confidence == "heard"


@pytest.mark.parametrize(
    ("text", "name"),
    [("My name is Daniel Reeves, I work here.", "Daniel Reeves"), ("Hello, this is Maria Lopez from the bank.", "Maria Lopez")],
)
def test_person(text, name):
    assert one(text, "person").value == name


def test_im_calling_is_not_a_person():
    assert ents("I'm calling about your review.", "person") == []
    assert ents("I'm just calling to say hello.", "person") == []


def test_person_inside_firm_name_is_skipped():
    assert ents("I'm calling from Hartwell and Crane.", "person") == []


# --- claims --------------------------------------------------------------------------------


def claims(text):
    return extract_rules(text, CAT).claims


def test_price_change_up():
    (c,) = claims("The stock is up 40% this quarter.")
    assert (c.metric, c.claimed_value, c.unit, c.period) == ("price_change", 40.0, "%", "this quarter")


def test_price_change_spoken():
    (c,) = claims("The stock is up forty percent this quarter.")
    assert c.claimed_value == 40.0 and c.period == "this quarter"


def test_price_change_down_is_negative():
    (c,) = claims("It fell 12% last month.")
    assert c.metric == "price_change" and c.claimed_value == -12.0 and c.period == "last month"


def test_return_metric():
    (c,) = claims("The returns were up 8% this year.")
    assert c.metric == "return" and c.claimed_value == 8.0


def test_guarantee_double_by_christmas():
    cs = claims("Our analysts say it's guaranteed to double by Christmas.")
    assert len(cs) == 1
    c = cs[0]
    assert (c.metric, c.claimed_value, c.unit, c.period) == ("guarantee", 100.0, "%", "by Christmas")


def test_plain_guarantee_has_no_value():
    (c,) = claims("With this deal in place, it really is a sure thing.")
    assert c.metric == "guarantee" and c.claimed_value is None and c.unit is None


def test_negated_guarantee_is_not_a_claim():
    assert claims("Past returns don't guarantee future results.") == []
    assert claims("Nothing can guarantee a profit, and we do not guarantee it.") == []


def test_event_sentences():
    found = event_sentences("They just signed a deal with a major carmaker, and the stock is up. Nice weather.")
    assert found == ["They just signed a deal with a major carmaker, and the stock is up."]
    assert event_sentences("Nothing special here.") == []
