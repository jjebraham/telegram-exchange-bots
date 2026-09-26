// Pure data helpers. No DOM access here so everything stays unit-testable.

// kind decides the table layout and the label shown to visitors:
//   reference  – a published market rate, not a price anyone will trade with you at
//   two_sided  – separate buy (bid) and sell (ask) prices of a bank or market
//   ask_only   – the price a customer pays to buy on an exchange
//   customer   – a Kiani customer price that expires at valid_until
// dailyDigest marks series published once a day, so "old" means older than a day.
export const CATEGORY_META = {
  iran_fx: { title: "ارز آزاد ایران", kind: "reference", family: "iran", note: "نرخ مرجع بازار آزاد، به تومان" },
  iran_gold: { title: "طلا و سکهٔ ایران", kind: "reference", family: "iran", note: "نرخ مرجع، به تومان" },
  usdt_exchange: { title: "تتر در صرافی‌های ایران", kind: "ask_only", family: "crypto", note: "قیمتی که برای خرید هر تتر می‌پردازید، به تومان" },
  turkey_fx: { title: "دلار و یورو در ترکیه", kind: "two_sided", family: "turkey", note: "خرید و فروش بانک‌ها و بازار، به لیر" },
  turkey_gold: { title: "طلای ترکیه", kind: "two_sided", family: "turkey", note: "خرید و فروش، به لیر" },
  kiani_hawala: { title: "حوالهٔ صرافی کیانی", kind: "customer", family: "iran", note: "قیمت مشتری با زمان اعتبار، به تومان" },
  crypto_global: { title: "رمزارزها در بازار جهانی", kind: "reference", family: "crypto", note: "نرخ مرجع، به دلار · روزانه", dailyDigest: true },
  daily_fx: { title: "خلاصهٔ روز: ارز", kind: "reference", family: "digest", note: "نرخ مرجع منتشرشده در خلاصهٔ روزانه", dailyDigest: true },
  daily_gold: { title: "خلاصهٔ روز: طلا", kind: "reference", family: "digest", note: "نرخ مرجع منتشرشده در خلاصهٔ روزانه", dailyDigest: true },
};

export const CATEGORY_ORDER = Object.keys(CATEGORY_META);
const DAILY_STALE_AFTER_MS = 26 * 3600 * 1000;

// Most-asked instruments first; anything unlisted falls back to Persian alphabetical order.
const PRIORITY = [
  "USD", "USDT", "EUR", "TRY", "AED", "GBP", "CAD", "AUD", "CNY", "CHF", "IQD", "SEK", "NOK", "DKK",
  "RUB", "AZN", "THB", "SGD", "HKD", "SAR", "KWD", "BHD", "OMR", "QAR", "INR", "MYR", "AFN",
  "BTC", "ETH", "SOL", "BNB", "XRP", "TRX", "DOGE", "ADA", "GRAM", "NOT", "SHIB", "XAU",
];
const GOLD_PRIORITY = ["gold-18k", "gold18", "mithqal", "mesghal", "gram", "emami", "coin-emami",
  "bahar-azadi", "coin-azadi", "half", "coin-half", "quarter", "coin-quarter", "full", "gram-coin", "xauusd"];

function priorityOf(quote) {
  const slug = String(quote.instrument_id || "").split(":").pop();
  const gold = GOLD_PRIORITY.indexOf(slug);
  if (String(quote.instrument_id).includes("gold")) return gold === -1 ? 999 : gold;
  const index = PRIORITY.indexOf(quote.base_asset);
  return index === -1 ? 999 : index;
}

export function numericPrice(quote) {
  for (const key of ["reference", "ask", "bid"]) {
    const raw = quote?.[key];
    if (typeof raw !== "string" || !/^\d+(?:\.\d+)?$/.test(raw)) continue;
    const value = Number(raw);
    if (Number.isFinite(value) && value > 0) return { value, raw, kind: key };
  }
  return null;
}

export function normalizeQuotes(payload) {
  if (payload?.schema_version !== "1" || !Array.isArray(payload.quotes)) {
    throw new Error("پاسخ سامانهٔ نرخ‌ها معتبر نیست.");
  }
  return payload.quotes.filter((quote) =>
    quote && typeof quote === "object" &&
    ["verified", "source_published"].includes(quote.verification_status) &&
    quote.source_family !== "sample" &&
    typeof quote.series_id === "string" &&
    typeof quote.instrument_id === "string" &&
    typeof quote.category === "string" &&
    Number.isFinite(Date.parse(quote.collected_at)) &&
    numericPrice(quote)
  );
}

// Backend freshness uses one TTL for every series. Daily-digest series are only
// published once a day, so they get a day-long window here instead of always
// reading as "old". Customer prices follow their own valid_until.
export function freshness(quote, now = Date.now(), connected = true) {
  if (!quote) return "stale";
  const validUntil = Date.parse(quote.valid_until);
  if (Number.isFinite(validUntil)) return now > validUntil ? "expired" : connected ? "fresh" : "stale";
  if (!connected) return "stale";
  if (CATEGORY_META[quote.category]?.dailyDigest) {
    return now - Date.parse(quote.collected_at) <= DAILY_STALE_AFTER_MS ? "fresh" : "stale";
  }
  return quote.freshness_status === "fresh" ? "fresh" : "stale";
}

export function isFresh(quote, connected = true, now = Date.now()) {
  if (quote && !Number.isFinite(Date.parse(quote.valid_until)) && !CATEGORY_META[quote.category]?.dailyDigest) {
    return connected && quote.freshness_status === "fresh";
  }
  return freshness(quote, now, connected) === "fresh";
}

