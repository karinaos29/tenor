"""Secret rules: requests for private details fire; warnings, refusals and honest look-alikes don't."""

import pytest

from detector.secrets import INFO, code_run, find_request, mentioned

REQUESTS = [
    ("Can you read me the code we just sent you?", "one_time_code"),
    ("Please read out the six digit code from the text message.", "one_time_code"),
    ("Read me the numbers we just texted you.", "one_time_code"),
    ("What's the verification code on your screen?", "one_time_code"),
    ("Don't tell your son about this, just read me the code.", "one_time_code"),
    ("I'll need your PIN to stop the transfer.", "pin"),
    ("Could you confirm your PIN number for me?", "pin"),
    ("What is your online banking password?", "password"),
    ("Can you give me the long card number and the three digits on the back?", "card"),
    ("I just need the security code on the back of the card.", "card"),
    ("Could you read me your recovery phrase, the twelve words?", "recovery_phrase"),
    ("Please download AnyDesk so I can fix it for you.", "remote_access"),
    ("Let me have access to your computer for a minute.", "remote_access"),
    ("What's your account number and sort code?", "account_number"),
    ("To confirm it's you, what's your date of birth?", "identity"),
    ("Can you tell me your social security number?", "identity"),
]

HONEST = [
    "We will never ask you for your PIN or password.",
    "Never share that code with anyone, not even us.",
    "Don't read the code to anyone who calls you.",
    "No one from the bank will ever ask for your code.",
    "I don't give out codes on the phone.",
    "I don't give my PIN to anyone.",
    "Please type the code into the app yourself.",
    "We've sent you a code by text.",
    "You'll get a six digit code in a minute.",
    "Keep your password to yourself.",
    "The card has a chip and a PIN.",
    "Your statement shows the account number at the top.",
    "Can you tell me which fund you're interested in?",
    "What's the best time to call you back?",
    "Could you confirm that you received the letter?",
]


@pytest.mark.parametrize(("sentence", "kind"), REQUESTS)
def test_requests_fire(sentence, kind):
    found = find_request(sentence)
    assert found is not None and found.kind == kind, sentence


@pytest.mark.parametrize("sentence", HONEST)
def test_honest_look_alikes_stay_quiet(sentence):
    assert find_request(sentence) is None, sentence


def test_an_ask_can_point_back_at_a_detail_mentioned_just_before():
    first = "We just sent you a six digit code by text."
    assert find_request(first) is None
    assert mentioned(first) == "one_time_code"
    assert find_request("Can you read it to me?", recent="one_time_code").kind == "one_time_code"
    assert find_request("What does it say?", recent="one_time_code").kind == "one_time_code"
    # A pointer that isn't the thing being read out.
    assert find_request("Could you confirm that you got it?", recent="one_time_code") is None
    assert find_request("Can you read it to me?") is None  # nothing mentioned


def test_a_refusal_isnt_a_mention():
    assert mentioned("Never share your code with anyone.") is None


def test_request_end_points_past_the_request():
    s = "Read me the code we sent you. 4 7 2"
    r = find_request(s)
    assert r is not None and code_run(s[r.end :]) == 3


def test_every_kind_has_a_label_and_level():
    assert set(INFO) == {k for _, k in REQUESTS}
    assert {i.level for i in INFO.values()} == {"stop", "check"}


@pytest.mark.parametrize(
    ("text", "run"),
    [
        ("It says four, seven, two, nine", 4),
        ("Oh, yes. It says four seven two nine one six.", 6),
        ("4729", 4),
        ("47 29 16", 6),
        ("double seven three one", 4),
        ("It's four, oh, five", 3),
        ("B 7 4 K", 4),
        ("One moment please, I need my glasses.", 1),
        ("a six digit code", 1),
        ("Oh, I see.", 0),
        ("I have a question.", 0),
        ("", 0),
    ],
)
def test_code_run(text, run):
    assert code_run(text) == run


def test_a_pointer_must_end_the_ask():
    assert find_request("Read them out, please.", recent="one_time_code") is not None
    assert find_request("To confirm it, see", recent="pin") is None  # half-heard interim words
