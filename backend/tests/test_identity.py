"""IdentityWatcher: a pitching caller who doesn't say, or won't say, which firm they're from."""

import asyncio

from detector.taxonomy import BY_ID
from pipeline.bus import EventBus
from pipeline.events import (
    IdentityClosed,
    IdentityGap,
    IdentityResolved,
    Offer,
    OfferClosed,
    OfferUpdated,
    TacticFlag,
    TacticFlagged,
    TacticsClosed,
    Utterance,
    UtteranceFinal,
)
from pipeline.identity import FIRM_QUESTION, IdentityWatcher
from tests.m3_helpers import latency_entries, term

_n = 0


def say(text, t, speaker="caller"):
    global _n
    _n += 1
    return UtteranceFinal(utterance=Utterance(id=f"u{_n}", speaker=speaker, speaker_index=1 if speaker == "caller" else 0, text=text, t_start=t - 3, t_end=t, is_final=True))


def firm(name="Northgate Wealth"):
    return OfferUpdated(offer=Offer(firm=term(name)))


def pitch():
    return TacticFlagged(flag=TacticFlag(
        id="t1", tactic="urgency", label=BY_ID["urgency"].label, quote="quick offer", severity="mild",
        utterance_id="u1", score=0.7, source="classifier",
    ))  # fmt: skip


def run(events):
    async def main():
        bus = EventBus()
        watcher = IdentityWatcher(bus, call_id="c", source="test")
        spy = bus.subscribe(IdentityGap, IdentityResolved, IdentityClosed)
        task = asyncio.create_task(watcher.run())
        for e in events:
            bus.publish(e)
            await asyncio.sleep(0)
        bus.publish(OfferClosed())
        bus.publish(TacticsClosed())
        await asyncio.wait_for(task, 5)
        spy.close()
        return [e async for e in spy]

    return asyncio.run(main())


def gaps(out):
    return [(e.kind, e.question) for e in out if isinstance(e, IdentityGap)]


# --- missing ----------------------------------------------------------------------------


def test_pitch_without_a_firm_after_40_s_is_a_missing_gap():
    out = run([say("We have a quick Black Friday offer.", 22), pitch(), say("It's a really good idea.", 36), say("Are you interested?", 45)])
    assert gaps(out) == [("missing", None)]
    assert isinstance(out[-1], IdentityClosed)


def test_no_gap_before_40_s():
    assert gaps(run([pitch(), say("Quick offer.", 10), say("Interested?", 30)])) == []


def test_no_gap_without_a_pitch():
    assert gaps(run([say("Hello, how are you?", 20), say("Lovely weather.", 50), say("Bye now.", 60)])) == []


def test_firm_named_early_means_no_gap():
    assert gaps(run([say("This is Tom from Northgate Wealth.", 5), firm(), pitch(), say("Quick offer.", 50), say("Ok?", 60)])) == []


def test_firm_in_the_line_that_crosses_40_s_does_not_flicker():
    # The firm entity arrives just after its utterance; the line is judged once it has.
    out = run([pitch(), say("Quick offer.", 30), say("By the way, I'm with Northgate Wealth.", 45), firm(), say("So?", 50)])
    assert [e for e in out if isinstance(e, IdentityGap | IdentityResolved)] == []


def test_firm_named_later_resolves_a_missing_gap():
    out = run([pitch(), say("Quick offer.", 30), say("Interested?", 45), say("Well?", 50), firm(), say("Ok.", 60)])
    assert gaps(out) == [("missing", None)]
    assert [e.firm for e in out if isinstance(e, IdentityResolved)] == ["Northgate Wealth"]


def test_missing_gap_is_judged_at_the_end_of_the_call():
    assert gaps(run([pitch(), say("Quick offer.", 30), say("Last chance.", 45)])) == [("missing", None)]


# --- evaded -----------------------------------------------------------------------------


def test_question_with_two_unanswered_caller_turns_is_evaded():
    q = "Sorry, which company are you calling from?"
    out = run([say(q, 10, "user"), say("That's not important right now.", 14), say("What matters is the return.", 18), say("Hm.", 20, "user")])
    assert gaps(out) == [("evaded", q)]


def test_question_mislabeled_as_the_callers_still_counts():
    q = "Who do you work for?"
    out = run([say(q, 10, "caller"), say("A boutique firm.", 14), say("Very exclusive.", 18), say("Hm.", 20, "user")])
    assert gaps(out) == [("evaded", q)]


def test_answered_question_is_not_evaded():
    out = run([say("What's the name of your company?", 10, "user"), say("Northgate Wealth.", 14), firm(), say("Ok.", 16, "user"), say("So.", 20)])
    assert gaps(out) == []


def test_silence_for_20_s_after_the_question_is_evaded():
    out = run([say("Where are you calling from?", 10, "user"), say("Let me tell you about the offer.", 32), say("Hm.", 33, "user")])
    assert gaps(out) == [("evaded", "Where are you calling from?")]


def test_call_ending_after_one_dodge_is_evaded_but_not_after_none():
    q = "Which firm are you with?"
    assert gaps(run([say(q, 10, "user"), say("Let's talk about the shares.", 14)])) == [("evaded", q)]
    assert gaps(run([say(q, 10, "user")])) == []


def test_evaded_replaces_missing_and_is_never_resolved():
    out = run([
        pitch(), say("Quick offer.", 30), say("Interested?", 45),
        say("Who are you with?", 48, "user"), say("Doesn't matter.", 50), say("Buy now.", 52), say("Hm.", 53, "user"),
        firm(), say("Ok.", 60),
    ])  # fmt: skip
    assert [k for k, _ in gaps(out)] == ["missing", "evaded"]
    assert [e for e in out if isinstance(e, IdentityResolved)] == []


def test_question_after_the_firm_was_named_is_just_clarification():
    out = run([say("I'm with Northgate Wealth.", 5), firm(), say("Sorry, which company are you from?", 10, "user"), say("Shares.", 14), say("Now.", 18), say("Ok.", 20, "user")])
    assert gaps(out) == []


def test_firm_question_patterns():
    for text in [
        "Which company are you from?", "What firm is this?", "What's your company called?", "Who are you with?",
        "Who do you work for?", "Where are you calling from?", "And you're from which company?",
        "What is the name of the firm?", "Who are you calling on behalf of?",
    ]:  # fmt: skip
        assert FIRM_QUESTION.search(text), text
    for text in ["Is that the company that makes the coins?", "Which company makes it?", "Who are you?"]:
        assert not FIRM_QUESTION.search(text), text


def test_latency_is_logged():
    run([say("Hello.", 5), say("Hi.", 8, "user")])
    assert latency_entries("identity")
