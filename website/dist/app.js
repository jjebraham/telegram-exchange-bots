import {
  CATEGORY_META, CATEGORY_ORDER, bestQuote, chartObservations,
  formatPrice, isFresh, normalizeQuotes, numericPrice, quoteUnit,
} from "./model.js";

const byId = (id) => document.getElementById(id);
const state = {
  quotes: [], connected: false, error: "", lastFetched: null,
  filter: "all", search: "", series: "", days: 7, loading: false, chartRequest: 0,
};
const tehranTime = new Intl.DateTimeFormat("fa-IR", {
  timeZone: "Asia/Tehran", day: "numeric", month: "short",
  hour: "2-digit", minute: "2-digit",
});
const svgNS = "http://www.w3.org/2000/svg";

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function priceNode(quote, raw, className = "number") {
  const number = element("bdi", className, formatPrice(quote, raw));
  number.dir = "ltr";
  return number;
}

function quoteTime(quote) {
  return tehranTime.format(new Date(quote.collected_at));
}

function markFresh(quote) {
  const fresh = isFresh(quote, state.connected);
  return element("span", fresh ? "freshness" : "freshness stale", fresh ? "تازه" : "قدیمی");
}

async function fetchJson(path) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 12000);
  try {
    const response = await fetch(path, {
      cache: "no-store", headers: { Accept: "application/json" },
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return await response.json();
  } finally {
    clearTimeout(timer);
  }
}

function renderConnection() {
  const notice = byId("connection");
  const message = byId("connection-text");
  const updated = byId("updated-at");
  if (state.error) {
    notice.className = "notice error";
    message.textContent = "ارتباط با سامانهٔ نرخ‌ها برقرار نیست. نرخ‌های نمایش‌داده‌شده ممکن است قدیمی باشند.";
  } else if (!state.lastFetched) {
    notice.className = "notice loading";
    message.textContent = "در حال دریافت نرخ‌های تأییدشده…";
  } else if (!state.quotes.length) {
    notice.className = "notice warning";
    message.textContent = "هنوز نرخ تأییدشده‌ای برای نمایش وارد نشده است.";
  } else {
    const freshCount = state.quotes.filter((quote) => isFresh(quote, state.connected)).length;
    notice.className = freshCount ? "notice" : "notice warning";
    message.textContent = freshCount
      ? `${freshCount.toLocaleString("fa-IR")} نرخ تازه از ${state.quotes.length.toLocaleString("fa-IR")} نرخ تأییدشده`
      : "آخرین نرخ‌های تأییدشده موجودند، اما همگی قدیمی شده‌اند.";
  }
  updated.textContent = state.lastFetched
    ? `آخرین پاسخ: ${tehranTime.format(state.lastFetched)} تهران` : "";
}

function highlight(title, icon, quote, extra = "") {
  const card = element("article", "highlight-card");
  card.append(element("span", "card-icon", icon), element("div", "card-title", title));
  const price = numericPrice(quote);
  if (price) {
    card.append(priceNode(quote, price.raw, "card-value"));
    card.append(element("div", "card-unit", `${quoteUnit(quote)}${extra ? " · " + extra : ""}`));
    card.append(markFresh(quote));
  } else {
    card.append(element("div", "card-value", "—"));
    card.append(element("div", "card-unit", "نرخ تأییدشده موجود نیست"));
  }
  return card;
}

function renderHighlights() {
  const quotes = state.quotes;
  const grid = byId("highlight-grid");
  const usd = bestQuote(quotes, (q) => q.category === "iran_fx" && q.base_asset === "USD", state.connected);
  const lira = bestQuote(quotes, (q) => q.category === "iran_fx" && q.base_asset === "TRY", state.connected);
  const usdt = bestQuote(quotes, (q) => q.category === "usdt_exchange", state.connected);
  const gold = bestQuote(quotes, (q) => q.category === "iran_gold" && q.instrument_id === "gold:iran:gold-18k", state.connected);
  grid.replaceChildren(
    highlight("دلار آمریکا", "$", usd),
    highlight("لیر ترکیه", "₺", lira),
    highlight("تتر", "◈", usdt, usdt?.display_name_fa?.replace(/^USDT · /, "") || ""),
    highlight("طلای ۱۸ عیار", "✦", gold),
  );
}

function quoteMatches(quote) {
  if (state.filter !== "all") {
    const family = CATEGORY_META[quote.category]?.family || "other";
    if (state.filter === "digest") {
      if (!quote.category.startsWith("daily_")) return false;
    } else if (family !== state.filter) {
      return false;
    }
  }
  if (!state.search) return true;
  const haystack = [
    quote.display_name_fa, quote.base_asset, quote.instrument_id,
    quote.quote_currency, quote.source_id,
  ].join(" ").toLocaleLowerCase();
  return haystack.includes(state.search);
}

function marketRow(quote) {
  const row = element("tr");
  const name = element("td");
  name.append(element("span", "", quote.display_name_fa || quote.instrument_id));
  name.append(element("small", "", quote.base_asset || ""));
  const main = element("td");
  const price = numericPrice(quote);
  main.append(priceNode(quote, price?.raw));
  const rateKind = quote.quote_kind === "customer_rate"
    ? "پرداختی" : price?.kind === "reference" ? "مرجع" : "فروش";
  main.append(element("small", "", `${rateKind} · ${quoteUnit(quote)}`));
  const bid = element("td");
  if (typeof quote.bid === "string" && typeof quote.ask === "string") {
    bid.append(priceNode(quote, quote.bid));
  } else {
    bid.append(element("span", "dim", "—"));
  }
  const time = element("td");
  time.append(element("span", "", quoteTime(quote)));
  time.append(markFresh(quote));
  row.append(name, main, bid, time);
  return row;
}

function marketGroup(category, quotes) {
  const meta = CATEGORY_META[category] || {
    title: category.replaceAll("_", " "), detail: "نرخ تأییدشده",
  };
  const section = element("section", "market-group");
  const header = element("div", "group-header");
  const heading = element("div");
  heading.append(element("h3", "", meta.title), element("p", "", meta.detail));
  header.append(heading, element("span", "group-count", `${quotes.length.toLocaleString("fa-IR")} نرخ`));
  const scroll = element("div", "table-scroll");
  const table = element("table", "rate-table");
  const thead = element("thead");
  const headRow = element("tr");
  for (const label of ["نام بازار", "نرخ", "خرید", "ثبت · تهران"]) {
    headRow.append(element("th", "", label));
  }
  thead.append(headRow);
  const tbody = element("tbody");
  quotes.sort((a, b) => (a.display_name_fa || "").localeCompare(b.display_name_fa || "", "fa"));
  for (const quote of quotes) tbody.append(marketRow(quote));
  table.append(thead, tbody);
  scroll.append(table);
  section.append(header, scroll);
  return section;
}

function renderMarkets() {
  const visible = state.quotes.filter(quoteMatches);
  byId("rate-count").textContent = `${visible.length.toLocaleString("fa-IR")} نرخ مطابق فیلتر`;
  const container = byId("market-content");
  if (!visible.length) {
    container.replaceChildren(element("p", "empty-state",
      state.quotes.length ? "نرخی مطابق این جست‌وجو یافت نشد." : "هنوز دادهٔ تأییدشده‌ای برای نمایش موجود نیست."));
    return;
  }
  const groups = new Map();
  for (const quote of visible) {
    if (!groups.has(quote.category)) groups.set(quote.category, []);
    groups.get(quote.category).push(quote);
  }
  const order = [...CATEGORY_ORDER, ...[...groups.keys()].filter((key) => !CATEGORY_ORDER.includes(key))];
  container.replaceChildren(...order.filter((key) => groups.has(key)).map((key) => marketGroup(key, groups.get(key))));
}

function syncSeries() {
  const select = byId("series-select");
  const bySeries = new Map();
  for (const quote of state.quotes) {
    if (!bySeries.has(quote.series_id)) bySeries.set(quote.series_id, quote);
  }
  const values = [...bySeries.values()].sort((a, b) =>
    (CATEGORY_ORDER.indexOf(a.category) - CATEGORY_ORDER.indexOf(b.category)) ||
    (a.display_name_fa || "").localeCompare(b.display_name_fa || "", "fa"));
  if (!bySeries.has(state.series)) {
    state.series = bestQuote(values, (q) => q.category === "iran_fx" && q.base_asset === "USD", state.connected)?.series_id
      || values[0]?.series_id || "";
  }
  select.replaceChildren(...values.map((quote) => {
    const option = element("option", "", `${quote.display_name_fa || quote.instrument_id} · ${CATEGORY_META[quote.category]?.title || quote.category}`);
    option.value = quote.series_id;
    return option;
  }));
  select.disabled = !values.length;
  select.value = state.series;
  if (!values.length) select.append(element("option", "", "در انتظار داده"));
}

function svgNode(tag, attrs) {
  const node = document.createElementNS(svgNS, tag);
  for (const [name, value] of Object.entries(attrs)) node.setAttribute(name, String(value));
  return node;
}

function renderChart(points, quote) {
  const svg = byId("history-chart");
  const labels = byId("chart-labels");
  svg.replaceChildren();
  labels.replaceChildren();
  if (!points.length) {
    byId("chart-status").textContent = "در این بازه مشاهدهٔ تأییدشده‌ای ثبت نشده است.";
    return;
  }
  const values = points.map((point) => point.value);
  const low = Math.min(...values), high = Math.max(...values);
  const pad = high === low ? Math.max(high * .01, .000001) : (high - low) * .14;
  const minY = low - pad, maxY = high + pad;
  const minTime = points[0].time, maxTime = points[points.length - 1].time;
  const x = (point) => maxTime === minTime ? 380 : 28 + (point.time - minTime) / (maxTime - minTime) * 704;
  const y = (point) => 229 - (point.value - minY) / (maxY - minY) * 200;
  for (const guideY of [35, 100, 165, 229]) {
    svg.append(svgNode("line", { x1: 28, y1: guideY, x2: 732, y2: guideY, stroke: "#2d4359", "stroke-width": 1 }));
  }
  if (points.length > 1) {
    svg.append(svgNode("polyline", {
      points: points.map((point) => `${x(point).toFixed(2)},${y(point).toFixed(2)}`).join(" "),
      fill: "none", stroke: "#70d6cd", "stroke-width": 3,
      "stroke-linecap": "round", "stroke-linejoin": "round",
    }));
  }
  for (const point of points) {
    const dot = svgNode("circle", {
      cx: x(point).toFixed(2), cy: y(point).toFixed(2), r: points.length > 80 ? 2 : 4,
      fill: "#f0b85e", stroke: "#102238", "stroke-width": 1,
    });
    dot.append(svgNode("title", {}));
    dot.firstChild.textContent = `${formatPrice(quote, point.raw)} · ${tehranTime.format(new Date(point.time))} تهران`;
    svg.append(dot);
  }
  byId("chart-status").textContent = `${points.length.toLocaleString("fa-IR")} مشاهدهٔ واقعی · ${quoteUnit(quote)}`;
  labels.append(
    element("span", "", tehranTime.format(new Date(minTime))),
    element("span", "", tehranTime.format(new Date(maxTime))),
  );
}

async function loadChart() {
  const request = ++state.chartRequest;
  const svg = byId("history-chart");
  if (!state.series || !state.connected) {
    svg.replaceChildren();
    byId("chart-status").textContent = state.error
      ? "نمودار پس از برقراری ارتباط نمایش داده می‌شود."
      : "هنوز تاریخچهٔ تأییدشده‌ای موجود نیست.";
    byId("chart-labels").replaceChildren();
    return;
  }
  byId("chart-status").textContent = "در حال دریافت مشاهدات تأییدشده…";
  const quote = state.quotes.find((item) => item.series_id === state.series);
  const end = new Date(), start = new Date(end.getTime() - state.days * 86400000);
  const params = new URLSearchParams({
    series_id: state.series, from: start.toISOString(), to: end.toISOString(), limit: "2000",
  });
  try {
    const payload = await fetchJson(`/api/v1/history?${params}`);
    if (request !== state.chartRequest) return;
    renderChart(chartObservations(payload), quote);
  } catch {
    if (request !== state.chartRequest) return;
    svg.replaceChildren();
    byId("chart-labels").replaceChildren();
    byId("chart-status").textContent = "دریافت تاریخچه ممکن نشد. دوباره تلاش کنید.";
  }
}

function render() {
  renderConnection();
  renderHighlights();
  renderMarkets();
  syncSeries();
}

async function loadQuotes() {
  if (state.loading) return;
  state.loading = true;
  try {
    const payload = await fetchJson("/api/v1/quotes");
    state.quotes = normalizeQuotes(payload);
    state.connected = true;
    state.error = "";
    state.lastFetched = new Date();
  } catch (error) {
    state.connected = false;
    state.error = String(error);
  } finally {
    state.loading = false;
    render();
    loadChart();
  }
}

byId("category-tabs").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-filter]");
  if (!button) return;
  state.filter = button.dataset.filter;
  for (const item of byId("category-tabs").querySelectorAll("button")) {
    item.setAttribute("aria-pressed", String(item === button));
  }
  renderMarkets();
});
byId("rate-search").addEventListener("input", (event) => {
  state.search = event.target.value.trim().toLocaleLowerCase();
  renderMarkets();
});
byId("series-select").addEventListener("change", (event) => {
  state.series = event.target.value;
  loadChart();
});
for (const button of document.querySelectorAll(".range-buttons button")) {
  button.addEventListener("click", () => {
    state.days = Number(button.dataset.days);
    for (const item of document.querySelectorAll(".range-buttons button")) {
      item.setAttribute("aria-pressed", String(item === button));
    }
    loadChart();
  });
}
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) loadQuotes();
});
setInterval(() => {
  if (!document.hidden) loadQuotes();
}, 60000);
loadQuotes();
