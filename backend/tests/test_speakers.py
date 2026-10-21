import asyncio

import pytest

from audio.sources import FRAME_SECONDS
from pipeline.bus import EventBus
from pipeline.events import (
    AudioLevel,
    SpeakersSwap,
    SpeakersUpdated,
    TranscriptClosed,
    TranscriptUtteranceEnd,
    UtteranceFinal,
    UtterancePartial,
)
from pipeline.speakers import SpeakerLabeler
from pipeline.transcriber import parse_deepgram_message
from tests.fakes import results


class Harness:
    """Drives a SpeakerLabeler through a real EventBus with a running timeline."""

    def __init__(self) -> None:
        self.bus = EventBus()
        self.out = self.bus.subscribe(UtterancePartial, UtteranceFinal, SpeakersUpdated)
        self.labeler = SpeakerLabeler(self.bus)
        self.t = 0.0

    def levels(self, t0: float, t1: float, dbfs: float, tone: float | None = None) -> None:
        """Frames at `dbfs`; with `tone`, also band powers (bass this many dB vs. the voice band)."""
        bands = {} if tone is None else {"voice_db": dbfs, "bass_db": dbfs + tone}
        i = round(t0 / FRAME_SECONDS)
        while i * FRAME_SECONDS < t1 - 1e-9:
            self.bus.publish(AudioLevel(t=i * FRAME_SECONDS, dbfs=dbfs, **bands))
            i += 1

    def segment(self, words, is_final=True, speech_final=False) -> None:
        for e in parse_deepgram_message(results(words, is_final, speech_final), 0.0):
            self.bus.publish(e)

    def speak(self, speaker: int, dbfs: float, seconds: float = 2.4, speech_final: bool = True, tone: float | None = None) -> None:
        """One turn: `seconds` of speech at `dbfs` by `speaker`, then a short quiet pause."""
        n = round(seconds / 0.3)
        t0 = self.t
        words = [(f"w{i}", t0 + 0.3 * i, t0 + 0.3 * (i + 1), speaker) for i in range(n)]
        self.levels(t0, t0 + 0.3 * n, dbfs, tone)
        self.levels(t0 + 0.3 * n, t0 + 0.3 * n + 0.4, -60.0, None if tone is None else -10.0)
        self.segment(words, True, speech_final)
        self.t = t0 + 0.3 * n + 0.4

    def swap(self) -> None:
        self.bus.publish(SpeakersSwap())


def run(scenario, expect_close: bool = True) -> list:
    async def main():
        h = Harness()
        task = asyncio.create_task(h.labeler.run())
        scenario(h)
        if expect_close:
            h.bus.publish(TranscriptClosed())
        await asyncio.wait_for(task, 2)
        h.bus.close()
        return [e async for e in h.out]

    return asyncio.run(main())


def updates(events) -> list[SpeakersUpdated]:
    return [e for e in events if isinstance(e, SpeakersUpdated)]


def finals(events) -> list:
    return [e.utterance for e in events if isinstance(e, UtteranceFinal)]


def partials(events) -> list:
    return [e.utterance for e in events if isinstance(e, UtterancePartial)]


# --- who is the user ------------------------------------------------------------------


def test_first_turn_rule():
    def scenario(h):
        h.speak(3, -20, seconds=0.6)

    ups = updates(run(scenario))
    assert [(u.user_indices, u.reason, u.locked) for u in ups] == [([3], "first_turn", False)]


def test_first_utterance_is_labeled_user_and_others_caller():
    def scenario(h):
        h.speak(0, -20, 0.6)
        h.speak(1, -20, 0.6)

    f = finals(run(scenario))
    assert [(u.speaker, u.speaker_index) for u in f] == [("user", 0), ("caller", 1)]


def test_loudness_keeps_loud_first_speaker_as_user():
    def scenario(h):
        h.speak(0, -20)
        h.speak(1, -30)
        h.speak(0, -20)
        h.speak(1, -30)

    events = run(scenario)
    ups = updates(events)
    assert ups[-1].user_indices == [0]
    assert len(ups) == 1  # first_turn only; loudness agrees, so nothing changes
    assert [u.speaker for u in finals(events)] == ["user", "caller", "user", "caller"]


