"""Speaker labeler: turns diarized "speaker 0/1" segments into caller/user utterances.

Who is "You":
1. First-turn rule: the first voice heard is provisionally the user (they answer the phone).
2. Bass: the caller comes out of a phone speaker, which barely plays anything below
   ~300 Hz; the user's voice reaches the laptop mic with its full low range. A voice's
   "tone" is its bass (120-300 Hz) relative to its telephone band (300-3400 Hz). Once two
   voices each have >= MIN_SPEECH_S of speech and their tones differ by >= TONE_DB, each
   voice is classified against the midpoint: more bass = the user. This holds however
   loud the phone is; a live test had the phone louder than the user.
3. Loudness, when the tones don't separate: the user sits next to the mic, so once two
   voices differ by >= SWITCH_DB, the louder side is the user. Diarization sometimes
   splits one voice into two speaker numbers; both then still land on the right side.
4. Merged voices: diarization can also put two voices on one speaker number. When one
   speaker's stretches of speech (between pauses) form two groups >= TONE_DB apart in
   tone, or its turns form two groups >= SPLIT_DB apart in loudness, the group without
   its first stretch becomes a second voice, numbered VIRTUAL_BASE + n. From then on each
   stretch of that speaker's words goes to the nearer group, so a turn change Deepgram
   didn't mark still starts a new line. Lines already sent keep their number:
   `speaker_index` is a voice number, and the UI relabels by it as before.
5. Manual swap: the user's "Swap speakers" button inverts the labels and locks them.
   No new splits after that: the user has said who is who.

Consumes: AudioLevel, TranscriptSegment, TranscriptUtteranceEnd, TranscriptClosed, SpeakersSwap.
Publishes: UtterancePartial, UtteranceProgress, UtteranceFinal, SpeakersUpdated, and UtterancesClosed when done.
"""

import math
import time
from collections.abc import Callable
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
    UtteranceProgress,
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
TONE_DB = 10.0  # voices this far apart in tone are a phone speaker and a person
MIN_GROUP_S = 0.3  # a split needs about a word in the smaller group ("Hello?" is 0.4 s)
VIRTUAL_BASE = 100  # voice number for the second person found inside diarized speaker n
PAUSE_S = 0.3  # a silence where a turn may change (Deepgram's endpointing is 300 ms)
LEADING_WORD_GAP_S = 0.25  # a lone first word this close to the next speaker belongs to them


@dataclass
class _Loudness:
    seconds: float = 0.0
    energy: float = 0.0  # sum of mean frame power x word duration
    bass: float = 0.0  # the same, for the 120-300 Hz band
    band: float = 0.0  # the same, for the 300-3400 Hz band

    def db(self) -> float:
        if self.seconds <= 0 or self.energy <= 0:
            return -100.0
        return 10 * math.log10(self.energy / self.seconds)

    def tone(self) -> float:
        """Bass relative to the telephone band, in dB. 0 for every voice without band data."""
        if self.bass <= 0 or self.band <= 0:
            return 0.0
        return 10 * math.log10(self.bass / self.band)

    def add(self, other: "_Loudness") -> None:
        self.seconds += other.seconds
        self.energy += other.energy
        self.bass += other.bass
        self.band += other.band


Feature = Literal["tone", "level"]
FEATURES: dict[Feature, tuple[Callable[[_Loudness], float], float]] = {
    "tone": (_Loudness.tone, TONE_DB),
    "level": (_Loudness.db, SPLIT_DB),
}


def _pool(turns: list[_Loudness]) -> _Loudness:
    total = _Loudness()
    for t in turns:
        total.add(t)
    return total


