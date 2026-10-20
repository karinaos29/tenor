"""Speaker labeler: turns diarized "speaker 0/1" segments into caller/user utterances.

Who is "You" (architecture doc: loudness heuristic + first-turn rule):
1. First-turn rule: the first voice heard is provisionally the user (they answer the phone).
2. Loudness: the user sits next to the laptop mic; the caller comes out of a phone
   speaker. Once two speakers each have >= MIN_SPEECH_S of speech and differ by
   >= SWITCH_DB, every diarized speaker is classified on its own against the midpoint
   (with a margin, so labels don't flap). Diarization sometimes splits one voice into
   two speaker numbers; both then still land on the right side.
3. Manual swap: the user's "Swap speakers" button inverts the labels and locks them.

Consumes: AudioLevel, TranscriptSegment, TranscriptUtteranceEnd, TranscriptClosed, SpeakersSwap.
Publishes: UtterancePartial, UtteranceFinal, SpeakersUpdated, and UtterancesClosed when done.
"""

import math
import time
from dataclasses import dataclass
from typing import Literal

from audio.sources import FRAME_SECONDS
from pipeline.bus import EventBus
from pipeline.events import (
    AudioLevel,
    SpeakersSwap,
    SpeakersUpdated,
    TranscriptClosed,
    TranscriptSegment,
    TranscriptUtteranceEnd,
    Utterance,
    UtterancesClosed,
    UtteranceFinal,
    UtterancePartial,
    Word,
)
from pipeline.latency import record

MIN_SPEECH_S = 2.0  # speech needed before a speaker's loudness counts as evidence
SWITCH_DB = 3.0  # minimum loudness gap between the loudest and quietest speaker
MARGIN_DB = 1.0  # hysteresis around the midpoint
MIN_CLASSIFY_S = 0.5  # less speech than this: keep the speaker's current label
LEADING_WORD_GAP_S = 0.25  # a lone first word this close to the next speaker belongs to them


@dataclass
class _Loudness:
    seconds: float = 0.0
    energy: float = 0.0  # sum of mean frame power x word duration

    def db(self) -> float:
        if self.seconds <= 0 or self.energy <= 0:
            return -100.0
        return 10 * math.log10(self.energy / self.seconds)


def smooth_speakers(words: list[Word]) -> list[Word]:
    """Absorb single-word speaker flips; diarization jitters on short words.

    - A B A -> A A A
    - a lone leading word glued to the next speaker (A B B, no pause) -> B B B
    """
    out = list(words)
    if (
        len(out) >= 3
        and out[0].speaker != out[1].speaker == out[2].speaker
        and out[1].start - out[0].end < LEADING_WORD_GAP_S
    ):
        out[0] = out[0].model_copy(update={"speaker": out[1].speaker})
    for i in range(1, len(out) - 1):
        prev, cur, nxt = out[i - 1].speaker, out[i].speaker, out[i + 1].speaker
        if cur != prev and prev == nxt:
            out[i] = out[i].model_copy(update={"speaker": prev})
    return out


