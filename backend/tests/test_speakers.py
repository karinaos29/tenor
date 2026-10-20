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

    def levels(self, t0: float, t1: float, dbfs: float) -> None:
        i = round(t0 / FRAME_SECONDS)
        while i * FRAME_SECONDS < t1 - 1e-9:
            self.bus.publish(AudioLevel(t=i * FRAME_SECONDS, dbfs=dbfs))
            i += 1

    def segment(self, words, is_final=True, speech_final=False) -> None:
        for e in parse_deepgram_message(results(words, is_final, speech_final), 0.0):
            self.bus.publish(e)

    def speak(self, speaker: int, dbfs: float, seconds: float = 2.4, speech_final: bool = True) -> None:
        """One turn: `seconds` of speech at `dbfs` by `speaker`, then a short quiet pause."""
        n = round(seconds / 0.3)
        t0 = self.t
        words = [(f"w{i}", t0 + 0.3 * i, t0 + 0.3 * (i + 1), speaker) for i in range(n)]
        self.levels(t0, t0 + 0.3 * n, dbfs)
        self.levels(t0 + 0.3 * n, t0 + 0.3 * n + 0.4, -60.0)
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
