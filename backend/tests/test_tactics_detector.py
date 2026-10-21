"""PressureDetector on a real bus with a fake classifier."""

import asyncio

from detector.taxonomy import BY_ID
from pipeline.bus import EventBus
from pipeline.events import TacticFlagged, TacticsClosed, Utterance, UtteranceFinal, UtteranceProgress, UtterancesClosed
from pipeline.tactics import PressureDetector, sentences
from tests.m3_helpers import latency_entries

ALL = {t: 0.5 for t in BY_ID}


class FakeClassifier:
    def __init__(self, canned=None, threshold=0.5):
        self.thresholds = {t: threshold for t in BY_ID}
        self.canned = canned or {}
        self.seen: list[str] = []

    def predict_proba(self, texts):
        self.seen += texts
        return [{**{t: 0.0 for t in BY_ID}, **self.canned.get(x, {})} for x in texts]


def utt(text, speaker="caller", id="u1", final=False):
    return Utterance(id=id, speaker=speaker, speaker_index=1, text=text, t_start=0, t_end=1, is_final=final)


def run(events, classifier=None):
    async def main():
        bus = EventBus()
        det = PressureDetector(bus, classifier, call_id="c", source="test")
        spy = bus.subscribe(TacticFlagged, TacticsClosed, UtterancesClosed)
        task = asyncio.create_task(det.run())
        for e in events:
            bus.publish(e)
            await asyncio.sleep(0)
        bus.publish(UtterancesClosed())
        await asyncio.wait_for(task, 5)
        spy.close()
        return [e async for e in spy]

    return asyncio.run(main())


def flags(out):
    return [e.flag for e in out if isinstance(e, TacticFlagged)]


def test_sentence_splitter():
    assert sentences("One thing. Two things? Three!") == ["One thing.", "Two things?", "Three!"]
    assert sentences("It is 3.5 percent.") == ["It is 3.5 percent."]


def test_user_lines_are_ignored():
    c = FakeClassifier({"Keep it quiet please.": {"secrecy": 0.99}})
    out = run([UtteranceFinal(utterance=utt("Keep this between us.", speaker="user", final=True))], c)
    assert flags(out) == [] and c.seen == []


def test_progress_scores_completed_sentences_then_final_scores_the_rest_once():
    c = FakeClassifier()
    run(
        [
            UtteranceProgress(utterance=utt("Hello there. How are")),
            UtteranceProgress(utterance=utt("Hello there. How are you today. And")),
            UtteranceFinal(utterance=utt("Hello there. How are you today. And goodbye.", final=True)),
        ],
        c,
    )
    assert c.seen == ["Hello there.", "How are you today.", "And goodbye."]


def test_incomplete_progress_scores_nothing():
    c = FakeClassifier()
    run([UtteranceProgress(utterance=utt("Hello there and"))], c)
    assert c.seen == []


def test_classifier_only_flag_is_mild_with_score():
    c = FakeClassifier({"Hmm that is quiet.": {"secrecy": 0.7}})
    (f,) = flags(run([UtteranceFinal(utterance=utt("Hmm that is quiet.", final=True))], c))
    assert (f.tactic, f.severity, f.source, f.score) == ("secrecy", "mild", "classifier", 0.7)
    assert f.label == BY_ID["secrecy"].label and f.quote == "Hmm that is quiet." and f.utterance_id == "u1"


def test_high_confidence_classifier_is_strong():
    c = FakeClassifier({"Hmm that is quiet.": {"secrecy": 0.95}})
    (f,) = flags(run([UtteranceFinal(utterance=utt("Hmm that is quiet.", final=True))], c))
    assert f.severity == "strong" and f.source == "classifier"


def test_below_threshold_is_not_flagged():
    c = FakeClassifier({"Hmm that is quiet.": {"secrecy": 0.49}})
    assert flags(run([UtteranceFinal(utterance=utt("Hmm that is quiet.", final=True))], c)) == []


def test_rule_hit_is_strong_and_source_rule():
    c = FakeClassifier()
    (f,) = flags(run([UtteranceFinal(utterance=utt("It is a sure thing.", final=True))], c))
    assert (f.tactic, f.severity, f.source, f.score) == ("guarantee", "strong", "rule", 1.0)


def test_both_source_and_strong_even_at_low_p():
    c = FakeClassifier({"It is a sure thing.": {"guarantee": 0.6}})
    (f,) = flags(run([UtteranceFinal(utterance=utt("It is a sure thing.", final=True))], c))
    assert (f.severity, f.source, f.score) == ("strong", "both", 0.6)


def test_ids_unique_across_sentences_and_tactics():
    text = "It is a sure thing. Keep this between us."
    out = flags(run([UtteranceFinal(utterance=utt(text, final=True))], FakeClassifier()))
    assert {f.tactic for f in out} == {"guarantee", "secrecy"}
    assert len({f.id for f in out}) == len(out) == 2


def test_no_classifier_rules_still_flag():
    (f,) = flags(run([UtteranceFinal(utterance=utt("Decide now, please.", final=True))], None))
    assert f.tactic == "urgency" and f.source == "rule"


def test_tactics_closed_comes_after_utterances_closed():
    out = run([UtteranceFinal(utterance=utt("It is a sure thing.", final=True))], None)
    kinds = [type(e) for e in out]
    assert kinds.index(UtterancesClosed) < kinds.index(TacticsClosed) == len(kinds) - 1


def test_latency_recorded_per_scored_sentence():
    run([UtteranceFinal(utterance=utt("Hello there. Nice day.", final=True))], FakeClassifier())
    rows = latency_entries("detector")
    assert len(rows) == 2 and all(r["call_id"] == "c" and r["source"] == "test" for r in rows)
