import test from "node:test";
import assert from "node:assert/strict";
import {
  bestQuote, chartObservations, formatPrice, isFresh, normalizeQuotes, quoteUnit,
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
      verified({ series_id: "invalid", reference: "NaN" }),
    ],
  });
  assert.equal(values.length, 1);
  assert.equal(values[0].series_id, verified().series_id);
  assert.throws(() => normalizeQuotes({ quotes: [] }));
});

test("fresh quotes are selected ahead of newer stale observations", () => {
  const fresh = verified({ series_id: "fresh" });
  const stale = verified({
    series_id: "stale", freshness_status: "stale",
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

test("units and decimal precision remain explicit", () => {
  assert.equal(formatPrice(verified(), "84455.10"), "84,455.10");
  assert.equal(formatPrice(verified(), "0.00000582"), "0.00000582");
  assert.equal(quoteUnit(verified({
    base_asset: "IQD", base_quantity: "100", quote_currency: "TOMAN",
  })), "تومان برای ۱۰۰ واحد");
});
