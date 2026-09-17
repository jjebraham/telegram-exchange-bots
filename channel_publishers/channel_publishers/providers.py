from __future__ import annotations

import re
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Iterable

import requests
from bs4 import BeautifulSoup

from .models import BankRate


class RateSourceError(RuntimeError):
    pass


class BankRatesProvider(ABC):
    @abstractmethod
    def get_rates(self, currency: str, institutions: Iterable[str]) -> list[BankRate]:
        raise NotImplementedError


def _parse_tr_number(text: str) -> float:
    """Parse Turkish-formatted numbers such as 48,6900 or 6.884,60."""
    value = text.strip().replace("\xa0", "").replace(" ", "")
    value = re.sub(r"[^0-9,.-]", "", value)
    if not value:
        raise ValueError(f"not a number: {text!r}")

    if "," in value:
        value = value.replace(".", "").replace(",", ".")
    return float(value)


class DovizComBankRatesProvider(BankRatesProvider):
    """Adapter for the public bank-comparison tables on kur.doviz.com.

    This is intentionally isolated behind `BankRatesProvider`: it is suitable for
    the test phase, but it is not an official bank API and can be replaced later
    with official Ziraat/Isbank/Kuveyt Turk adapters or a licensed aggregate API.
    """

    BASE_URL = "https://kur.doviz.com/altinkaynak/{slug}"
    SLUGS = {
        "USD": "amerikan-dolari",
        "EUR": "euro",
        "GBP": "ingiliz-sterlini",
        "CHF": "isvicre-frangi",
        "CAD": "kanada-dolari",
        "AUD": "avustralya-dolari",
        "JPY": "japon-yeni",
        "KWD": "kuveyt-dinari",
        "SAR": "suudi-arabistan-riyali",
    }

    # Normalize variants that may appear on the source page.
    ALIASES = {
        "kapalıçarşı": "Kapalıçarşı",
        "kapalicarsi": "Kapalıçarşı",
        "garanti bbva": "Garanti BBVA",
        "garanti": "Garanti BBVA",
        "iş bankası": "İş Bankası",
        "is bankası": "İş Bankası",
        "is bankasi": "İş Bankası",
        "kuveyt türk": "Kuveyt Türk",
        "kuveyt turk": "Kuveyt Türk",
        "ziraat bankası": "Ziraat Bankası",
        "ziraat bankasi": "Ziraat Bankası",
    }

    def __init__(self, timeout: float = 12.0, user_agent: str = "AlanChandeChannelPublisher/0.1"):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.7",
            }
        )

    @classmethod
    def _canonical_name(cls, raw_name: str) -> str:
        compact = " ".join(raw_name.split()).strip()
        return cls.ALIASES.get(compact.casefold(), compact)

    def get_rates(self, currency: str, institutions: Iterable[str]) -> list[BankRate]:
        code = currency.upper()
        slug = self.SLUGS.get(code)
        if not slug:
            raise RateSourceError(f"Unsupported currency for bank comparison: {code}")

        wanted = {self._canonical_name(name) for name in institutions}
        url = self.BASE_URL.format(slug=slug)

        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise RateSourceError(f"Failed to fetch {url}: {exc}") from exc

        rates = self.parse_html(response.text, code, wanted, url)
        missing = sorted(wanted - {rate.institution for rate in rates})
        if missing:
            raise RateSourceError(
                "Bank comparison source is incomplete; missing: " + ", ".join(missing)
            )
        return rates

    @classmethod
    def parse_html(
        cls,
        html: str,
        currency: str,
        institutions: set[str],
        source_url: str = "doviz.com",
    ) -> list[BankRate]:
        soup = BeautifulSoup(html, "html.parser")
        found: dict[str, BankRate] = {}

        for row in soup.find_all("tr"):
            cells = [" ".join(cell.get_text(" ", strip=True).split()) for cell in row.find_all(["td", "th"])]
            if len(cells) < 3:
                continue

            institution = cls._canonical_name(cells[0])
            if institution not in institutions:
                continue

            numeric_values: list[float] = []
            for cell in cells[1:]:
                try:
                    numeric_values.append(_parse_tr_number(cell))
                except (ValueError, TypeError):
                    continue
                if len(numeric_values) == 2:
                    break

            if len(numeric_values) < 2:
                continue

            buy, sell = numeric_values[0], numeric_values[1]
            if buy <= 0 or sell <= 0:
                continue

            found[institution] = BankRate(
                institution=institution,
                currency=currency,
                buy=buy,
                sell=sell,
                source=source_url,
                observed_at=datetime.now().astimezone(),
            )

        return [found[name] for name in institutions if name in found]