class SpeakerLabeler:
    def __init__(self, bus: EventBus, call_id: str = "", source: str = "") -> None:
        self.bus = bus
        self.call_id = call_id
        self.source = source
        # Subscribe now, not in run(), so no event published before run() starts is missed.
        self._sub = bus.subscribe(AudioLevel, TranscriptSegment, TranscriptUtteranceEnd, TranscriptClosed, SpeakersSwap)
        self.user: set[int] = set()  # diarized speakers labeled "You"
        self.locked = False
        self._locked_known: set[int] = set()  # speakers whose label the user set by hand
        self._decided = False
        self._power: list[float] = []  # linear power per 80 ms frame, indexed by frame number
        self._loudness: dict[int, _Loudness] = {}
        self._seen: list[int] = []  # speakers in order of first appearance
        self._words: list[Word] = []  # finalized words of the turn in progress
        self._interim: list[Word] = []
        self._utt_id: str | None = None
        self._count = 0

    async def run(self) -> None:
        async for event in self._sub:
            if isinstance(event, AudioLevel):
                self._add_level(event)
            elif isinstance(event, TranscriptSegment):
                started = time.perf_counter()
                self._on_segment(event)
                if event.is_final:
                    record("labeler", (time.perf_counter() - started) * 1000, call_id=self.call_id, source=self.source)
            elif isinstance(event, TranscriptUtteranceEnd):
                self._finalize()
            elif isinstance(event, SpeakersSwap):
                self._swap()
            elif isinstance(event, TranscriptClosed):
                self._finalize(include_interim=True)
                break
        self.bus.publish(UtterancesClosed())
        self._sub.close()

    # --- input handling ---------------------------------------------------------------

    def _add_level(self, event: AudioLevel) -> None:
        index = round(event.t / FRAME_SECONDS)
        if index >= len(self._power):
            self._power.extend([0.0] * (index + 1 - len(self._power)))
        self._power[index] = 10 ** (event.dbfs / 10)

    def _on_segment(self, seg: TranscriptSegment) -> None:
        for w in seg.words:
            if w.speaker not in self._seen:
                self._seen.append(w.speaker)
        if seg.words and not self._decided:
            self._set_user({seg.words[0].speaker}, "first_turn")

        if not seg.is_final:
            self._interim = seg.words
            self._emit_partial()
            return

        self._interim = []
        for w in smooth_speakers(seg.words):
            if self._words and w.speaker != self._words[-1].speaker:
                self._finalize()  # speaker changed: close the previous turn
            self._words.append(w)
        if seg.speech_final:
            self._finalize()
        else:
            self._emit_partial()

    # --- utterances -------------------------------------------------------------------

    def _current_id(self) -> str:
        if self._utt_id is None:
            self._count += 1
            self._utt_id = f"u{self._count}"
        return self._utt_id

    def _utterance(self, uid: str, words: list[Word], is_final: bool) -> Utterance:
        index = words[0].speaker
        return Utterance(
            id=uid,
            speaker="user" if index in self.user else "caller",
            speaker_index=index,
            text=" ".join(w.text for w in words),
            t_start=words[0].start,
            t_end=words[-1].end,
            is_final=is_final,
        )

    def _emit_partial(self) -> None:
        # Same smoothing as finals, so a mislabeled first word can't mislabel the whole partial.
        words = smooth_speakers(self._words + self._interim)
        if words:
            self.bus.publish(UtterancePartial(utterance=self._utterance(self._current_id(), words, False)))

    def _finalize(self, include_interim: bool = False) -> None:
        words = self._words + (self._interim if include_interim else [])
        self._words = []
        if include_interim:
            self._interim = []
        if not words:
            return
        uid = self._current_id()
        self._utt_id = None
        self._add_loudness(words)
        self._maybe_relabel()
        self.bus.publish(UtteranceFinal(utterance=self._utterance(uid, words, True)))

    # --- who is "You" -----------------------------------------------------------------

    def _add_loudness(self, words: list[Word]) -> None:
        for w in words:
            first = int(w.start / FRAME_SECONDS)
            last = max(first, math.ceil(w.end / FRAME_SECONDS) - 1)
            frames = self._power[first : last + 1]
            if not frames:
                continue
            stats = self._loudness.setdefault(w.speaker, _Loudness())
            duration = max(w.end - w.start, FRAME_SECONDS)
            stats.seconds += duration
            stats.energy += (sum(frames) / len(frames)) * duration

    def _maybe_relabel(self) -> None:
        measured = {s: st.db() for s, st in self._loudness.items() if st.seconds >= MIN_SPEECH_S}
        if len(measured) < 2:
            return
        loud, quiet = max(measured.values()), min(measured.values())
        if loud - quiet < SWITCH_DB:
            return  # can't tell the voices apart by loudness
        new_user = set(self.user)
        if self.locked:
            # Labels the user set stay. Speakers who appeared later are classified
            # against the two hand-labeled groups.
            mine = [measured[s] for s in self._locked_known & self.user if s in measured]
            theirs = [measured[s] for s in self._locked_known - self.user if s in measured]
            if not mine or not theirs:
                return
            mine_db, theirs_db = sum(mine) / len(mine), sum(theirs) / len(theirs)
            mid = (mine_db + theirs_db) / 2
            user_is_louder = mine_db > theirs_db  # the user may have picked the quieter voice
            candidates = set(self._loudness) - self._locked_known
        else:
            mid = (loud + quiet) / 2
            user_is_louder = True  # the person at the mic is louder than the phone speaker
            candidates = set(self._loudness)
        for s in candidates:
            stats = self._loudness[s]
            if stats.seconds < MIN_CLASSIFY_S:
                continue
            if stats.db() > mid + MARGIN_DB:
                (new_user.add if user_is_louder else new_user.discard)(s)
            elif stats.db() < mid - MARGIN_DB:
                (new_user.discard if user_is_louder else new_user.add)(s)
        if new_user != self.user:
            self._set_user(new_user, "manual" if self.locked else "loudness")

    def _swap(self) -> None:
        # Invert every label heard so far and lock: the user knows best.
        self.locked = True
        self._locked_known = set(self._seen)
        self._set_user(set(self._seen) - self.user, "manual")

    def _set_user(self, user: set[int], reason: Literal["first_turn", "loudness", "manual"]) -> None:
        self.user = user
        self._decided = True
        self.bus.publish(SpeakersUpdated(user_indices=sorted(user), reason=reason, locked=self.locked))
