from __future__ import annotations

import hashlib
import json
import random
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Sequence

UTC = timezone.utc
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,39}$")


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso_utc(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("datetime must include a timezone")
    return value.astimezone(UTC).isoformat()


def parse_datetime(value: str) -> datetime:
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        raise ValueError("datetime must include a UTC offset, e.g. +03:00")
    return dt.astimezone(UTC)


def points_from_invites(invites: int, invites_per_point: int, max_points: int) -> int:
    if invites_per_point < 1:
        raise ValueError("invites_per_point must be >= 1")
    points = max(0, invites) // invites_per_point
    if max_points > 0:
        points = min(points, max_points)
    return points


def weighted_draw(entrants: Sequence[tuple[int, int]], seed: str, winners: int) -> list[int]:
    """Deterministic weighted sampling without replacement."""
    clean = [(int(uid), int(tickets)) for uid, tickets in entrants if int(tickets) > 0]
    clean.sort(key=lambda x: x[0])
    if winners < 1 or not clean:
        return []
    seed_int = int.from_bytes(hashlib.sha256(seed.encode("utf-8")).digest(), "big")
    rng = random.Random(seed_int)
    pool = clean[:]
    result: list[int] = []
    for _ in range(min(winners, len(pool))):
        total = sum(tickets for _, tickets in pool)
        pick = rng.uniform(0, total)
        cursor = 0.0
        for index, (uid, tickets) in enumerate(pool):
            cursor += tickets
            if cursor >= pick:
                result.append(uid)
                pool.pop(index)
                break
    return result


def entrant_snapshot(entrants: Sequence[tuple[int, int]]) -> tuple[str, str]:
    ordered = sorted((int(uid), int(tickets)) for uid, tickets in entrants)
    payload = json.dumps(ordered, separators=(",", ":"))
    return payload, hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Campaign:
    id: int
    slug: str
    name: str
    start_at: str
    end_at: str
    status: str
    invites_per_point: int
    min_stay_hours: int
    max_points: int
    num_winners: int
    prize_text: str

    @property
    def start_dt(self) -> datetime:
        return parse_datetime(self.start_at)

    @property
    def end_dt(self) -> datetime:
        return parse_datetime(self.end_at)

    def is_live(self, now: datetime | None = None) -> bool:
        now = (now or utcnow()).astimezone(UTC)
        return self.status == "active" and self.start_dt <= now < self.end_dt

    def cutoff(self, now: datetime | None = None) -> datetime:
        now = (now or utcnow()).astimezone(UTC)
        return now - timedelta(hours=self.min_stay_hours)
