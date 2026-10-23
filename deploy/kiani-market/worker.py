#!/usr/bin/env python3
"""Kiani Akamai feed preflight and optional snapshot worker.

No production flag is changed by this file. Run --audit first.
Untimestamped APIs require current HTTP metadata plus an observed book change.
Observation times are never described as exchange-generated timestamps.
"""
from __future__ import annotations
import argparse
import ast
import configparser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import re
import tempfile
import time
import sys
sys.path.insert(0, "/home/kianirad2020/telegram_bot_repo/channel_split")

HOST = "139.162.186.28"
MAX_AGE = 90
from akamai_rate_feed import ORDER_MINIMUM_SOURCES, sources_agree
MIN_SOURCES = ORDER_MINIMUM_SOURCES
SELECTORS = ("nobitex_book", "nobitex_stats", "wallex_markets", "tabdeal_depth",
             "ramzinex_book", "ramzinex_pairs", "raastin_depth", "exir_books", "exir_book",
             "wallex_depth", "wallex_trades", "tabdeal_trades", "raastin_state", "exir_state",
             "bitpin_markets", "bitpin_book", "bitpin_trades")
EXCHANGES = {"Nobitex": "نوبیتکس", "Wallex": "والکس", "Tabdeal": "تبدیل",
             "Ramzinex": "رمزینکس", "Raastin": "راستین", "Exir": "اکسیر", "Bitpin": "بیت پین"}
CLIENT_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIB3v+yxXk89AImiTB5Am0R1yfDdmw6mXzylsPyb91dqw"
HOST_LINE = "139.162.186.28 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEnTEGelzvtZGAbgDtRPDBEDpre/9+Gx+ubQC4jJHCrO"


def utc(epoch=None):
    return datetime.fromtimestamp(time.time() if epoch is None else epoch, timezone.utc).isoformat()


def epoch(value):
    try:
        result = float(Decimal(str(value)))
    except (InvalidOperation, ValueError, TypeError):
        result = None
    if result is not None:
        if not math.isfinite(result):
            raise ValueError("non-finite timestamp")
        return result / 1000 if result > 100_000_000_000 else result
    stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("timestamp has no timezone")
    return stamp.timestamp()


def positive(value):
    try:
        value = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("non-numeric price or quantity") from exc
    if not value.is_finite() or value <= 0:
        raise ValueError("non-positive or non-finite price or quantity")
    return value


def median(values):
    values = sorted(values)
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2


def book(rows, divisor, *, dictionaries=False):
    if not isinstance(rows, list) or not rows:
        raise ValueError("empty book side")
    result = []
    for row in rows:
        price, quantity = (row["price"], row["amount"]) if dictionaries else row[:2]
        # Zero-quantity levels are not executable. Other malformed levels fail the source.
        qty = Decimal(str(quantity))
        if qty == 0:
            continue
        result.append((positive(price) / divisor, positive(qty)))
    if not result:
        raise ValueError("book side has no positive liquidity")
    return sorted(result)


def http_live(headers, observed):
    """A conservative cache check, distinct from a book timestamp check."""
    try:
        age = Decimal(str(headers.get("age", "0")))
        date = parsedate_to_datetime(headers["date"]).timestamp()
        return age.is_finite() and 0 <= age <= 2 and -5 <= observed - date <= 15
    except (ValueError, TypeError, KeyError, OverflowError, InvalidOperation):
        return False


