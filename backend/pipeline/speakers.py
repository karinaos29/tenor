"""Speaker labeler: turns diarized "speaker 0/1" segments into caller/user utterances.

Who is "You" (architecture doc: loudness heuristic + first-turn rule):
1. First-turn rule: the first voice heard is provisionally the user (they answer the phone).
2. Loudness: the user sits next to the laptop mic; the caller comes out of a phone
   speaker. Once two speakers each have >= MIN_SPEECH_S of speech and differ by
   >= SWITCH_DB, every diarized speaker is classified on its own against the midpoint
   (with a margin, so labels don't flap). Diarization sometimes splits one voice into
   two speaker numbers; both then still land on the right side.
3. Merged voices: diarization can also put two similar voices on one speaker number.
   When one speaker's turns form a loud and a quiet group >= SPLIT_DB apart, the group
   without its first turn becomes a second voice, numbered VIRTUAL_BASE + n; the loud
   group is the user. From then on each stretch of that speaker's words between pauses
   goes to the nearer group, so a turn change Deepgram didn't mark still starts a new
   line. Lines already sent keep their number: `speaker_index` is a voice number, and
   the UI relabels by it as before.
4. Manual swap: the user's "Swap speakers" button inverts the labels and locks them.
   No new splits after that: the user has said who is who.

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
SPLIT_DB = 6.0  # one speaker's loud and quiet turns this far apart are two people
MIN_GROUP_S = 0.3  # a split needs about a word in the smaller group ("Hello?" is 0.4 s)
VIRTUAL_BASE = 100  # voice number for the second person found inside diarized speaker n
PAUSE_S = 0.3  # a silence where a turn may change (Deepgram's endpointing is 300 ms)
LEADING_WORD_GAP_S = 0.25  # a lone first word this close to the next speaker belongs to them


@dataclass
class _Loudness:
    seconds: float = 0.0
    energy: float = 0.0  # sum of mean frame power x word duration

    def db(self) -> float:
        if self.seconds <= 0 or self.energy <= 0:
            return -100.0
        return 10 * math.log10(self.energy / self.seconds)

    def add(self, other: "_Loudness") -> None:
        self.seconds += other.seconds
        self.energy += other.energy


def _pool(turns: list[_Loudness]) -> _Loudness:
    total = _Loudness()
    for t in turns:
        total.add(t)
    return total


def _two_people(quiet: _Loudness, loud: _Loudness, others: list[float]) -> bool:
    """Whether a quiet and a loud group of one speaker's turns are clearly two people.

    `others` are the levels of the call's other voices with enough speech."""
    if min(quiet.seconds, loud.seconds) < MIN_GROUP_S or max(quiet.seconds, loud.seconds) < MIN_SPEECH_S:
        return False
    if loud.db() - quiet.db() < SPLIT_DB:
        return False
    levels = [quiet.db(), loud.db(), *others]
    mid = (max(levels) + min(levels)) / 2
    return loud.db() > mid + MARGIN_DB and quiet.db() < mid - MARGIN_DB


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
        self.user: set[int] = set()  # voices labeled "You"
        self.locked = False
        self._locked_known: set[int] = set()  # voices whose label the user set by hand
        self._decided = False
        self._power: list[float] = []  # linear power per 80 ms frame, indexed by frame number
        self._loudness: dict[int, _Loudness] = {}  # per voice: a diarized speaker or a split-off voice
        self._turns: dict[int, list[_Loudness]] = {}  # each final turn's loudness, per unsplit speaker
        self._second_voice: dict[int, int] = {}  # diarized speaker -> the voice split off from it
        self._seen: list[int] = []  # voices in order of first appearance
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
        for w in smooth_speakers(self._route_stretches(seg.words)):
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

    def _utterance(self, uid: str, words: list[Word], is_final: bool, voice: int) -> Utterance:
        return Utterance(
            id=uid,
            speaker="user" if voice in self.user else "caller",
            speaker_index=voice,
            text=" ".join(w.text for w in words),
            t_start=words[0].start,
            t_end=words[-1].end,
            is_final=is_final,
        )

    def _emit_partial(self) -> None:
        # Same smoothing as finals, so a mislabeled first word can't mislabel the whole partial.
        words = smooth_speakers(self._words + self._interim)
        if words:
            speaker = words[0].speaker
            voice = self._route(speaker, self._measure(words)) if speaker in self._second_voice else speaker
            self.bus.publish(UtterancePartial(utterance=self._utterance(self._current_id(), words, False, voice)))

    def _finalize(self, include_interim: bool = False) -> None:
        words = self._words + (self._interim if include_interim else [])
        self._words = []
        if include_interim:
            self._interim = []
        if not words:
            return
        uid = self._current_id()
        self._utt_id = None
        voice = self._assign(words)
        self._maybe_relabel()
        self.bus.publish(UtteranceFinal(utterance=self._utterance(uid, words, True, voice)))

    # --- who is "You" -----------------------------------------------------------------

    def _measure(self, words: list[Word]) -> _Loudness:
        turn = _Loudness()
        for w in words:
            first = int(w.start / FRAME_SECONDS)
            last = max(first, math.ceil(w.end / FRAME_SECONDS) - 1)
            frames = self._power[first : last + 1]
            if not frames:
                continue
            duration = max(w.end - w.start, FRAME_SECONDS)
            turn.seconds += duration
            turn.energy += (sum(frames) / len(frames)) * duration
        return turn

    def _route(self, speaker: int, turn: _Loudness) -> int:
        """The voice a turn by diarized `speaker` belongs to: after a split, the nearer group."""
        other = self._second_voice.get(speaker)
        if other is None or turn.seconds <= 0:
            return speaker
        db = turn.db()
        if abs(db - self._loudness[speaker].db()) <= abs(db - self._loudness[other].db()):
            return speaker
        return other

    def _route_stretches(self, words: list[Word]) -> list[Word]:
        """Give each pause-delimited stretch of a split speaker's words the nearer voice."""
        out: list[Word] = []
        start = 0
        for i in range(1, len(words) + 1):
            if i < len(words) and words[i].speaker == words[i - 1].speaker and words[i].start - words[i - 1].end < PAUSE_S:
                continue
            stretch, start = words[start:i], i
            speaker = stretch[0].speaker
            voice = self._route(speaker, self._measure(stretch)) if speaker in self._second_voice else speaker
            out += stretch if voice == speaker else [w.model_copy(update={"speaker": voice}) for w in stretch]
        return out

    def _assign(self, words: list[Word]) -> int:
        """Pick the voice of a final turn and add its loudness there. May split the speaker."""
        speaker = words[0].speaker  # diarized, or already a split-off voice (_route_stretches)
        turn = self._measure(words)
        voice = self._route(speaker, turn)
        if turn.seconds <= 0:
            return voice
        self._loudness.setdefault(voice, _Loudness()).add(turn)
        if speaker in self._second_voice or speaker in self._second_voice.values():
            return voice  # already split; a voice splits at most once
        self._turns.setdefault(speaker, []).append(turn)
        if not self.locked and self._split(speaker):
            voice = self._route(speaker, turn)
        return voice

    def _split(self, speaker: int) -> bool:
        """Split a diarized speaker in two if its turns form a loud and a quiet group.

        A cut of the turns (sorted by loudness) counts if each group has >= MIN_GROUP_S and
        one has >= MIN_SPEECH_S, the groups are >= SPLIT_DB apart, and they fall on opposite
        sides of the call's midpoint: a split that wouldn't change a label isn't made (a
        caller who sometimes speaks up stays one voice). Of those, take the most balanced
        one (largest between-group variance, as in Otsu's method)."""
        turns = self._turns[speaker]
        ranked = sorted(turns, key=_Loudness.db)
        total = _pool(ranked)
        others = [st.db() for v, st in self._loudness.items() if v != speaker and st.seconds >= MIN_SPEECH_S]
        best: tuple[float, int] | None = None
        quiet = _Loudness()
        for k in range(1, len(ranked)):
            quiet.add(ranked[k - 1])
            loud = _Loudness(total.seconds - quiet.seconds, total.energy - quiet.energy)
            if not _two_people(quiet, loud, others):
                continue
            score = quiet.seconds * loud.seconds * (loud.db() - quiet.db()) ** 2
            if best is None or score > best[0]:
                best = (score, k)
        if best is None:
            return False
        k = best[1]

        # The speaker number keeps the group holding its first turn: lines already on
        # screen mostly keep the right label. The other group becomes the new voice.
        first_is_quiet = any(t is turns[0] for t in ranked[:k])
        kept, moved = (ranked[:k], ranked[k:]) if first_is_quiet else (ranked[k:], ranked[:k])
        other = VIRTUAL_BASE + speaker
        self._second_voice[speaker] = other
        del self._turns[speaker]
        self._loudness[speaker] = _pool(kept)
        self._loudness[other] = _pool(moved)
        self._seen.append(other)
        loud_voice, quiet_voice = (other, speaker) if first_is_quiet else (speaker, other)
        new_user = (self.user - {quiet_voice}) | {loud_voice}
        if new_user != self.user:
            self._set_user(new_user, "loudness")
        return True

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