def _two_people(low: _Loudness, high: _Loudness, others: list[float], feature: Feature = "level") -> bool:
    """Whether a low and a high group of one speaker's speech (by tone or loudness) are
    clearly two people. `others` are the call's other voices with enough speech."""
    key, gap = FEATURES[feature]
    if min(low.seconds, high.seconds) < MIN_GROUP_S or max(low.seconds, high.seconds) < MIN_SPEECH_S:
        return False
    if key(high) - key(low) < gap:
        return False
    values = [key(low), key(high), *others]
    mid = (max(values) + min(values)) / 2
    return key(high) > mid + MARGIN_DB and key(low) < mid - MARGIN_DB


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
        self._bass: list[float] = []  # the same, 120-300 Hz
        self._band: list[float] = []  # the same, 300-3400 Hz
        self._loudness: dict[int, _Loudness] = {}  # per voice: a diarized speaker or a split-off voice
        self._turns: dict[int, list[_Loudness]] = {}  # each final turn's loudness, per unsplit speaker
        self._stretches: dict[int, list[_Loudness]] = {}  # each stretch between pauses, per unsplit speaker
        self._second_voice: dict[int, int] = {}  # diarized speaker -> the voice split off from it
        self._split_by: dict[int, Feature] = {}  # diarized speaker -> what told its two voices apart
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
                    # Each voice's level, tone and seconds so far: the evidence behind the labels.
                    voices = {v: [round(st.db(), 1), round(st.tone(), 1), round(st.seconds, 1)] for v, st in self._loudness.items()}
                    record("labeler", (time.perf_counter() - started) * 1000, call_id=self.call_id, source=self.source, voices=voices)
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
            grow = [0.0] * (index + 1 - len(self._power))
            self._power.extend(grow)
            self._bass.extend(grow)
            self._band.extend(grow)
        self._power[index] = 10 ** (event.dbfs / 10)
        self._bass[index] = 10 ** (event.bass_db / 10)
        self._band[index] = 10 ** (event.voice_db / 10)

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
        if seg.speech_final and not seg.from_finalize:
            self._finalize()  # a flush we asked for finalizes words, but doesn't end the turn
        else:
            self._emit_progress()
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

    def _emit_progress(self) -> None:
        """Finalized words of the turn in progress, so a finished sentence can be checked now."""
        words = smooth_speakers(self._words)
        if words:
            speaker = words[0].speaker
            voice = self._route(speaker, self._measure(words)) if speaker in self._second_voice else speaker
            self.bus.publish(UtteranceProgress(utterance=self._utterance(self._current_id(), words, False, voice)))

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
            turn.bass += (sum(self._bass[first : last + 1]) / len(frames)) * duration
            turn.band += (sum(self._band[first : last + 1]) / len(frames)) * duration
        return turn

    def _measure_stretches(self, words: list[Word]) -> list[_Loudness]:
        """One measurement per stretch of words between pauses (a turn can hold both people)."""
        out, start = [], 0
        for i in range(1, len(words) + 1):
            if i < len(words) and words[i].start - words[i - 1].end < PAUSE_S:
                continue
            stretch = self._measure(words[start:i])
            start = i
            if stretch.seconds > 0:
                out.append(stretch)
        return out

    def _route(self, speaker: int, turn: _Loudness) -> int:
        """The voice a turn by diarized `speaker` belongs to: after a split, the nearer group."""
        other = self._second_voice.get(speaker)
        if other is None or turn.seconds <= 0:
            return speaker
        key = FEATURES[self._split_by[speaker]][0]
        value = key(turn)
        if abs(value - key(self._loudness[speaker])) <= abs(value - key(self._loudness[other])):
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
        self._stretches.setdefault(speaker, []).extend(self._measure_stretches(words))
        if not self.locked and self._split(speaker):
            voice = self._route(speaker, turn)
        return voice

    def _split(self, speaker: int) -> bool:
        """Split a diarized speaker in two if its speech forms two groups: by tone over its
        stretches first (a phone and a person), else by loudness over its turns."""
        for feature, observations in (("tone", self._stretches[speaker]), ("level", self._turns[speaker])):
            cut = self._best_cut(speaker, observations, feature)
            if cut is not None:
                self._split_into(speaker, observations, *cut, feature)
                return True
        return False

    def _best_cut(self, speaker: int, observations: list[_Loudness], feature: Feature) -> tuple[list[_Loudness], int] | None:
        """A cut of the observations (sorted by the feature) counts if each group has >=
        MIN_GROUP_S and one has >= MIN_SPEECH_S, the groups are far enough apart, and they
        fall on opposite sides of the call's midpoint: a split that wouldn't change a label
        isn't made (a caller who sometimes speaks up stays one voice). Of those, take the
        most balanced one (largest between-group variance, as in Otsu's method)."""
        key = FEATURES[feature][0]
        ranked = sorted(observations, key=key)
        total = _pool(ranked)
        others = [key(st) for v, st in self._loudness.items() if v != speaker and st.seconds >= MIN_SPEECH_S]
        best: tuple[float, int] | None = None
        low = _Loudness()
        for k in range(1, len(ranked)):
            low.add(ranked[k - 1])
            high = _Loudness(*(a - b for a, b in zip(
                (total.seconds, total.energy, total.bass, total.band), (low.seconds, low.energy, low.bass, low.band)
            )))  # fmt: skip
            if not _two_people(low, high, others, feature):
                continue
            score = low.seconds * high.seconds * (key(high) - key(low)) ** 2
            if best is None or score > best[0]:
                best = (score, k)
        return None if best is None else (ranked, best[1])

    def _split_into(self, speaker: int, observations: list[_Loudness], ranked: list[_Loudness], k: int, feature: Feature) -> None:
        # The speaker number keeps the group holding its first observation: lines already
        # on screen mostly keep the right label. The other group becomes the new voice.
        first_is_low = any(t is observations[0] for t in ranked[:k])
        kept, moved = (ranked[:k], ranked[k:]) if first_is_low else (ranked[k:], ranked[:k])
        other = VIRTUAL_BASE + speaker
        self._second_voice[speaker] = other
        self._split_by[speaker] = feature
        del self._turns[speaker], self._stretches[speaker]
        self._loudness[speaker] = _pool(kept)
        self._loudness[other] = _pool(moved)
        self._seen.append(other)
        # More bass, or louder: the person at the mic. _maybe_relabel may still correct a
        # loudness split by tone.
        high_voice, low_voice = (other, speaker) if first_is_low else (speaker, other)
        new_user = (self.user - {low_voice}) | {high_voice}
        if new_user != self.user:
            self._set_user(new_user, "tone" if feature == "tone" else "loudness")

    def _maybe_relabel(self) -> None:
        if not self.locked and self._relabel_by_tone():
            return
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

    def _relabel_by_tone(self) -> bool:
        """Classify every voice by tone if the voices clearly differ in it. More bass = the
        user, whatever the loudness. False if tone can't tell them apart."""
        tones = {s: st.tone() for s, st in self._loudness.items() if st.seconds >= MIN_SPEECH_S}
        if len(tones) < 2 or max(tones.values()) - min(tones.values()) < TONE_DB:
            return False
        mid = (max(tones.values()) + min(tones.values())) / 2
        new_user = set(self.user)
        for s, stats in self._loudness.items():
            if stats.seconds < MIN_CLASSIFY_S:
                continue
            if stats.tone() > mid + MARGIN_DB:
                new_user.add(s)
            elif stats.tone() < mid - MARGIN_DB:
                new_user.discard(s)
        if new_user != self.user:
            self._set_user(new_user, "tone")
        return True

    def _swap(self) -> None:
        # Invert every label heard so far and lock: the user knows best.
        self.locked = True
        self._locked_known = set(self._seen)
        self._set_user(set(self._seen) - self.user, "manual")

    def _set_user(self, user: set[int], reason: Literal["first_turn", "loudness", "tone", "manual"]) -> None:
        self.user = user
        self._decided = True
        self.bus.publish(SpeakersUpdated(user_indices=sorted(user), reason=reason, locked=self.locked))
