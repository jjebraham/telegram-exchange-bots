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
import json
import re
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

GARANTI_APP = (
    "https://webforms.garantibbva.com.tr/"
    "currency-convertor-app-v3/?lang=tr"
)
GARANTI_CONFIG = (
    "https://webforms.garantibbva.com.tr/"
    "currency-convertor-app-v3/config"
)
KUVEYT_PORTAL = "https://www.kuveytturk.com.tr/finans-portali"
KUVEYT_CONVERTER = (
    "https://www.kuveytturk.com.tr/hesaplama-araclari/doviz-cevirici"
)

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
    "parity",
    "parities",
    "converter",
    "convertor",
    "finance",
    "portal",
    "summary",
)


CALL_URL_PATTERNS = (
    re.compile(
        r"""fetch\(\s*["']([^"']{2,300})["']""",
        re.IGNORECASE,
    ),
    re.compile(
        r"""axios(?:\.[a-z]+)?\(\s*["']([^"']{2,300})["']""",
        re.IGNORECASE,
    ),
    re.compile(
        r"""\.open\(\s*["'][A-Z]+["']\s*,\s*["']([^"']{2,300})["']""",
        re.IGNORECASE,
    ),
    re.compile(
        r"""\burl\s*:\s*["']([^"']{2,300})["']""",
        re.IGNORECASE,
    ),
)