def normalise(name, response, extras, *, now=None):
    now = time.time() if now is None else now
    observed = epoch(response["observed_at_utc"])
    if not -5 <= now - observed <= 30:
        raise ValueError("transport observation is old or in the future")
    raw = response["data"]
    def extra(selector):
        item = extras[selector]
        if not -5 <= now - epoch(item["observed_at_utc"]) <= 30:
            raise ValueError("market-state observation is old or in the future")
        return item["data"]
    def recent_trade(rows, stamp_key, price_key, quantity_key):
        if not isinstance(rows, list) or not rows:
            raise ValueError("no public trade evidence")
        times = []
        for trade in rows:
            positive(trade[price_key])
            positive(trade[quantity_key])
            times.append(epoch(trade[stamp_key]))
        if not -5 <= now - max(times) <= MAX_AGE:
            raise ValueError("latest public trade is stale or in the future")
    source_time = None
    evidence = {}
    liquidity_basis = "order-book levels"
    market_state = "depth endpoint provides no explicit market-state flag"
    if name == "Nobitex":
        if raw.get("status") != "ok":
            raise ValueError("Nobitex API status is not ok")
        m = raw["USDTIRT"]
        stats_response = extra("nobitex_stats")
        if stats_response.get("status") != "ok":
            raise ValueError("Nobitex market-state request is unavailable")
        stats = stats_response.get("stats", {}).get("usdt-rls", {})
        if not isinstance(stats, dict) or not stats:
            raise ValueError("Nobitex market-state row is unavailable")
        if stats.get("isClosed") is not False:
            raise ValueError("Nobitex market is closed")
        market_state = "explicitly open" if stats.get("isClosed") is False else "market-state response supplies no closure flag"
        bids, asks = book(m["bids"], Decimal(10)), book(m["asks"], Decimal(10))
        source_time = epoch(m["lastUpdate"])
    elif name == "Wallex":
        if raw.get("success") is not True:
            raise ValueError("Wallex API status is not successful")
        m = raw["result"]["symbols"]["USDTTMN"]
        if m.get("isMarketTypeEnable") is not True:
            raise ValueError("Wallex market is disabled or its state is unknown")
        if m.get("quoteAsset") not in (None, "TMN"):
            raise ValueError("Wallex quote currency is not TMN")
        market_state = "market enabled"
        stats = m["stats"]
        depth = extra("wallex_depth")
        if depth.get("success") is not True:
            raise ValueError("Wallex order book is unavailable")
        def wallex_levels(side):
            return [[row["price"], row["quantity"]] for row in depth["result"][side]]
        bids, asks = book(wallex_levels("bid"), Decimal(1)), book(wallex_levels("ask"), Decimal(1))
        if abs(asks[0][0]/positive(stats["askPrice"])-1) > Decimal("0.0025") or abs(bids[-1][0]/positive(stats["bidPrice"])-1) > Decimal("0.0025"):
            raise ValueError("Wallex market statistics and executable book disagree")
        trades = extra("wallex_trades")
        if trades.get("success") is not True:
            raise ValueError("Wallex public-trade request failed")
        rows = trades["result"]["latestTrades"]
        if any(row.get("symbol") != "USDTTMN" for row in rows):
            raise ValueError("Wallex public trade symbol mismatch")
        recent_trade(rows, "timestamp", "price", "quantity")
        market_state = "enabled market with public trades inside the freshness window"
    elif name == "Tabdeal":
        bids, asks = book(raw["bids"], Decimal(1)), book(raw["asks"], Decimal(1))
        recent_trade(extra("tabdeal_trades"), "time", "price", "qty")
        market_state = "recent public trades inside the freshness window; explicit state endpoint unavailable"
    elif name == "Ramzinex":
        if raw.get("status") != 0:
            raise ValueError("Ramzinex API status is not successful")
        pair_data = extra("ramzinex_pairs")
        if pair_data.get("status") != 0:
            raise ValueError("Ramzinex pair-state response failed or is unavailable")
        rows = [r for r in pair_data.get("data", []) if str(r.get("pair_id")) == "11"]
        if not rows:
            raise ValueError("Ramzinex pair 11 is absent from market metadata")
        if rows[0].get("is_delist") or rows[0].get("is_temporarily_suspended"):
            raise ValueError("Ramzinex pair is delisted or suspended")
        def symbol(value):
            return str(value.get("en", "") if isinstance(value, dict) else value).lower()
        if symbol(rows[0].get("base_currency_symbol")) != "usdt" or symbol(rows[0].get("quote_currency_symbol")) != "irr":
            raise ValueError("Ramzinex pair 11 is not USDT/IRR")
        market_state = "pair metadata reports no delisting or suspension"
        bids = book(raw["data"]["buys"], Decimal(10))
        asks = book(raw["data"]["sells"], Decimal(10))
    elif name == "Raastin":
        states = extra("raastin_state")
        rows = [m for m in states if m.get("name") == "USDTIRT"]
        if len(rows) != 1:
            raise ValueError("Raastin market state is absent or ambiguous")
        state = rows[0]
        if state.get("enable") is not True or state.get("order_disable") is not False or state.get("order_paused") is not False:
            raise ValueError("Raastin orders are disabled, paused, or their state is unknown")
        if state.get("asset", {}).get("symbol") != "USDT" or state.get("base_asset", {}).get("symbol") != "IRT":
            raise ValueError("Raastin market units mismatch")
        market_state = "enabled market; order_disable=false; order_paused=false"
        bids = book(raw["bids"], Decimal(1), dictionaries=True)
        asks = book(raw["asks"], Decimal(1), dictionaries=True)
    elif name == "Bitpin":
        states = extra("bitpin_markets")
        if not isinstance(states, list):
            raise ValueError("Bitpin markets response is not a list")
        rows = [row for row in states if row.get("symbol") == "USDT_IRT"]
        if len(rows) != 1:
            raise ValueError("Bitpin market is absent or ambiguous")
        state = rows[0]
        if state.get("base") != "USDT" or state.get("quote") != "IRT":
            raise ValueError("Bitpin market units mismatch")
        if state.get("tradable") is not True or state.get("suspended") is not False:
            raise ValueError("Bitpin market is disabled, suspended, or unknown")
        # IRT is toman, never divide this venue's prices by ten.
        bids, asks = book(raw["bids"], Decimal(1)), book(raw["asks"], Decimal(1))
        trades = extra("bitpin_trades")
        recent_trade(trades, "time", "price", "base_amount")
        trade_response = extras["bitpin_trades"]
        if not http_live(trade_response.get("response_headers", {}), epoch(trade_response["observed_at_utc"])):
            raise ValueError("Bitpin trade HTTP freshness is unconfirmed")
        latest_trade = max(epoch(trade["time"]) for trade in trades)
        market_response = extras["bitpin_markets"]
        headers = market_response.get("response_headers", {})
        market_observed = epoch(market_response["observed_at_utc"])
        age = Decimal(str(headers.get("age", "0")))
        date = parsedate_to_datetime(headers["date"]).timestamp()
        # Market metadata has a documented/observed 60-second cache, unlike books.
        if not age.is_finite() or not 0 <= age <= 60 or not -5 <= market_observed-date <= 15:
            raise ValueError("Bitpin market metadata HTTP freshness is unconfirmed")
        market_proof = min(market_observed, date) - float(age)
        if not -5 <= now-market_proof <= MAX_AGE:
            raise ValueError("Bitpin market-state proof is stale or in the future")
        evidence = {"market_state_proof_utc": utc(market_proof),
                    "latest_trade_utc": utc(latest_trade)}
        market_state = "USDT/IRT tradable=true; suspended=false; recent public trade"
    elif name == "Exir":
        state = extra("exir_state")["pairs"]["usdt-irt"]
        status = str(state.get("status", "")).strip().lower()
        breaker = state.get("circuit_breaker")
        # HollaEx "full" allows trading; circuit_breaker configures price protection.
        # It does not by itself report a currently halted market.
        full_trading = status == "full" and type(breaker) is bool
        legacy_trading = status in {"active", "open", "trading"} and breaker is False
        if state.get("active") is not True or not (full_trading or legacy_trading):
            raise ValueError("Exir market is paused, cancel-only, or not confirmed executable")
        market_state = ("full trading market; circuit breaker configured=" + str(breaker).lower()
                        if full_trading else "active trading market; circuit_breaker=false")
        m = raw.get("usdt-irt", raw)
        bids, asks = book(m["bids"], Decimal(1)), book(m["asks"], Decimal(1))
        source_time = epoch(m["timestamp"])
    else:
        raise ValueError("unknown exchange")
    bid, bid_qty = bids[-1]
    ask, ask_qty = asks[0]
    if bid >= ask:
        raise ValueError("crossed or locked order book")
    if (ask - bid) / ask > Decimal("0.02"):
        raise ValueError("spread exceeds conservative 2% safety limit")
    if source_time is not None and not -5 <= now - source_time <= MAX_AGE:
        raise ValueError("exchange book timestamp is stale or in the future")
    fingerprint = hashlib.sha256(json.dumps([bids, asks], default=str, separators=(",", ":")).encode()).hexdigest()
    headers = response.get("response_headers", {})
    return {"provider": name, "exchange": EXCHANGES[name],
            "buy_toman": str(ask), "sell_toman": str(bid),
            "buy_quantity": str(ask_qty),
            "sell_quantity": str(bid_qty),
            "aggregate_ask_volume": None,
            "aggregate_bid_volume": None,
            "liquidity_basis": liquidity_basis,
            "market_state": market_state, "market_open": True,
            "observed_at_utc": utc(observed),
            "exchange_timestamp": utc(source_time) if source_time is not None else None,
            "freshness_upper_bound_utc": utc(source_time) if source_time is not None else None,
            "freshness_basis": "exchange_timestamp" if source_time is not None else "unconfirmed",
            "book_hash": fingerprint, "http_live": http_live(headers, observed),
            "response_headers": headers,
            "transport_route": response.get('transport_route', 'akamai-restricted-ssh'), **evidence}


