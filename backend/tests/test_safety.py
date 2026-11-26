"""SecretGuard: warns on a request for a private detail, and again when an answer starts."""

import asyncio

from memo.builder import CallRecord, sections, template_summary
from pipeline.bus import EventBus
from pipeline.events import (
    SecretRequested,
    SecretsClosed,
    SecretSharing,
    Utterance,
    UtteranceFinal,
    UtterancePartial,
    UtteranceProgress,
    UtterancesClosed,
)
from pipeline.safety import SecretGuard


def u(uid, text, t_end, speaker="caller"):
    return Utterance(id=uid, speaker=speaker, speaker_index=1 if speaker == "caller" else 0, text=text, t_start=t_end - 3, t_end=t_end, is_final=False)


def final(uid, text, t_end, speaker="caller"):
    return UtteranceFinal(utterance=u(uid, text, t_end, speaker).model_copy(update={"is_final": True}))


def partial(uid, text, t_end, speaker="user"):
    return UtterancePartial(utterance=u(uid, text, t_end, speaker))


def run(events, **kwargs):
    async def main():
        bus = EventBus()
        guard = SecretGuard(bus, call_id="c", source="test", **kwargs)
        spy = bus.subscribe(SecretRequested, SecretSharing, SecretsClosed)
        task = asyncio.create_task(guard.run())
        for e in events:
            bus.publish(e)
            await asyncio.sleep(0)
        bus.publish(UtterancesClosed())
        await asyncio.wait_for(task, 5)
        spy.close()
        return [e async for e in spy]

    return asyncio.run(main())


def kinds(out):
    return [type(e).__name__ for e in out]


def test_request_then_answer_read_out():
    out = run([
        final("u1", "This is the fraud team. Can you read me the code we just sent you?", 8),
        partial("u2", "Oh, yes. It says four", 10),
        partial("u2", "Oh, yes. It says four seven", 11),
        partial("u2", "Oh, yes. It says four seven two", 12),
        final("u2", "Oh, yes. It says four seven two nine one six.", 14, "user"),
    ])  # fmt: skip
    assert kinds(out) == ["SecretRequested", "SecretSharing", "SecretsClosed"]
    req, share = out[0], out[1]
    assert (req.kind, req.level, req.label) == ("one_time_code", "stop", "one-time code")
    assert share.utterance_id == "u2" and share.t == 11  # at the second digit
    # Nothing from the answer is kept.
    assert not any(w in e.model_dump_json() for e in out for w in ("seven", "nine"))


def test_two_sentence_request_seen_mid_turn():
    out = run([
        UtteranceProgress(utterance=u("u1", "We just sent you a six digit code by text.", 5)),
        UtteranceProgress(utterance=u("u1", "We just sent you a six digit code by text. Can you read it to me?", 8)),
        final("u1", "We just sent you a six digit code by text. Can you read it to me?", 8),
    ])  # fmt: skip
    assert kinds(out) == ["SecretRequested", "SecretsClosed"]  # once, and "six" isn't an answer


def test_answer_in_the_same_turn_counts_only_after_the_request():
    # Diarization merged both voices into one turn.
    text = "Can you read me the code we sent? Yes, it's 4 7 2 9."
    out = run([UtteranceProgress(utterance=u("u1", "Can you read me the code we sent?", 4)), partial("u1", text, 7, "caller")])
    assert kinds(out) == ["SecretRequested", "SecretSharing", "SecretsClosed"]


def test_warnings_and_refusals_stay_quiet():
    out = run([
        final("u1", "We will never ask you for your code or PIN. Never read it to anyone.", 5),
        final("u2", "I don't give out codes on the phone.", 8, "user"),
        partial("u3", "My number is four seven two nine", 10),
    ])  # fmt: skip
    assert kinds(out) == ["SecretsClosed"]


def test_check_requests_warn_but_dont_interrupt():
    out = run([final("u1", "To confirm it's you, what's your date of birth?", 5), partial("u2", "It's the fourth of the seventh, 1 9 6 8", 8)])
    assert kinds(out) == ["SecretRequested", "SecretsClosed"]
    assert out[0].level == "check"


