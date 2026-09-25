export const CATEGORY_META = {
  iran_fx: { title: "ارز آزاد ایران", detail: "نرخ مرجع · تومان", family: "iran" },
  iran_gold: { title: "طلا و سکهٔ ایران", detail: "نرخ مرجع · تومان", family: "iran" },
  turkey_fx: { title: "ارز و بانک‌های ترکیه", detail: "خرید و فروش · لیر", family: "turkey" },
  turkey_gold: { title: "طلای ترکیه", detail: "خرید و فروش · لیر", family: "turkey" },
  usdt_exchange: { title: "تتر در صرافی‌ها", detail: "نرخ فروش · تومان", family: "crypto" },
  kiani_hawala: { title: "حوالهٔ کیانی", detail: "نرخ پرداختی · تومان", family: "iran" },
  daily_fx: { title: "خلاصهٔ روز · ارز", detail: "نرخ مرجع منتشرشده", family: "digest" },
  daily_gold: { title: "خلاصهٔ روز · طلا", detail: "نرخ مرجع منتشرشده", family: "digest" },
  crypto_global: { title: "رمزارزهای جهانی", detail: "نرخ مرجع · دلار", family: "crypto" },
};

export const CATEGORY_ORDER = Object.keys(CATEGORY_META);

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
    quote.verification_status === "verified" &&
    quote.source_family !== "sample" &&
    typeof quote.series_id === "string" &&
    typeof quote.instrument_id === "string" &&
    typeof quote.category === "string" &&
    Number.isFinite(Date.parse(quote.collected_at)) &&
    numericPrice(quote)
  );
}

export function isFresh(quote, connected = true) {
  return connected && quote?.freshness_status === "fresh";
}

export function bestQuote(quotes, predicate, connected = true) {
  return quotes.filter(predicate).sort((a, b) => {
    const freshDifference = Number(isFresh(b, connected)) - Number(isFresh(a, connected));
    return freshDifference || Date.parse(b.collected_at) - Date.parse(a.collected_at);
  })[0] || null;
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

export function chartObservations(payload) {
  if (payload?.sampling_kind !== "verified_publisher_observations" || !Array.isArray(payload.points)) {
    throw new Error("تاریخچهٔ نمودار معتبر نیست.");
  }
  return payload.points.flatMap((point) => {
    const quote = point?.quote;
    const price = numericPrice(quote);
    const time = Date.parse(quote?.collected_at);
    if (quote?.verification_status !== "verified" || quote?.source_family === "sample" ||
        !price || !Number.isFinite(time)) return [];
    return [{ time, value: price.value, raw: price.raw }];
  }).sort((a, b) => a.time - b.time);
}

export function quoteUnit(quote) {
  const currency = { TOMAN: "تومان", TRY: "لیر", USD: "دلار" }[quote.quote_currency] || quote.quote_currency;
  if (quote.base_quantity === "100") return `${currency} برای ۱۰۰ واحد`;
  if (quote.unit === "gram-18k") return `${currency} برای هر گرم`;
  if (quote.unit === "mithqal") return `${currency} برای هر مثقال`;
  if (quote.unit === "troy-ounce") return `${currency} برای هر انس`;
  return currency;
}
