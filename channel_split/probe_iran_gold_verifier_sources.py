#!/usr/bin/env python3
"""Compare candidate external Iran-gold sources without affecting publishing.

Diagnostic only. The goal is to identify genuinely independent source families
before any source is allowed to satisfy the production safety quorum.

Candidates are intentionally treated as observational only. Similar values on
different domains do not prove independence.
"""

from __future__ import annotations

import argparse
import re
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

TARGETS = {
    "coinland": "https://coinlandexchange.com/gold",
    "dolarchand": "https://dolarchand.com/en/gold-silver",
    "rialnerkh": "https://www.rialnerkh.com/?lang=en",
    "arzbin": "https://www.arzbin.com/gold",
}

LABELS = (
    "سکه امامی",
    "سکه بهار آزادی",
    "نیم سکه",
    "ربع سکه",
    "سکه گرمی",
    "طلای ۱۸ عیار",
    "طلای 18 عیار",
    "مثقال",
    "Emami",
    "Azadi",
    "Half",
    "Quarter",
    "Gerami",
    "18K",
    "Mithqal",
    "Mesghal",
)


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        clean = " ".join(data.split())
        if clean:
            self.parts.append(clean)


def _fetch(url: str, timeout: int = 20, max_bytes: int = 3_000_000) -> str:
    request = Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.7",
            "Accept-Encoding": "identity",
            "User-Agent": "AlanChande-IranGoldVerifierProbe/1.0",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(max_bytes + 1)
            if len(raw) > max_bytes:
                raise RuntimeError(
                    f"response exceeded {max_bytes} byte diagnostic limit"
                )
            charset = response.headers.get_content_charset() or "utf-8"
            return raw.decode(charset, errors="replace")
    except HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} for {url}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"request failed for {url}: {exc}") from exc


def _normalize_digits(value: str) -> str:
    return value.translate(
        str.maketrans(
            "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
            "01234567890123456789",
        )
    )


def _context(text: str, label: str, radius: int = 180) -> str | None:
    lowered = text.lower()
    needle = label.lower()
    index = lowered.find(needle)
    if index < 0:
        return None
    left = max(0, index - radius)
    right = min(len(text), index + len(label) + radius)
    return " ".join(text[left:right].split())


def _numbers(text: str) -> list[str]:
    normalized = _normalize_digits(text)
    return re.findall(
        r"(?<!\d)\d{1,3}(?:[,.٬]\d{3})+(?!\d)|"
        r"(?<!\d)\d+(?:[.,]\d+)?(?!\d)",
        normalized,
    )


def inspect_source(name: str, url: str) -> None:
    print(f"\n===== {name.upper()} =====")
    print(f"url: {url}")
    try:
        html = _fetch(url)
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")
        return

    parser = _TextParser()
    parser.feed(html)
    text = " ".join(parser.parts)
    print(f"text chars: {len(text)}")

    timestamp_patterns = (
        r"(?:آخرین\s*به.?روزرسانی|آخرین\s*بروز\s*رسانی)\s*[:：]?\s*"
        r"([^|]{3,80})",
        r"Last\s+updated\s*[:：]?\s*([^|]{3,80})",
        r"\b\d{1,2}:\d{2}(?::\d{2})?\b",
    )
    for pattern in timestamp_patterns:
        match = re.search(
            pattern,
            _normalize_digits(text),
            re.IGNORECASE,
        )
        if match:
            print(f"timestamp candidate: {match.group(0)[:140]}")
            break

    seen_contexts: set[str] = set()
    for label in LABELS:
        snippet = _context(text, label)
        if not snippet or snippet in seen_contexts:
            continue
        seen_contexts.add(snippet)
        nums = _numbers(snippet)
        print(f"label: {label}")
        print(f"  numbers: {nums[:12]}")
        print(f"  context: {snippet[:500]}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        choices=("all", *TARGETS.keys()),
        default="all",
    )
    args = parser.parse_args()

    selected = (
        TARGETS.items()
        if args.source == "all"
        else [(args.source, TARGETS[args.source])]
    )
    for name, url in selected:
        inspect_source(name, url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