export function bestQuote(quotes, predicate, connected = true) {
  return quotes.filter(predicate).sort((a, b) => {
    const freshDifference = Number(isFresh(b, connected)) - Number(isFresh(a, connected));
    return freshDifference || Date.parse(b.collected_at) - Date.parse(a.collected_at);
  })[0] || null;
}

// Cheapest ask among exchanges. Only fresh quotes compete, so a days-old low price never wins.
export function cheapestAsk(quotes, predicate, connected = true) {
  const candidates = quotes.filter((q) => predicate(q) && typeof q.ask === "string");
  const fresh = candidates.filter((q) => isFresh(q, connected));
  const pool = fresh.length ? fresh : candidates;
  const sorted = [...pool].sort((a, b) => Number(a.ask) - Number(b.ask));
  return sorted.length ? { quote: sorted[0], count: pool.length, allStale: !fresh.length } : null;
}

export function sortQuotes(category, quotes) {
  const kind = CATEGORY_META[category]?.kind;
  return [...quotes].sort((a, b) => {
    if (kind === "ask_only") {
      const fresh = Number(isFresh(b)) - Number(isFresh(a));
      return fresh || Number(a.ask) - Number(b.ask);
    }
    const venueA = a.series_id.includes("kapalicarsi") ? 0 : 1;
    const venueB = b.series_id.includes("kapalicarsi") ? 0 : 1;
    return (priorityOf(a) - priorityOf(b)) || (venueA - venueB) ||
      (a.display_name_fa || "").localeCompare(b.display_name_fa || "", "fa");
  });
}

export function formatPrice(quote, raw) {
  if (typeof raw !== "string" || !/^\d+(?:\.\d+)?$/.test(raw)) return "—";
  const [integer, fractional = ""] = raw.split(".");
  let decimals = fractional.length;
  if (quote.quote_currency === "TRY") {
    decimals = Math.max(decimals, quote.category === "turkey_fx" ? 4 : 2);
  } else if (quote.quote_currency === "USD") {
    decimals = Number(raw) < 1 ? decimals : Math.max(decimals, 2);
  }
  const grouped = integer.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return decimals ? `${grouped}.${fractional.padEnd(decimals, "0")}` : grouped;
}

// field: optional "bid" or "ask" to chart one side of a two-sided market.
export function chartObservations(payload, field) {
  if (!new Set(["verified_publisher_observations", "published_source_observations"]).has(payload?.sampling_kind) ||
      !Array.isArray(payload.points)) {
    throw new Error("تاریخچهٔ نمودار معتبر نیست.");
  }
  return payload.points.flatMap((point) => {
    const quote = point?.quote;
    const price = field ? numericPrice({ [field]: quote?.[field] }) : numericPrice(quote);
    const time = Date.parse(quote?.collected_at);
    if (!["verified", "source_published"].includes(quote?.verification_status) || quote?.source_family === "sample" ||
        !price || !Number.isFinite(time)) return [];
    return [{ time, value: price.value, raw: price.raw }];
  }).sort((a, b) => a.time - b.time);
}

// Splits observations wherever the gap is much longer than the usual spacing, so the
// chart never draws a line through a period with no published rate.
export function observationSegments(points, minGapMs = 3600 * 1000) {
  if (points.length < 2) return points.length ? [points] : [];
  const gaps = points.slice(1).map((p, i) => p.time - points[i].time).sort((a, b) => a - b);
  const median = gaps[Math.floor(gaps.length / 2)];
  const limit = Math.max(minGapMs, median * 3);
  const segments = [[points[0]]];
  for (let i = 1; i < points.length; i += 1) {
    if (points[i].time - points[i - 1].time > limit) segments.push([]);
    segments[segments.length - 1].push(points[i]);
  }
  return segments;
}

// Percent change between two real observations. Returns null when there is nothing to compare.
export function changeBetween(from, to) {
  if (!from || !to || !(from.value > 0) || from.time === to.time) return null;
  const pct = (to.value - from.value) / from.value * 100;
  return { pct, direction: Math.abs(pct) < 0.005 ? "flat" : pct > 0 ? "up" : "down", from, to };
}

export function formatPercent(pct) {
  const abs = Math.abs(pct);
  const digits = abs >= 10 ? 1 : 2;
  return `${abs.toFixed(digits)}٪`;
}

export function relativeAge(time, now = Date.now()) {
  const minutes = Math.max(0, Math.floor((now - time) / 60000));
  const fa = (n) => n.toLocaleString("fa-IR");
  if (minutes < 1) return "همین حالا";
  if (minutes < 60) return `${fa(minutes)} دقیقه پیش`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${fa(hours)} ساعت پیش`;
  return `${fa(Math.round(hours / 24))} روز پیش`;
}

// Arabic-script variants, ZWNJ and spacing should not decide whether a search matches.
export function searchKey(text) {
  return String(text || "").toLocaleLowerCase()
    .replace(/ي/g, "ی").replace(/ك/g, "ک").replace(/[ةۀ]/g, "ه").replace(/[\u200c\s]+/g, "");
}

export function quoteUnit(quote) {
  const currency = { TOMAN: "تومان", TRY: "لیر", USD: "دلار" }[quote.quote_currency] || quote.quote_currency;
  if (quote.base_quantity === "100") return `${currency} برای ۱۰۰ واحد`;
  if (quote.unit === "gram-18k") return `${currency} برای هر گرم`;
  if (quote.unit === "mithqal") return `${currency} برای هر مثقال`;
  if (quote.unit === "troy-ounce") return `${currency} برای هر انس`;
  return currency;
}

export function currencyName(quote) {
  return { TOMAN: "تومان", TRY: "لیر", USD: "دلار" }[quote.quote_currency] || quote.quote_currency;
}