class Transport:
    def __init__(self):
        folder = Path("/home/kianirad2020/.ssh")
        key = folder / "kiani_akamai_rates_ed25519"
        known = folder / "kiani_akamai_rates_known_hosts"
        if key.is_symlink() or known.is_symlink() or known.read_text().strip() != HOST_LINE:
            raise ValueError("SSH host pin or key path is invalid")
        public = subprocess.check_output(["ssh-keygen", "-y", "-P", "", "-f", str(key)], text=True, timeout=5)
        if " ".join(public.split()[:2]) != CLIENT_KEY:
            raise ValueError("SSH client identity does not match")
        self.command = ["ssh", "-F", "/dev/null", "-T", "-o", "BatchMode=yes",
                        "-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={known}",
                        "-o", "GlobalKnownHostsFile=/dev/null", "-o", "IdentitiesOnly=yes",
                        "-o", "ConnectTimeout=5", "-i", str(key), f"root@{HOST}"]

    def fetch(self, selector):
        try:
            return self._fetch_primary(selector)
        except (RuntimeError, subprocess.TimeoutExpired, OSError) as primary_error:
            if selector == 'health':
                raise
            from google_rate_fallback import fetch as fetch_google
            try:
                return fetch_google(selector)
            except Exception:
                # Retain the primary timeout marker for bounded-age reuse rules.
                raise primary_error

    def _fetch_primary(self, selector):
        if selector not in SELECTORS and selector != "health":
            raise ValueError("unsupported selector")
        if selector in ("nobitex_book", "nobitex_stats"):
            # The fixed stream endpoint already rejects old observations. REST
            # remains available when the stream is disconnected or has no update.
            try:
                live_selector = "nobitex_live" if selector == "nobitex_book" else "nobitex_live_stats"
                r = subprocess.run(self.command + [live_selector], capture_output=True,
                                   text=True, timeout=5)
                data = json.loads(r.stdout)
                if (r.returncode == 0 and data.get("protocol") == 1 and data.get("ok") is True
                        and data.get("selector") == live_selector
                        and -5 <= time.time() - epoch(data["observed_at_utc"]) <= 20):
                    data["selector"] = selector
                    return data
            except (ValueError, KeyError, subprocess.TimeoutExpired):
                pass
        r = subprocess.run(self.command + [selector], capture_output=True, text=True, timeout=20)
        if r.returncode:
            raise RuntimeError((r.stderr.strip() or r.stdout.strip() or "SSH failed")[:250])
        data = json.loads(r.stdout)
        if data.get("protocol") != 1 or data.get("ok") is not True:
            raise ValueError("transport rejected request")
        if selector != "health" and data.get("selector") != selector:
            raise ValueError("transport response selector mismatch")
        if not -5 <= time.time() - epoch(data["observed_at_utc"]) <= 30:
            raise ValueError("transport clock or response age is invalid")
        return data


