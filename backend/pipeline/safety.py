"""Secret guard: warns Eszter when the caller asks for a private detail, and again if she
starts to read one out. Rules only (detector/secrets.py); no model, no network.

Three states:
- listening: each sentence is matched for a request, in the interim words too
  (utterance.partial), so a request inside a long turn is seen as it's said. Interim
  words are misheard more ("ever" for "never"), so only a direct request counts there
  (an ask and the detail together); remembered mentions need finished sentences. A detail mentioned without an ask ("we sent you a code") is remembered for
  `mention_for_s`, so "Can you read it to me?" right after it counts as a request.
- asked: for `asked_for_s` after a request, the live words (utterance.partial too) are
  watched for a run of code characters (digits, digit words, spelled letters).
- sharing: once `share_run` code characters in a row are heard after a "stop" request
  (a code, PIN, password, card, recovery phrase or remote access), SecretSharing is
  published, once per request. "Check" requests (account number, date of birth) only warn.

Both speakers are matched: speakerphone diarization often gives the caller's request and
Eszter's answer the same label (a real replay labeled the whole exchange "You"). The cost
is that a caller reading digits back after a request also triggers the interruption.

Nothing secret is kept or published: events carry the kind of detail and a masked quote.

Consumes: UtterancePartial, UtteranceProgress, UtteranceFinal, UtterancesClosed.
Publishes: SecretRequested, SecretSharing, SecretsClosed.
"""

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from detector.secrets import INFO, code_run, find_request, mentioned
from pipeline.bus import EventBus
from pipeline.events import (
    SecretKind,
    SecretRequested,
    SecretsClosed,
    SecretSharing,
    Utterance,
    UtteranceFinal,
    UtterancePartial,
    UtteranceProgress,
    UtterancesClosed,
)
from pipeline.latency import record

ASKED_FOR_S = 30.0
MENTION_FOR_S = 20.0
SHARE_RUN = 2  # code characters in a row; the timing test heard them ~1 s apart
_SENTENCE = re.compile(r"[^.?!]+(?:[.?!]+|$)")
_DIGITS = re.compile(r"\d")


@dataclass
class _Asked:
    kind: SecretKind
    t: float
    utterance_id: str
    offset: int  # an answer in the request's own utterance starts here
    before: set[str] = field(default_factory=set)  # utterances already over at the request
    shared: bool = False


def mask(text: str) -> str:
    return _DIGITS.sub("•", text)


class SecretGuard:
    def __init__(
        self,
        bus: EventBus,
        *,
        call_id: str = "",
        source: str = "",
        clock: Callable[[float], float | None] | None = None,
        asked_for_s: float = ASKED_FOR_S,
        mention_for_s: float = MENTION_FOR_S,
        share_run: int = SHARE_RUN,
    ) -> None:
        self.bus = bus
        self.call_id = call_id
        self.source = source
        self.clock = clock  # call time (s) -> time.monotonic() of that moment of audio
        self.asked_for_s = asked_for_s
        self.mention_for_s = mention_for_s
        self.share_run = share_run
        self._sub = bus.subscribe(UtterancePartial, UtteranceProgress, UtteranceFinal, UtterancesClosed)
        self._done: dict[str, int] = {}  # utterance -> characters already matched for requests
        self._seen: set[str] = set()
        self._mention: tuple[SecretKind, float] | None = None
        self._asked: _Asked | None = None

    async def run(self) -> None:
        async for event in self._sub:
            if isinstance(event, UtterancesClosed):
                break
            started = time.perf_counter()
            u = event.utterance
            if isinstance(event, (UtteranceProgress, UtteranceFinal)):
                self._requests(u, final=isinstance(event, UtteranceFinal))
            else:
                # Interim words too: a request inside a long turn otherwise waits for the
                # turn to settle (2.1 s on a replay). Asking again never warns twice.
                self._requests(u, final=False, peek=True)
            self._sharing(u)
            self._seen.add(u.id)
            record("secret_guard", (time.perf_counter() - started) * 1000, call_id=self.call_id, source=self.source)
        self.bus.publish(SecretsClosed())
        self._sub.close()

    # --- requests ---------------------------------------------------------------------

    def _requests(self, u: Utterance, final: bool, peek: bool = False) -> None:
        """Match new sentences. `peek` (interim words) matches the unfinished one too, but
        marks nothing done: the finished words are matched again when they arrive."""
        done = self._done.get(u.id, 0)
        for m in _SENTENCE.finditer(u.text, done):
            sentence = m.group(0)
            if peek:
                self._sentence(u, sentence, m.start(), interim=True)
                continue
            if not final and not re.search(r"[.?!]\s*$", sentence):
                break  # unfinished: wait for the rest of it
            self._done[u.id] = m.end()
            self._sentence(u, sentence, m.start())
        if final:
            self._done.pop(u.id, None)

    def _sentence(self, u: Utterance, sentence: str, at: int, interim: bool = False) -> None:
        fresh = self._mention and u.t_end - self._mention[1] <= self.mention_for_s
        recent = self._mention[0] if fresh and not interim else None  # type: ignore[index]
        found = find_request(sentence, recent)
        if found is None:
            if not interim and (kind := mentioned(sentence)):
                self._mention = (kind, u.t_end)
            return
        asked = self._asked
        same = asked is not None and asked.kind == found.kind and u.t_end - asked.t <= self.asked_for_s
        # The same request matched again (finished words after interim ones, which can come
        # after the answer has started) keeps the first one's boundary.
        before = asked.before if same else self._seen - {u.id}  # type: ignore[union-attr]
        self._asked = _Asked(
            kind=found.kind, t=u.t_end, utterance_id=u.id, offset=at + found.end,
            before=before, shared=same and asked.shared,  # type: ignore[union-attr]
        )  # fmt: skip
        if same:
            return  # asked again: keep watching, don't warn twice
        info = INFO[found.kind]
        self.bus.publish(
            SecretRequested(
                kind=found.kind, level=info.level, label=info.label, quote=mask(sentence.strip()),
                utterance_id=u.id, t=u.t_end,
            )  # fmt: skip
        )
        self._e2e("secret.request_e2e", u.t_end, kind=found.kind)

    # --- an answer being read out -----------------------------------------------------

    def _sharing(self, u: Utterance) -> None:
        a = self._asked
        if a is None or a.shared or INFO[a.kind].level != "stop" or u.id in a.before:
            return
        if u.t_start - a.t > self.asked_for_s:
            return
        text = u.text[a.offset :] if u.id == a.utterance_id else u.text
        if code_run(text) < self.share_run:
            return
        a.shared = True
        self.bus.publish(SecretSharing(kind=a.kind, label=INFO[a.kind].label, utterance_id=u.id, t=u.t_end))
        self._e2e("secret.share_e2e", u.t_end, kind=a.kind, since_request_s=round(u.t_end - a.t, 2))

    def _e2e(self, stage: str, t_call: float, **extra: object) -> None:
        spoken_at = self.clock(t_call) if self.clock else None
        if spoken_at is not None:
            record(stage, (time.monotonic() - spoken_at) * 1000, call_id=self.call_id, source=self.source, **extra)