def test_loudness_flips_when_quiet_speaker_went_first():
    def scenario(h):
        h.speak(0, -30)
        h.speak(1, -20)

    events = run(scenario)
    ups = updates(events)
    assert [(u.user_indices, u.reason) for u in ups] == [([0], "first_turn"), ([1], "loudness")]
    assert not ups[-1].locked
    assert [u.speaker for u in finals(events)] == ["user", "user"]  # the 2nd turn is already labeled with the flip


def test_diarization_split_voice_lands_on_user_side():
    def scenario(h):
        h.speak(0, -20)
        h.speak(1, -30)
        h.speak(2, -20)

    ups = updates(run(scenario))
    assert ups[-1].user_indices == [0, 2]
    assert ups[-1].reason == "loudness"


def test_no_flapping_inside_margin():
    def scenario(h):
        h.speak(0, -20)
        h.speak(1, -30)
        for _ in range(4):
            h.speak(2, -25.3)  # right at the midpoint, inside the +-1 dB margin
            h.speak(0, -20)
            h.speak(1, -30)

    ups = updates(run(scenario))
    assert len(ups) == 1
    assert ups[0].user_indices == [0]


def test_no_relabel_when_voices_differ_by_less_than_switch_gap():
    def scenario(h):
        h.speak(0, -30)
        h.speak(1, -28)  # only 2 dB apart

    assert len(updates(run(scenario))) == 1


# --- manual swap ----------------------------------------------------------------------


def test_manual_swap_inverts_seen_speakers_and_locks():
    def scenario(h):
        h.speak(0, -20)
        h.speak(1, -30)
        h.swap()
        # Loudness still says speaker 0 is the user; the lock must win.
        h.speak(0, -20)
        h.speak(1, -30)
        h.speak(0, -20)

    events = run(scenario)
    ups = updates(events)
    assert [(u.user_indices, u.reason, u.locked) for u in ups] == [
        ([0], "first_turn", False),
        ([1], "manual", True),
    ]
    assert [u.speaker for u in finals(events)][-3:] == ["caller", "user", "caller"]


def test_new_speaker_after_lock_classified_against_hand_labels_user_louder():
    # The user swapped before loudness could speak, and ends up the louder side.
    def scenario(h):
        h.segment([("hi", 0.0, 0.2, 0)], True, True)
        h.segment([("hello", 0.3, 0.5, 1)], True, True)
        h.swap()  # user = {1}
        h.t = 1.0
        h.speak(1, -20)
        h.speak(0, -30)
        h.speak(2, -20)  # new voice as loud as the user's -> user
        h.speak(3, -30)  # new voice as quiet as the caller's -> caller

    ups = updates(run(scenario))
    assert ups[-1].user_indices == [1, 2]
    assert ups[-1].locked and ups[-1].reason == "manual"


def test_new_speaker_after_lock_classified_against_hand_labels_user_quieter():
    def scenario(h):
        h.speak(0, -20)  # first turn -> user (loud)
        h.speak(1, -30)
        h.swap()  # user says: the quiet voice is me -> user = {1}
        h.speak(2, -30)  # new voice as quiet as the user's -> should join the user

    ups = updates(run(scenario))
    assert ups[-1].user_indices == [1, 2]


# --- merged voices: both people on one diarized speaker -------------------------------


def hello(h) -> None:
    """The user answers with one loud word, like the real replays ("Hello?" is 0.4 s)."""
    h.levels(0.0, 0.4, -20)
    h.levels(0.4, 1.0, -60)
    h.segment([("Hello?", 0.0, 0.4, 0)], True, True)
    h.t = 1.0


def shown(events) -> list[str]:
    """Roles as the UI shows them at the end: by speaker_index in the last user_indices."""
    user = updates(events)[-1].user_indices
    return ["user" if u.speaker_index in user else "caller" for u in finals(events)]


def test_merged_voices_split_by_loudness_from_the_callers_first_line():
    # Diarization puts both people on speaker 0; the caller's phone is 8 dB quieter.
    def scenario(h):
        hello(h)
        h.speak(0, -28, 4.8)  # the caller introduces themself
        h.speak(0, -20)
        h.speak(0, -28)
        h.speak(0, -20)

    events = run(scenario)
    f = finals(events)
    # Labeled right when sent, so the extractor and the offer see the caller's words.
    assert [(u.speaker, u.speaker_index) for u in f] == [
        ("user", 0),
        ("caller", 100),
        ("user", 0),
        ("caller", 100),
        ("user", 0),
    ]
    assert [(u.user_indices, u.reason) for u in updates(events)] == [([0], "first_turn")]