class Collector:
    def __init__(self, transport, seed_quotes=None):
        self.transport = transport
        self.previous = {q["provider"]: dict(q) for q in (seed_quotes or [])}
        self.last_accepted = {q["provider"]: dict(q) for q in (seed_quotes or [])}

    def _quote_after_timeout(self, name, selectors, replies, errors, now):
        # These two venues have explicit market-state checks and currently
        # provide the display quorum. Never reuse a quote after a semantic failure.
        if name not in {"Nobitex", "Ramzinex"}:
            return None
        failure = errors.get(selectors[0], "")
        if not any(marker in failure for marker in ("curl failed (exit 28)", "TimeoutExpired", "timed out")):
            return None
        previous = self.last_accepted.get(name)
        if not previous or previous.get("eligible") is not True or previous.get("market_open") is not True:
            return None
        proof = previous.get("freshness_upper_bound_utc")
        if proof is None:
            return None
        age = now - epoch(proof)
        if not 0 <= age < MAX_AGE:
            return None
        state_selector = "nobitex_stats" if name == "Nobitex" else "ramzinex_pairs"
        state_response = replies.get(state_selector)
        if not state_response or not -5 <= now - epoch(state_response["observed_at_utc"]) <= 30:
            return None
        state = state_response["data"]
        if name == "Nobitex":
            if state.get("status") != "ok" or state.get("stats", {}).get("usdt-rls", {}).get("isClosed") is not False:
                return None
        else:
            rows = [r for r in state.get("data", []) if str(r.get("pair_id")) == "11"]
            if state.get("status") != 0 or len(rows) != 1:
                return None
            pair = rows[0]
            if pair.get("is_delist") or pair.get("is_temporarily_suspended"):
                return None
            def symbol(value):
                return str(value.get("en", "") if isinstance(value, dict) else value).lower()
            if symbol(pair.get("base_currency_symbol")) != "usdt" or symbol(pair.get("quote_currency_symbol")) != "irr":
                return None
        # Preserve all original observation, trade and freshness timestamps.
        # Snapshot expiry below still uses the original proof + MAX_AGE.
        quote = dict(previous)
        quote.update(cached_after_timeout=True, transport_error=failure,
                     age_upper_bound_seconds=round(age, 3))
        quote.pop("book_changed_since_previous_poll", None)
        return quote

    def collect(self, replies=None, errors=None):
        supplied_replies = replies is not None
        replies, errors = (dict(replies), dict(errors or {})) if supplied_replies else ({}, {})
        def safe(selector):
            try:
                return selector, self.transport.fetch(selector), None
            except Exception as exc:
                return selector, None, f"{type(exc).__name__}: {str(exc)[:220]}"
        if not supplied_replies:
            with ThreadPoolExecutor(max_workers=4) as pool:
                for selector, reply, error in pool.map(safe, SELECTORS):
                    if error:
                        errors[selector] = error
                    else:
                        replies[selector] = reply
        choices = {"Nobitex": ("nobitex_book",), "Wallex": ("wallex_markets",),
                   "Tabdeal": ("tabdeal_depth",), "Ramzinex": ("ramzinex_book",),
                   "Raastin": ("raastin_depth",), "Exir": ("exir_book", "exir_books"),
                   "Bitpin": ("bitpin_book",)}
        candidates, diagnostics = [], []
        now = time.time()
        for name, selectors in choices.items():
            reasons = []
            quote = None
            for selector in selectors:
                try:
                    quote = normalise(name, replies[selector], replies, now=now)
                    quote["endpoint_selector"] = selector
                    break
                except Exception as exc:
                    reasons.append(f"{selector}: {errors.get(selector, str(exc))}")
            if quote is None:
                try:
                    cached = self._quote_after_timeout(name, selectors, replies, errors, now)
                except (ValueError, TypeError, KeyError, AttributeError, InvalidOperation):
                    cached = None
                if cached is not None:
                    self.previous[name] = dict(cached)
                    diagnostics.append(cached)
                    candidates.append(cached)
                    continue
                diagnostics.append({"provider": name, "eligible": False, "error": "; ".join(reasons)})
                self.previous.pop(name, None)
                continue
            previous = self.previous.get(name)
            changed = bool(previous and previous["book_hash"] != quote["book_hash"])
            quote["book_changed_since_previous_poll"] = changed
            if quote["exchange_timestamp"] is None:
                if quote["http_live"] and previous and previous["http_live"]:
                    if changed:
                        # This is an observed-change interval bound, not an exchange timestamp.
                        quote["freshness_upper_bound_utc"] = previous["observed_at_utc"]
                        quote["freshness_basis"] = "http_cache_checks+observed_book_change"
                    elif previous.get("freshness_basis") == "http_cache_checks+observed_book_change":
                        quote["freshness_upper_bound_utc"] = previous["freshness_upper_bound_utc"]
                        quote["freshness_basis"] = previous["freshness_basis"]
            if name == "Bitpin" and quote["freshness_upper_bound_utc"] is not None:
                # Trade time is an extra cap, not an order-book timestamp.
                quote["freshness_upper_bound_utc"] = utc(min(
                    epoch(quote["freshness_upper_bound_utc"]),
                    epoch(quote["market_state_proof_utc"]), epoch(quote["latest_trade_utc"])))
            proof = quote["freshness_upper_bound_utc"]
            age = now - epoch(proof) if proof is not None else None
            eligible = age is not None and -5 <= age <= MAX_AGE
            if quote["exchange_timestamp"] is None and not quote["http_live"]:
                eligible = False
            quote["age_upper_bound_seconds"] = round(max(0.0, age), 3) if age is not None else None
            quote["eligible"] = eligible
            if not eligible:
                quote["error"] = "freshness not established; receipt time alone is insufficient"
            if reasons:
                quote["alternate_endpoint_errors"] = reasons
            self.previous[name] = dict(quote)
            diagnostics.append(quote)
            if eligible:
                candidates.append(quote)
        if len(candidates) >= 3:
            centre = median([positive(q["buy_toman"]) for q in candidates])
            accepted = []
            for quote in candidates:
                if centre * Decimal("0.92") <= positive(quote["buy_toman"]) <= centre * Decimal("1.08"):
                    accepted.append(quote)
                else:
                    quote["eligible"] = False
                    quote["error"] = "outside existing 8% buy-price median tolerance"
            candidates = accepted
        self.last_accepted = {q["provider"]: dict(q) for q in candidates}
        ok = MIN_SOURCES <= len(candidates) <= 7 and sources_agree(candidates)
        expires = min((epoch(q["freshness_upper_bound_utc"]) + MAX_AGE for q in candidates), default=now)
        return {"schema_version": 2, "transport": "akamai-restricted-ssh", "ok": ok,
                "generated_at_utc": utc(now), "valid_until_utc": utc(expires),
                "source_count": len(candidates), "minimum_sources": MIN_SOURCES,
                "median_buy_toman": str(median([positive(q["buy_toman"]) for q in candidates])) if ok else None,
                "quotes": candidates, "diagnostics": diagnostics, "transport_errors": errors}


