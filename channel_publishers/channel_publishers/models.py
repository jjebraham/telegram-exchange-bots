from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class BankRate:
    institution: str
    currency: str
    buy: float
    sell: float
    source: str
    observed_at: datetime | None = None

    @property
    def spread(self) -> float:
        return self.sell - self.buy

    @property
    def spread_pct(self) -> float:
        if self.buy <= 0:
            return 0.0
        return (self.spread / self.buy) * 100