def test_merged_voices_caller_first_relabels_their_opening_line():
    def scenario(h):
        h.speak(0, -28, 4.8)  # the caller speaks first: provisionally "You"
        h.speak(0, -20)
        h.speak(0, -28)

    events = run(scenario)
    assert [(u.user_indices, u.reason) for u in updates(events)] == [([0], "first_turn"), ([100], "loudness")]
    assert [(u.speaker, u.speaker_index) for u in finals(events)] == [("user", 0), ("user", 100), ("caller", 0)]
    assert shown(events) == ["caller", "user", "caller"]  # the opening line keeps index 0 and flips


def test_after_a_split_a_turn_change_inside_one_segment_starts_a_new_line():
    def scenario(h):
        hello(h)
        h.speak(0, -28, 4.8)
        # One final segment: the caller, a pause, then the user. Deepgram marks no change.
        t = h.t
        h.levels(t, t + 1.2, -28)
        h.levels(t + 1.2, t + 1.6, -60)
        h.levels(t + 1.6, t + 2.8, -20)
        words = [(f"c{i}", t + 0.3 * i, t + 0.3 * (i + 1), 0) for i in range(4)]
        words += [(f"u{i}", t + 1.6 + 0.3 * i, t + 1.6 + 0.3 * (i + 1), 0) for i in range(4)]
        h.segment(words, True, True)

    f = finals(run(scenario))
    assert [(u.speaker, u.speaker_index, u.text) for u in f[2:]] == [
        ("caller", 100, "c0 c1 c2 c3"),
        ("user", 0, "u0 u1 u2 u3"),
    ]
    assert f[2].id != f[3].id


def test_partials_after_a_split_carry_the_nearer_voice():
    def scenario(h):
        hello(h)
        h.speak(0, -28, 4.8)
        t = h.t
        h.levels(t, t + 0.6, -28)
        h.segment([("so", t, t + 0.3, 0), ("then", t + 0.3, t + 0.6, 0)], False, False)

    p = partials(run(scenario))
    assert (p[-1].speaker_index, p[-1].speaker) == (100, "caller")


def test_one_voice_with_uneven_loudness_is_not_split():
    def scenario(h):
        for dbfs in (-20, -25, -20, -25, -21, -24):  # 5 dB apart: less than SPLIT_DB
            h.speak(0, dbfs)

    events = run(scenario)
    assert {u.speaker_index for u in finals(events)} == {0}
    assert len(updates(events)) == 1


def test_no_split_when_both_groups_land_on_the_same_side():
    # Diarization works, and the caller's phone gets quieter for a while: still one caller.
    def scenario(h):
        h.speak(0, -20)
        h.speak(1, -28)
        h.speak(0, -20)
        h.speak(1, -35)
        h.speak(1, -35)

    events = run(scenario)
    assert [(u.speaker, u.speaker_index) for u in finals(events)] == [
        ("user", 0),
        ("caller", 1),
        ("user", 0),
        ("caller", 1),
        ("caller", 1),
    ]
    assert len(updates(events)) == 1


def test_swap_after_a_split_inverts_both_voices_and_locks():
    def scenario(h):
        hello(h)
        h.speak(0, -28, 4.8)  # split: 0 = user, 100 = caller
        h.swap()
        h.speak(0, -20)  # still routed by loudness; the labels are the user's
        h.speak(0, -28)

    events = run(scenario)
    ups = updates(events)
    assert (ups[-1].user_indices, ups[-1].reason, ups[-1].locked) == ([100], "manual", True)
    assert [(u.speaker, u.speaker_index) for u in finals(events)[-2:]] == [("caller", 0), ("user", 100)]


def test_no_new_split_after_a_manual_swap():
    def scenario(h):
        hello(h)
        h.swap()  # the user said who is who
        h.speak(0, -28, 4.8)
        h.speak(0, -20)

    events = run(scenario)
    assert {u.speaker_index for u in finals(events)} == {0}
    assert [(u.user_indices, u.locked) for u in updates(events)] == [([0], False), ([], True)]


# --- smoothing and utterance boundaries -----------------------------------------------


