import asyncio

from providers.catalog import default_catalog
from providers.register import FixtureRegister


def lookup(name):
    return asyncio.run(FixtureRegister(default_catalog()).lookup(name))


def test_registered_firm():
    r = lookup("Riverside Savings Bank")
    assert r.status == "registered" and "TEST-BANK-0147" in r.detail and "1998" in r.detail
    assert "fictional" in r.source


def test_registered_lookup_ignores_case():
    assert lookup("riverside savings bank").status == "registered"


def test_fictional_firm_not_in_register_is_not_found():
    r = lookup("Hartwell & Crane")
    assert r.status == "not_found" and "No record" in r.detail


def test_real_sounding_unknown_firm_is_unverifiable():
    r = lookup("Goldman Sachs")
    assert r.status == "unverifiable" and r.source == "None"
