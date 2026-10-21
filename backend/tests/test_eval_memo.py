import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "eval"))

import run_eval as ev  # noqa: E402

from detector.taxonomy import BY_ID  # noqa: E402
from memo.builder import build_memo  # noqa: E402
from pipeline.events import Claim, MemoItem, MemoSection  # noqa: E402
from tests.m5_helpers import scam_record  # noqa: E402


def memo_with(*secs):
    return build_memo(scam_record(), "A calm summary.", "template").model_copy(update={"sections": list(secs)})


def test_none_is_not_ok():
    assert ev.memo_ok(None) is False


def test_own_text_with_buy_fails():
    assert ev.memo_ok(memo_with(MemoSection(id="steps", title="t", items=[MemoItem(text="You should buy now")]))) is False
    bad = build_memo(scam_record(), "Consider to sell.", "template")
    assert ev.memo_ok(bad) is False


def test_caller_quotes_are_exempt():
    pressure = MemoSection(id="pressure", title="p", items=[MemoItem(text="Urgency", detail="“it is safe, buy now”")])
    claims = MemoSection(id="claims", title="c", items=[MemoItem(text="“totally safe”", detail="Couldn't verify.")])
    assert ev.memo_ok(memo_with(pressure, claims)) is True
    # ...but a claim detail that is Tenor's own words is checked
    own = MemoSection(id="claims", title="c", items=[MemoItem(text="“x”", detail="This is safe")])
    assert ev.memo_ok(memo_with(own)) is False


def test_real_scam_memo_is_ok():
    assert ev.memo_ok(build_memo(scam_record(), "ok", "template")) is True


def test_social_proof_say_this_has_no_buy():
    import re

    assert not re.search(r"\bbuy", BY_ID["social_proof"].say_this, re.I)