def test_a_b_a_inside_final_segment_is_one_utterance():
    def scenario(h):
        h.segment([("a", 0.0, 0.2, 0), ("b", 0.3, 0.5, 1), ("c", 0.6, 0.8, 0)], True, True)

    f = finals(run(scenario))
    assert len(f) == 1
    assert f[0].text == "a b c" and f[0].speaker_index == 0


def test_lone_leading_word_glued_to_next_speaker():
    def scenario(h):
        h.segment([("a", 0.0, 0.2, 0), ("b", 0.3, 0.5, 1), ("c", 0.6, 0.8, 1)], True, True)

    f = finals(run(scenario))
    assert len(f) == 1 and f[0].speaker_index == 1 and f[0].text == "a b c"


def test_lone_leading_word_after_a_pause_stays_separate():
    def scenario(h):
        h.segment([("a", 0.0, 0.2, 0), ("b", 0.8, 1.0, 1), ("c", 1.1, 1.3, 1)], True, True)

    f = finals(run(scenario))
    assert [(u.speaker_index, u.text) for u in f] == [(0, "a"), (1, "b c")]


def test_speaker_change_in_final_segment_splits_utterance():
    def scenario(h):
        words = [(f"a{i}", 0.3 * i, 0.3 * i + 0.2, 0) for i in range(3)]
        words += [(f"b{i}", 1.2 + 0.3 * i, 1.2 + 0.3 * i + 0.2, 1) for i in range(3)]
        h.segment(words, True, True)

    f = finals(run(scenario))
    assert [(u.speaker_index, u.text) for u in f] == [(0, "a0 a1 a2"), (1, "b0 b1 b2")]
    assert f[0].id != f[1].id
    assert f[0].t_end <= f[1].t_start


def test_speech_final_finalizes_but_plain_final_does_not():
    def scenario(h):
        h.segment([("one", 0.0, 0.3, 0)], True, False)
        h.segment([("two", 0.4, 0.7, 0)], True, True)

    events = run(scenario)
    f = finals(events)
    assert [u.text for u in f] == ["one two"]
    # the plain final produced a partial, not a final
    assert partials(events)[0].text == "one"


def test_utterance_end_finalizes():
    def scenario(h):
        h.segment([("one", 0.0, 0.3, 0)], True, False)
        h.bus.publish(TranscriptUtteranceEnd(last_word_end=0.3))
        h.segment([("two", 2.0, 2.3, 0)], True, False)

    f = finals(run(scenario))
    assert [u.text for u in f] == ["one", "two"]  # "two" is flushed by TranscriptClosed
    assert f[0].id != f[1].id


def test_utterance_end_with_nothing_pending_publishes_nothing():
    def scenario(h):
        h.bus.publish(TranscriptUtteranceEnd(last_word_end=1.0))

    assert run(scenario) == []


def test_partials_combine_final_and_interim_words_with_stable_id():
    def scenario(h):
        h.segment([("a", 0.0, 0.2, 0), ("b", 0.3, 0.5, 0)], True, False)
        h.segment([("c", 0.6, 0.8, 0)], False, False)
        h.segment([("c", 0.6, 0.8, 0), ("d", 0.9, 1.1, 0)], False, False)
        h.segment([("c", 0.6, 0.8, 0), ("d", 0.9, 1.1, 0)], True, True)

    events = run(scenario)
    p = partials(events)
    assert [u.text for u in p] == ["a b", "a b c", "a b c d"]
    assert not any(u.is_final for u in p)
    [final] = finals(events)
    assert final.text == "a b c d" and final.is_final
    assert {u.id for u in p} == {final.id}
    assert final.t_start == 0.0 and final.t_end == pytest.approx(1.1)


def test_next_turn_gets_a_new_id():
    def scenario(h):
        h.segment([("a", 0.0, 0.2, 0)], True, True)
        h.segment([("b", 1.0, 1.2, 0)], False, False)
        h.segment([("b", 1.0, 1.2, 0)], True, True)

    events = run(scenario)
    f = finals(events)
    assert len(f) == 2 and f[0].id != f[1].id
    assert partials(events)[-1].id == f[1].id


def test_closed_finalizes_pending_interim_words_and_ends_run():
    def scenario(h):
        h.segment([("x", 0.0, 0.2, 0), ("y", 0.3, 0.5, 0)], False, False)

    events = run(scenario)  # run() awaits the labeler task: it must end
    f = finals(events)
    assert [u.text for u in f] == ["x y"]
    assert partials(events)[-1].id == f[0].id