def test_no_interruption_long_after_the_request():
    out = run([final("u1", "Please read me your PIN.", 5), partial("u2", "4 7 2 9", 60)])
    assert kinds(out) == ["SecretRequested", "SecretsClosed"]


def test_one_word_isnt_an_answer():
    out = run([final("u1", "Please read me your PIN.", 5), partial("u2", "One moment, I need my glasses.", 8)])
    assert kinds(out) == ["SecretRequested", "SecretsClosed"]


def test_asking_again_doesnt_warn_twice_and_a_new_kind_does():
    out = run([
        final("u1", "Can you read me the code we sent?", 5),
        final("u2", "Sorry?", 7, "user"),
        final("u3", "The code, can you read me the code?", 10),
        final("u4", "And what's your online banking password?", 14),
    ])  # fmt: skip
    assert [e.kind for e in out if isinstance(e, SecretRequested)] == ["one_time_code", "password"]


def test_quote_masks_digits():
    out = run([final("u1", "Can you confirm your PIN is 4 7 2 9?", 5)])
    assert "4" not in out[0].quote and "•" in out[0].quote


def test_memo_lists_requests_and_the_answer():
    req = SecretRequested(kind="one_time_code", level="stop", label="one-time code", quote="Read me the code.", utterance_id="u1", t=5)
    r = CallRecord(secrets=[req], sharing=[SecretSharing(kind="one_time_code", label="one-time code", utterance_id="u2", t=9)])
    secs = {s.id: s for s in sections(r)}
    assert [i.tone for i in secs["secrets"].items] == ["danger", "danger"]
    assert secs["steps"].items[0].text.startswith("If you read out a code")
    assert "asked for your one-time code" in template_summary(r)


def test_memo_has_no_requests_section_on_an_ordinary_call():
    assert "secrets" not in {s.id for s in sections(CallRecord())}


def test_suggestions_put_the_request_first_and_risk_critical():
    from pipeline.events import RiskUpdated, SuggestionsUpdated
    from pipeline.suggestions import SuggestionEngine

    async def main():
        bus = EventBus()
        engine = SuggestionEngine(bus, wait_for=("secrets",))
        spy = bus.subscribe(SuggestionsUpdated, RiskUpdated)
        task = asyncio.create_task(engine.run())
        bus.publish(SecretRequested(kind="pin", level="stop", label="PIN", quote="Read me your PIN.", utterance_id="u1", t=5))
        bus.publish(SecretSharing(kind="pin", label="PIN", utterance_id="u2", t=8))
        bus.publish(SecretsClosed())
        await asyncio.wait_for(task, 5)
        spy.close()
        return [e async for e in spy]

    out = asyncio.run(main())
    sug = [e for e in out if isinstance(e, SuggestionsUpdated)][-1]
    risk = [e for e in out if isinstance(e, RiskUpdated)][-1]
    assert sug.visible[0].id == "say-secret" and sug.visible[0].title == "Stop before you say more"
    assert risk.level == "critical" and risk.reasons[0].label == "The caller asked for your PIN"


def test_interim_words_dont_point_back_at_a_mention():
    # A misheard warning ("ever" for "never") in interim words must not become a request.
    out = run([
        final("u1", "We will never ask you for a code, your PIN or your password.", 5),
        partial("u2", "Will ever ask you for your PIN. To confirm it to me", 7, "caller"),
        partial("u3", "Read it to me", 9, "caller"),
    ])  # fmt: skip
    assert kinds(out) == ["SecretsClosed"]


def test_a_direct_request_is_seen_in_interim_words():
    out = run([partial("u1", "Then I also need your online banking password so we can move", 5, "caller")])
    assert kinds(out) == ["SecretRequested", "SecretsClosed"]


def test_a_late_final_of_the_request_doesnt_hide_the_answer():
    # Interim words show the request, her answer starts, then the request's final arrives.
    out = run([
        partial("u1", "Can you read me the code we sent", 5, "caller"),
        partial("u2", "It says four", 7),
        final("u1", "Can you read me the code we sent?", 5),
        partial("u2", "It says four seven", 8),
    ])  # fmt: skip
    assert kinds(out) == ["SecretRequested", "SecretSharing", "SecretsClosed"]
