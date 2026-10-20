"""Known names the extractor can match: fictional companies and firms (scam scenarios)
and a curated list of real tickers (names only, no claims)."""

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@dataclass(frozen=True)
class Company:
    ticker: str
    name: str
    aliases: tuple[str, ...]
    fictional: bool


@dataclass(frozen=True)
class Firm:
    name: str
    aliases: tuple[str, ...]
    fictional: bool


@dataclass
class Catalog:
    companies: dict[str, Company] = field(default_factory=dict)  # by ticker
    firms: list[Firm] = field(default_factory=list)

    def ticker(self, symbol: str) -> Company | None:
        return self.companies.get(symbol.upper())

    @classmethod
    def load(cls, fixtures: Path = FIXTURES) -> "Catalog":
        catalog = cls()
        real = json.loads((fixtures / "tickers.json").read_text())["tickers"]
        fictional = [json.loads(p.read_text()) for p in sorted((fixtures / "companies").glob("*.json"))]
        for entry in [*real, *fictional]:
            company = Company(
                ticker=entry["ticker"].upper(),
                name=entry["name"],
                aliases=tuple(entry.get("aliases", [])),
                fictional=bool(entry.get("fictional", False)),
            )
            catalog.companies[company.ticker] = company
        for entry in json.loads((fixtures / "firms.json").read_text())["firms"]:
            catalog.firms.append(Firm(entry["name"], tuple(entry["aliases"]), bool(entry.get("fictional", True))))
        return catalog


@lru_cache
def default_catalog() -> Catalog:
    return Catalog.load()