def test_closed_with_nothing_pending_ends_run_quietly():
    assert run(lambda h: None) == []


def test_empty_speech_final_does_not_emit():
    def scenario(h):
        h.segment([], True, True)

    assert run(scenario) == []


def test_flush_we_requested_does_not_end_the_turn():
    """A Finalize-forced result (from_finalize) finalizes words but keeps the turn open,
    so a sentence with a pause isn't split into separate lines (seen on the scam replay)."""
    import asyncio

    from pipeline.bus import EventBus
    from pipeline.events import TranscriptClosed, TranscriptSegment, UtteranceFinal, Word
    from pipeline.speakers import SpeakerLabeler

    def seg(words, t, **kw):
        ws = [Word(text=w, start=t + i * 0.3, end=t + i * 0.3 + 0.25, speaker=1, confidence=0.9) for i, w in enumerate(words)]
        return TranscriptSegment(words=ws, is_final=True, start=t, end=ws[-1].end, **kw)

    async def main():
        bus = EventBus()
        out = bus.subscribe(UtteranceFinal)
        labeler = SpeakerLabeler(bus)
        task = asyncio.create_task(labeler.run())
        bus.publish(seg(["Most", "people", "haven't,"], 0.0, speech_final=True, from_finalize=True))
        bus.publish(seg(["yet."], 1.5, speech_final=True))
        bus.publish(TranscriptClosed())
        await task
        out.close()
        return [e.utterance.text async for e in out]

    assert asyncio.run(main()) == ["Most people haven't, yet."]


# --- tone: a phone speaker has no bass ----------------------------------------------------
# A voice in the room: bass about level with the telephone band. Through a phone: ~25 dB less.
ROOM, PHONE = 2.0, -25.0


def test_tone_beats_loudness_when_the_phone_is_louder():
    """The live failure: the phone was louder at the mic than the user."""

    def scenario(h):
        h.speak(0, -16, tone=PHONE)  # the caller speaks first, and loudly
        h.speak(1, -22, tone=ROOM)
        h.speak(0, -16, tone=PHONE)
        h.speak(1, -22, tone=ROOM)

    events = run(scenario)
    assert updates(events)[-1].user_indices == [1]
    assert updates(events)[-1].reason == "tone"
    assert [u.speaker for u in finals(events)][1:] == ["user", "caller", "user"]


def test_tone_splits_one_diarized_speaker_inside_a_single_turn():
    """Deepgram heard one speaker; each pause-delimited stretch is measured on its own."""

    def scenario(h):
        words, t = [], 0.0
        for k, (tone, dbfs, n) in enumerate([(PHONE, -16, 8), (ROOM, -22, 3), (PHONE, -16, 8), (ROOM, -22, 3)]):
            words += [(f"s{k}w{i}", t + 0.3 * i, t + 0.3 * (i + 1), 0) for i in range(n)]
            h.levels(t, t + 0.3 * n, dbfs, tone)
            h.levels(t + 0.3 * n, t + 0.3 * n + 0.5, -60.0, -10.0)
            t += 0.3 * n + 0.5
        h.segment(words, True, True)
        h.t = t
        h.speak(0, -22, seconds=1.5, tone=ROOM)  # a later turn: routed by tone to the user's voice
        h.speak(0, -16, seconds=2.4, tone=PHONE)

    events = run(scenario)
    ups = updates(events)
    assert ups[-1].reason == "tone" and ups[-1].user_indices == [100]
    assert [(u.speaker, u.speaker_index) for u in finals(events)[-2:]] == [("user", 100), ("caller", 0)]


def test_one_voice_with_varying_tone_is_not_split():
    def scenario(h):
        for tone in (-22.0, -30.0, -24.0, -31.0, -23.0):  # one phone voice, noisy bass
            h.speak(0, -20, tone=tone)

    events = run(scenario)
    assert {u.speaker_index for u in finals(events)} == {0}


def test_without_band_data_loudness_still_decides():
    def scenario(h):
        h.speak(0, -30)
        h.speak(1, -20)

    assert [(u.user_indices, u.reason) for u in updates(run(scenario))][-1] == ([1], "loudness")