CONTEXT_TERMS = (
    "currency",
    "exchange",
    "doviz",
    "döviz",
    "parity",
    "parities",
    "alis",
    "alış",
    "satis",
    "satış",
    "usd",
    "try",
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

    for pattern in CALL_URL_PATTERNS:
        for match in pattern.findall(text):
            candidate = urljoin(base_url, match)
            parsed = urlparse(candidate)
            if parsed.scheme in {"http", "https"}:
                found.add(candidate)

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



def extract_context_snippets(
    text: str,
    *,
    radius: int = 180,
    limit: int = 24,
) -> list[str]:
    """Return compact unique JS contexts around rate-related terms."""
    lowered = text.lower()
    snippets: list[str] = []
    seen: set[str] = set()

    for term in CONTEXT_TERMS:
        start = 0
        needle = term.lower()
        while len(snippets) < limit:
            index = lowered.find(needle, start)
            if index < 0:
                break
            left = max(0, index - radius)
            right = min(len(text), index + len(term) + radius)
            snippet = " ".join(text[left:right].split())
            if snippet and snippet not in seen:
                seen.add(snippet)
                snippets.append(snippet)
            start = index + len(term)
        if len(snippets) >= limit:
            break

    return snippets



def _flatten_json(value, prefix: str = "") -> list[tuple[str, object]]:
    rows: list[tuple[str, object]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            rows.extend(_flatten_json(child, child_prefix))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            rows.extend(_flatten_json(child, f"{prefix}[{index}]"))
    else:
        rows.append((prefix, value))
    return rows


def inspect_garanti_config(*, max_bytes: int) -> None:
    print("\n===== GARANTI FOCUSED CONFIG =====")
    print(f"config: {GARANTI_CONFIG}")
    try:
        text = _fetch_text(GARANTI_CONFIG, max_bytes=max_bytes)
    except Exception as exc:
        print(f"CONFIG ERROR: {type(exc).__name__}: {exc}")
        return

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        print("config is not JSON; first 4000 chars:")
        print(text[:4000])
        return

    interesting_keys = (
        "path",
        "url",
        "service",
        "api",
        "currency",
        "exchange",
        "rate",
        "overview",
        "chart",
    )
    for key, value in _flatten_json(payload):
        lowered = key.lower()
        if any(term in lowered for term in interesting_keys):
            print(f"{key} = {value!r}")


def extract_kuveyt_api_tokens(text: str) -> dict[str, str]:
    wanted = ("exchangeRates", "financePortal", "parities")
    result: dict[str, str] = {}
    for name in wanted:
        match = re.search(
            rf"""\b{name}\s*:\s*["']([^"']+)["']""",
            text,
            re.IGNORECASE,
        )
        if match:
            result[name] = match.group(1)
    return result


def _context_around(
    text: str,
    needle: str,
    *,
    radius: int = 800,
) -> str | None:
    index = text.find(needle)
    if index < 0:
        return None
    return " ".join(
        text[max(0, index - radius): index + len(needle) + radius].split()
    )



def _find_garanti_main_bundle(html: str) -> str | None:
    parser = AssetParser()
    parser.feed(html)
    for src in parser.assets:
        if "/assets/index." in src and src.endswith(".js"):
            return urljoin(GARANTI_APP, src)
    return None


def extract_garanti_hook_aliases(text: str) -> dict[str, str]:
    names = (
        "useCalculatePriceMutation",
        "useGetExpandedCurrRateQuery",
        "useGetCurrencyOverviewQuery",
        "useGetExchangeChartSeriesQuery",
    )
    aliases: dict[str, str] = {}
    for name in names:
        match = re.search(
            rf"""\b{name}\s*:\s*([A-Za-z_$][A-Za-z0-9_$]*)""",
            text,
        )
        if match:
            aliases[name] = match.group(1)
    return aliases


def _contexts_for_call_alias(
    text: str,
    alias: str,
    *,
    limit: int = 8,
    radius: int = 900,
) -> list[str]:
    pattern = re.compile(rf"""(?<![A-Za-z0-9_$]){re.escape(alias)}\s*\(""")
    snippets: list[str] = []
    for match in pattern.finditer(text):
        left = max(0, match.start() - radius)
        right = min(len(text), match.end() + radius)
        snippet = " ".join(text[left:right].split())
        if snippet not in snippets:
            snippets.append(snippet)
        if len(snippets) >= limit:
            break
    return snippets


def inspect_garanti_request_shape(*, max_bytes: int) -> None:
    print("\n===== GARANTI FOCUSED REQUEST SHAPE =====")
    try:
        html = _fetch_text(GARANTI_APP, max_bytes=max_bytes)
    except Exception as exc:
        print(f"APP ERROR: {type(exc).__name__}: {exc}")
        return

    bundle_url = _find_garanti_main_bundle(html)
    if not bundle_url:
        print("main index bundle not found")
        return

    print(f"bundle: {bundle_url}")
    try:
        javascript = _fetch_text(bundle_url, max_bytes=max_bytes)
    except Exception as exc:
        print(f"BUNDLE ERROR: {type(exc).__name__}: {exc}")
        return

    aliases = extract_garanti_hook_aliases(javascript)
    for hook, alias in aliases.items():
        print(f"{hook}: alias={alias}")
        contexts = _contexts_for_call_alias(javascript, alias)
        for index, context in enumerate(contexts, 1):
            print(f"  call-context-{index}: {context[:4200]}")

    for needle in (
        "expandedCurrRateServicePath",
        "currencyListServicePath",
        "convertCurrencyServicePath",
        "getExpandedCurrRate",
    ):
        context = _context_around(javascript, needle, radius=1400)
        if context:
            print(f"bundle context [{needle}]: {context[:4200]}")


def inspect_kuveyt_core(
    *,
    max_bytes: int,
    probe_endpoint: bool,
) -> None:
    print("\n===== KUVEYT FOCUSED API MAP =====")
    page = _fetch_text(KUVEYT_PORTAL, max_bytes=max_bytes)
    parser = AssetParser()
    parser.feed(page)

    core_asset = next(
        (
            urljoin(KUVEYT_PORTAL, src)
            for src in parser.assets
            if "magiclick.core" in src
        ),
        None,
    )
    sub_asset = next(
        (
            urljoin(KUVEYT_PORTAL, src)
            for src in parser.assets
            if "magiclick.sub" in src
        ),
        None,
    )

    if not core_asset:
        print("magiclick.core asset not found")
        return

    print(f"core asset: {core_asset}")
    core = _fetch_text(core_asset, max_bytes=max_bytes)
    tokens = extract_kuveyt_api_tokens(core)

    if not tokens:
        print("No exchangeRates/financePortal/parities API tokens found.")
    else:
        for name, token in tokens.items():
            resolved = urljoin(KUVEYT_PORTAL, token)
            print(f"{name}: token={token!r}")
            print(f"{name}: resolved={resolved}")

            if probe_endpoint:
                try:
                    body = _fetch_text(
                        resolved,
                        max_bytes=min(max_bytes, 2_000_000),
                    )
                except Exception as exc:
                    print(
                        f"{name}: PROBE ERROR: "
                        f"{type(exc).__name__}: {exc}"
                    )
                else:
                    compact = " ".join(body.split())
                    print(
                        f"{name}: response chars={len(body)} "
                        f"preview={compact[:1800]}"
                    )

    for needle in (
        "MODULES.Utility.Ajax",
        "Utility.Ajax=function",
        "Ajax:function",
        "ApiEndpoints=",
    ):
        context = _context_around(core, needle)
        if context:
            print(f"core context [{needle}]: {context[:3000]}")

    if sub_asset:
        print(f"sub asset: {sub_asset}")
        sub = _fetch_text(sub_asset, max_bytes=max_bytes)
        for needle in (
            "ApiEndpoints.exchangeRates",
            "BuyRate",
            "SellRate",
            "CurrencyCode",
        ):
            context = _context_around(sub, needle)
            if context:
                print(f"sub context [{needle}]: {context[:2600]}")


def discover_page(
    label: str,
    url: str,
    *,
    max_assets: int,
    max_bytes: int,
) -> None:
    print(f"\n===== {label} =====")
    print(f"page: {url}")

    try:
        html = _fetch_text(url, max_bytes=max_bytes)
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
            javascript = _fetch_text(asset, max_bytes=max_bytes)
        except Exception as exc:
            print(f"  ASSET ERROR: {type(exc).__name__}: {exc}")
            continue

        candidates = extract_endpoint_candidates(javascript, asset)
        if candidates:
            for candidate in candidates[:80]:
                print(f"  candidate: {candidate}")
        else:
            print("  no endpoint-like strings")

        snippets = extract_context_snippets(javascript)
        if snippets:
            print("  rate-related contexts:")
            for snippet in snippets:
                print(f"    context: {snippet[:700]}")


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
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=12_000_000,
        help="Maximum response size to inspect for each page/asset",
    )
    parser.add_argument(
        "--focused",
        action="store_true",
        help=(
            "Run focused Garanti config and Kuveyt API-map diagnostics "
            "instead of dumping all JavaScript contexts"
        ),
    )
    parser.add_argument(
        "--probe-endpoints",
        action="store_true",
        help=(
            "With --focused, issue safe GET probes to discovered Kuveyt "
            "public endpoint tokens and print a short response preview"
        ),
    )
    args = parser.parse_args()

    max_assets = max(1, min(args.max_assets, 30))
    max_bytes = max(500_000, min(args.max_bytes, 25_000_000))

    if args.focused:
        if args.bank in {"all", "garanti"}:
            inspect_garanti_config(max_bytes=max_bytes)
            inspect_garanti_request_shape(max_bytes=max_bytes)
        if args.bank in {"all", "kuveyt"}:
            inspect_kuveyt_core(
                max_bytes=max_bytes,
                probe_endpoint=args.probe_endpoints,
            )
        return 0

    if args.bank in {"all", "garanti"}:
        discover_page(
            "GARANTI BBVA OFFICIAL CURRENCY APP",
            GARANTI_APP,
            max_assets=max_assets,
            max_bytes=max_bytes,
        )

    if args.bank in {"all", "kuveyt"}:
        discover_page(
            "KUVEYT TURK OFFICIAL FINANCE PORTAL",
            KUVEYT_PORTAL,
            max_assets=max_assets,
            max_bytes=max_bytes,
        )
        discover_page(
            "KUVEYT TURK OFFICIAL CURRENCY CONVERTER",
            KUVEYT_CONVERTER,
            max_assets=max_assets,
            max_bytes=max_bytes,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
