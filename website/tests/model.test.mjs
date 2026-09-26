import test from "node:test";
import assert from "node:assert/strict";
import {
  CATEGORY_META, bestQuote, changeBetween, chartObservations, cheapestAsk, formatPrice, freshness, isFresh,
  normalizeQuotes, observationSegments, quoteUnit, relativeAge, searchKey, sortQuotes,
} from "../dist/model.js";

const verified = (extra = {}) => ({
  series_id: "digest:crypto:btc:usd:reference:v1",
  instrument_id: "crypto:btc", category: "crypto_global",
  base_asset: "BTC", base_quantity: "1", quote_currency: "USD",
  collected_at: "2026-09-25T12:00:00+00:00",
  verification_status: "verified", source_family: "telegram_verified_history",
  freshness_status: "fresh", reference: "84455.10", ...extra,
});

test("quotes reject sample, unverified, invalid, and nondecimal values", () => {
  const values = normalizeQuotes({
    schema_version: "1",
    quotes: [
      verified(),
      verified({ series_id: "sample", source_family: "sample" }),
      verified({ series_id: "unverified", verification_status: "unverified" }),
      verified({ series_id: "published", verification_status: "source_published", source_id: "tomanify:rate-json-default" }),
      verified({ series_id: "invalid", reference: "NaN" }),
    ],
  });
  assert.equal(values.length, 2);
  assert.deepEqual(values.map((quote) => quote.series_id), [verified().series_id, "published"]);
  assert.throws(() => normalizeQuotes({ quotes: [] }));
});

test("fresh quotes are selected ahead of newer stale observations", () => {
  const fresh = verified({ series_id: "fresh", category: "iran_fx" });
  const stale = verified({
    series_id: "stale", freshness_status: "stale", category: "iran_fx",
    collected_at: "2026-09-25T13:00:00+00:00",
  });
  assert.equal(bestQuote([stale, fresh], () => true), fresh);
  assert.equal(isFresh(fresh, false), false);
});

test("history uses only actual verified observations", () => {
  const points = chartObservations({
    sampling_kind: "verified_publisher_observations",
    points: [
      { quote: verified({ collected_at: "2026-09-25T13:00:00+00:00", reference: "84000" }) },
      { quote: verified({ collected_at: "2026-09-25T12:00:00+00:00", reference: "83000" }) },
      { quote: verified({ source_family: "sample" }) },
    ],
  });
  assert.deepEqual(points.map((point) => point.value), [83000, 84000]);
  assert.throws(() => chartObservations({ sampling_kind: "interpolated", points: [] }));
});

test("chart accepts archived published-source snapshots without claiming verification", () => {
  const sourceQuote = verified({
    verification_status: "source_published", source_family: "public_market_provider",
    collected_at: "2026-09-25T12:00:00+00:00", reference: "235200",
  });
  const points = chartObservations({
    sampling_kind: "published_source_observations",
    points: [{ quote: sourceQuote }],
  });
  assert.deepEqual(points.map((point) => point.value), [235200]);
});

test("units and decimal precision remain explicit", () => {
  assert.equal(formatPrice(verified(), "84455.10"), "84,455.10");
  assert.equal(formatPrice(verified(), "0.00000582"), "0.00000582");
  assert.equal(formatPrice(verified(), "0.000000000012"), "0.000000000012");
  assert.equal(quoteUnit(verified({
    base_asset: "IQD", base_quantity: "100", quote_currency: "TOMAN",
  })), "تومان برای ۱۰۰ واحد");
});

const HOUR = 3600 * 1000;

test("daily digest series stay current for a day; customer prices expire at valid_until", () => {
  assert.equal(CATEGORY_META.crypto_global.dailyDigest, true);
  const published = Date.parse("2026-09-25T12:00:00+00:00");
  const digest = verified({ category: "daily_fx", freshness_status: "stale" });
  assert.equal(freshness(digest, published + 20 * HOUR), "fresh");
  assert.equal(freshness(digest, published + 27 * HOUR), "stale");
  assert.equal(freshness(digest, published + HOUR, false), "stale");
  const hawala = verified({ category: "kiani_hawala", valid_until: "2026-09-25T12:15:00+00:00" });
  assert.equal(freshness(hawala, published + 10 * 60000), "fresh");
  assert.equal(freshness(hawala, published + 16 * 60000), "expired");
  const intraday = verified({ category: "iran_fx", freshness_status: "stale" });
  assert.equal(freshness(intraday, published), "stale");
  assert.equal(isFresh(verified({ category: "iran_fx" })), true);
});

test("charts break at unusually long gaps instead of drawing through them", () => {
  const t = (h) => ({ time: h * HOUR, value: 1 });
  const segments = observationSegments([t(0), t(2), t(4), t(6), t(30), t(32)]);
  assert.deepEqual(segments.map((s) => s.length), [4, 2]);
  assert.deepEqual(observationSegments([t(0)]).map((s) => s.length), [1]);
  assert.deepEqual(observationSegments([]), []);
});

test("changes compare two real observations only", () => {
  const change = changeBetween({ time: 1, value: 100 }, { time: 2, value: 101 });
  assert.equal(change.direction, "up");
  assert.ok(Math.abs(change.pct - 1) < 1e-9);
  assert.equal(changeBetween(null, { time: 2, value: 1 }), null);
  assert.equal(changeBetween({ time: 2, value: 1 }, { time: 2, value: 1 }), null);
});

test("cheapest ask ignores stale exchanges when fresh ones exist", () => {
  const ex = (id, ask, status) => verified({
    series_id: id, category: "usdt_exchange", reference: null, ask, freshness_status: status,
  });
  const pick = cheapestAsk([ex("a", "104100", "fresh"), ex("b", "103000", "stale"), ex("c", "104050", "fresh")], () => true);
  assert.equal(pick.quote.series_id, "c");
  assert.equal(pick.count, 2);
  assert.equal(pick.allStale, false);
  assert.equal(sortQuotes("usdt_exchange", [ex("a", "104100", "fresh"), ex("c", "104050", "fresh")])[0].series_id, "c");
});

test("two-sided history can be read per side", () => {
  const payload = {
    sampling_kind: "verified_publisher_observations",
    points: [{ quote: verified({ reference: null, bid: "41.30", ask: "41.35" }) }],
  };
  assert.equal(chartObservations(payload, "bid")[0].raw, "41.30");
  assert.equal(chartObservations(payload, "ask")[0].raw, "41.35");
  assert.equal(chartObservations(payload)[0].raw, "41.35");
});

test("search ignores Arabic letter variants and ZWNJ; ages read naturally", () => {
  assert.equal(searchKey("كويت ترك"), searchKey("کویت‌ترک"));
  assert.equal(relativeAge(0, 30 * 1000), "همین حالا");
  assert.equal(relativeAge(0, 5 * 60000), "۵ دقیقه پیش");
  assert.equal(relativeAge(0, 3 * HOUR), "۳ ساعت پیش");
});

test("well-known instruments sort first", () => {
  const fx = (base) => verified({ category: "iran_fx", base_asset: base, instrument_id: `fx:${base.toLowerCase()}`, display_name_fa: base });
  assert.deepEqual(sortQuotes("iran_fx", [fx("AFN"), fx("EUR"), fx("USD")]).map((q) => q.base_asset), ["USD", "EUR", "AFN"]);
});

