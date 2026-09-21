#!/usr/bin/env python3
"""Discover public live-rate endpoints used by official bank web apps.

Diagnostic only. This script does not publish anything and does not modify the
market-history database. It fetches the public Garanti BBVA and Kuveyt Türk
pages/apps, follows public JavaScript asset references, and prints URL/API-like
strings that may identify stable verifier endpoints.

Do not promote a discovered endpoint to production merely because it responds:
the response schema, semantics, freshness and bank ownership still need to be
validated first.
"""

from __future__ import annotations

import argparse
import re
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

GARANTI_APP = (
    "https://webforms.garantibbva.com.tr/"
    "currency-convertor-app-v3/?lang=tr"
)
KUVEYT_PORTAL = "https://www.kuveytturk.com.tr/finans-portali"

KEYWORDS = (
    "api",
    "currency",
    "exchange",
    "rate",
    "rates",
    "doviz",
    "döviz",
    "kur",
    "price",
    "market",
    "quote",
    "forex",
)

ABSOLUTE_URL_RE = re.compile(
    r"""https?://[^"'<>\s)\\]+""",
    re.IGNORECASE,
)
RELATIVE_ENDPOINT_RE = re.compile(
    r"""["']((?:/|\.\.?/)[^"'<>\s]{2,240})["']""",
    re.IGNORECASE,
)


class AssetParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.assets: list[str] = []
        self.iframes: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[no-untyped-def]
        values = dict(attrs)
        if tag == "script" and values.get("src"):
            self.assets.append(values["src"])
        elif tag == "iframe" and values.get("src"):
            self.iframes.append(values["src"])
        elif tag == "link" and values.get("href"):
            rel = str(values.get("rel", "")).lower()
            href = str(values["href"])
            if "preload" in rel and href.endswith(".js"):
                self.assets.append(href)


def _fetch_text(
    url: str,
    *,
    timeout: int = 20,
    max_bytes: int = 3_000_000,
) -> str:
    request = Request(
        url,
        headers={
            "Accept": "*/*",
            "Accept-Encoding": "identity",
            "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.5",
            "User-Agent": "AlanChande-BankVerifierProbe/1.0",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(max_bytes + 1)
            if len(raw) > max_bytes:
                raise RuntimeError(
                    f"response exceeded diagnostic limit of {max_bytes} bytes"
                )
            charset = response.headers.get_content_charset() or "utf-8"
            return raw.decode(charset, errors="replace")
    except HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} for {url}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"request failed for {url}: {exc}") from exc


def _interesting(candidate: str) -> bool:
    lowered = candidate.lower()
    return any(keyword in lowered for keyword in KEYWORDS)


def extract_endpoint_candidates(text: str, base_url: str) -> list[str]:
    found: set[str] = set()

    for match in ABSOLUTE_URL_RE.findall(text):
        cleaned = match.rstrip(".,;]")
        if _interesting(cleaned):
            found.add(cleaned)

    for match in RELATIVE_ENDPOINT_RE.findall(text):
        if _interesting(match):
            found.add(urljoin(base_url, match))

    # Also catch common fetch/axios route literals that do not begin with '/'.
    route_re = re.compile(
        r"""["']([^"'\s]{0,80}(?:api|currency|exchange|rate|doviz|kur|quote)[^"'\s]{0,160})["']""",
        re.IGNORECASE,
    )
    for match in route_re.findall(text):
        if match.startswith(("http://", "https://", "/", "./", "../")):
            candidate = urljoin(base_url, match)
            if _interesting(candidate):
                found.add(candidate)

    return sorted(found)


def discover_page(
    label: str,
    url: str,
    *,
    max_assets: int,
) -> None:
    print(f"\n===== {label} =====")
    print(f"page: {url}")

    try:
        html = _fetch_text(url)
    except Exception as exc:
        print(f"PAGE ERROR: {type(exc).__name__}: {exc}")
        return

    print(f"page bytes/chars: {len(html)}")

    parser = AssetParser()
    parser.feed(html)

    for iframe in parser.iframes:
        print(f"iframe: {urljoin(url, iframe)}")

    page_candidates = extract_endpoint_candidates(html, url)
    if page_candidates:
        print("page endpoint candidates:")
        for candidate in page_candidates[:40]:
            print(f"  {candidate}")

    assets: list[str] = []
    seen: set[str] = set()
    for src in parser.assets:
        absolute = urljoin(url, src)
        if absolute in seen:
            continue
        seen.add(absolute)
        assets.append(absolute)

    print(f"javascript assets discovered: {len(assets)}")

    for asset in assets[:max_assets]:
        parsed = urlparse(asset)
        if parsed.scheme not in {"http", "https"}:
            continue
        print(f"\nasset: {asset}")
        try:
            javascript = _fetch_text(asset)
        except Exception as exc:
            print(f"  ASSET ERROR: {type(exc).__name__}: {exc}")
            continue

        candidates = extract_endpoint_candidates(javascript, asset)
        if not candidates:
            print("  no endpoint-like strings")
            continue

        for candidate in candidates[:60]:
            print(f"  candidate: {candidate}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--bank",
        choices=("all", "garanti", "kuveyt"),
        default="all",
    )
    parser.add_argument(
        "--max-assets",
        type=int,
        default=12,
        help="Maximum JavaScript assets to inspect per bank",
    )
    args = parser.parse_args()

    max_assets = max(1, min(args.max_assets, 30))

    if args.bank in {"all", "garanti"}:
        discover_page(
            "GARANTI BBVA OFFICIAL CURRENCY APP",
            GARANTI_APP,
            max_assets=max_assets,
        )

    if args.bank in {"all", "kuveyt"}:
        discover_page(
            "KUVEYT TURK OFFICIAL FINANCE PORTAL",
            KUVEYT_PORTAL,
            max_assets=max_assets,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
