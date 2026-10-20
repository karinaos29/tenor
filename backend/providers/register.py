"""Firm register lookups. The prototype has a test register for fictional firms only;
real or unknown firms are "couldn't verify" (never a claim about a real firm)."""

import json
from dataclasses import dataclass
from typing import Literal

from providers.catalog import FIXTURES, Catalog


@dataclass(frozen=True)
class RegisterResult:
    status: Literal["registered", "not_found", "unverifiable"]
    firm: str
    detail: str
    source: str


class FixtureRegister:
    def __init__(self, catalog: Catalog) -> None:
        data = json.loads((FIXTURES / "register.json").read_text())
        self.source = data["source"]
        self._firms = {f["name"].lower(): f for f in data["firms"]}
        self.catalog = catalog

    async def lookup(self, firm: str) -> RegisterResult:
        entry = self._firms.get(firm.lower())
        if entry:
            detail = f"Registered since {entry['since']} (ID {entry['register_id']})"
            return RegisterResult("registered", firm, detail, self.source)
        known_fictional = any(f.name.lower() == firm.lower() and f.fictional for f in self.catalog.firms)
        if known_fictional:
            return RegisterResult("not_found", firm, "No record found in the register", self.source)
        return RegisterResult("unverifiable", firm, "No register connection for this firm in the prototype", "None")