def save(path, data, *, public=False):
    path = Path(path)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False, encoding="utf-8") as stream:
        temp = Path(stream.name)
        try:
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), 0o644 if public else 0o600)
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
    os.replace(temp, path)


def production_context():
    """Print only relevant code/configuration, redacting credential values."""
    def redact(text):
        text = re.sub(r'(?i)((?:https?|socks5h?)://)[^/\s@]+@', r'\1<REDACTED>@', text)
        text = re.sub(r'\b\d{6,12}:[A-Za-z0-9_-]{25,}\b', '<REDACTED_BOT_TOKEN>', text)
        text = re.sub(r'(?im)^(\s*[A-Z_]*(?:TOKEN|PASSWORD|SECRET|API_KEY)[A-Z_]*\s*=).*$', r'\1 "<REDACTED>"', text)
        text = re.sub(r'(?i)(--(?:password|token|api-key)[=\s]+)\S+', r'\1<REDACTED>', text)
        return text
    repo = Path("/home/kianirad2020/telegram_bot_repo")
    for rel in ("shahidi-exchange/kiani-exchange/backend/app/price_cache.py",
                "shahidi-exchange/kiani-exchange/backend/app/api/rates.py",
                "shahidi-exchange/kiani-exchange/backend/app/main.py"):
        path = repo / rel
        print("CONTEXT FILE:", rel, flush=True)
        if not path.is_file():
            print("NOT FOUND", flush=True)
            continue
        source = path.read_text()
        # Proxy host inventories add hundreds of irrelevant lines.
        try:
            tree = ast.parse(source)
            lines = source.splitlines()
            for node in sorted(tree.body, key=lambda n: n.lineno, reverse=True):
                if isinstance(node, ast.Assign) and isinstance(node.value, (ast.List, ast.Tuple)):
                    if len(node.value.elts) > 12:
                        lines[node.lineno - 1:node.end_lineno] = ["# Large literal inventory omitted from diagnostic output."]
            source = "\n".join(lines)
        except SyntaxError:
            pass
        print(redact(source), flush=True)
    print("RELEVANT SUPERVISOR CONFIGURATION", flush=True)
    for path in sorted(Path("/etc/supervisor/conf.d").glob("*.conf")):
        try:
            config = configparser.ConfigParser(interpolation=None)
            config.read(path)
            for section in config.sections():
                if any(part in section.lower() for part in ("kiani", "shahidi", "main_user")):
                    print("CONFIG:", path, section, flush=True)
                    for key in ("command", "directory", "user", "autostart"):
                        if config.has_option(section, key):
                            print(key + "=" + redact(config.get(section, key)), flush=True)
        except (OSError, configparser.Error):
            print("CONFIG UNREADABLE:", path, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--audit", action="store_true")
    action.add_argument("--serve", metavar="SNAPSHOT_PATH")
    parser.add_argument("--context", action="store_true", help="Print redacted Shahidi code and relevant service configuration")
    args = parser.parse_args()
    if args.context:
        production_context()
    transport = Transport()
    try:
        health = transport.fetch("health")
    except (RuntimeError, subprocess.TimeoutExpired, OSError) as exc:
        # An unavailable primary host must not prevent the independent public
        # Google route from being tried. SSH identity/host pins remain enforced.
        health = None
        print(json.dumps({'primary_health_unavailable': type(exc).__name__}), flush=True)
    if health is not None:
        if health.get("effective_uid", 0) == 0:
            raise SystemExit("Bridge privilege-drop check failed")
        print(json.dumps({"transport_health": health}), flush=True)
    seed_quotes = []
    if args.serve:
        try:
            from akamai_rate_feed import read_display_feed
            seed_quotes = read_display_feed()["quotes"]
        except Exception:
            pass
    collector = Collector(transport, seed_quotes=seed_quotes)
    if args.serve:
        from resilient_runtime import serve
        return serve(collector, args.serve, save, SELECTORS)
    rounds = []
    index = 0
    while True:
        snapshot = collector.collect()
        if args.serve:
            save(args.serve, snapshot, public=True)
        else:
            rounds.append(snapshot)
            save("/tmp/kiani-akamai-audit.json", {"rounds": rounds})
        index += 1
        print(json.dumps({"poll": index, "source_count": snapshot["source_count"],
                          "cached_sources": [q["provider"] for q in snapshot["quotes"] if q.get("cached_after_timeout")],
                          "quorum": snapshot["ok"], "median_buy_toman": snapshot["median_buy_toman"]}), flush=True)
        if args.audit:
            for quote in snapshot["diagnostics"]:
                print(json.dumps(quote, ensure_ascii=False), flush=True)
        if not args.serve and index >= 3:
            print("Full audit: /tmp/kiani-akamai-audit.json", flush=True)
            return 0 if snapshot["ok"] else 2
        time.sleep(8)


if __name__ == "__main__":
    raise SystemExit(main())
