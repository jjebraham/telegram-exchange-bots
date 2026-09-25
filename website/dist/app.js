import {
  CATEGORY_META, CATEGORY_ORDER, bestQuote, changeBetween, chartObservations, cheapestAsk,
  currencyName, formatPercent, formatPrice, freshness, normalizeQuotes, numericPrice,
  observationSegments, quoteUnit, relativeAge, searchKey, sortQuotes,
} from "./model.js";

const byId = (id) => document.getElementById(id);
const svgNS = "http://www.w3.org/2000/svg";
const state = {
  quotes: [], connected: false, error: "", lastFetched: null, loading: false,
  filter: "all", search: "", series: new URLSearchParams(location.search).get("s") || "",
  days: 7, chartRequest: 0, chart: null, cursor: -1, scale: null, history: new Map(),
};

const tehranFull = new Intl.DateTimeFormat("fa-IR", {
  timeZone: "Asia/Tehran", weekday: "short", day: "numeric", month: "long", hour: "2-digit", minute: "2-digit",
});
const tehranDay = new Intl.DateTimeFormat("fa-IR", { timeZone: "Asia/Tehran", day: "numeric", month: "short" });
const tehranClock = new Intl.DateTimeFormat("fa-IR", { timeZone: "Asia/Tehran", hour: "2-digit", minute: "2-digit" });
const KIND_LABEL = { reference: "نرخ مرجع", two_sided: "خرید و فروش", ask_only: "قیمت خرید", customer: "قیمت مشتری" };

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
function svg(tag, attrs = {}) {
  const node = document.createElementNS(svgNS, tag);
  for (const [name, value] of Object.entries(attrs)) node.setAttribute(name, String(value));
  return node;
}
function num(quote, raw, className = "price") {
  const node = el("bdi", className, formatPrice(quote, raw));
  node.dir = "ltr";
  return node;
}
function timeNode(iso) {
  const node = el("time", "", relativeAge(Date.parse(iso)));
  node.dateTime = iso;
  node.dataset.at = iso;
  node.title = `${tehranFull.format(new Date(iso))} به وقت تهران`;
  return node;
}
function ageTag(quote) {
  const status = freshness(quote, Date.now(), state.connected);
  if (status === "fresh") return null;
  const tag = el("span", "age-tag", status === "expired" ? "منقضی" : "قدیمی");
  tag.dataset.state = status;
  return tag;
}
function splitName(quote) {
  const name = quote.display_name_fa || quote.instrument_id;
  const parts = name.split(" · ");
  if (parts.length === 2 && /^[A-Z/]+$/.test(parts[0])) return { name: parts[1], code: parts[0] };
  const code = /^[A-Z]{3,5}$/.test(quote.base_asset || "") ? quote.base_asset : "";
  return { name, code };
}
function changeNode(change, suffix) {
  if (!change) return el("span", "flat", "");
  const arrow = { up: "▲", down: "▼", flat: "■" }[change.direction];
  const node = el("span", change.direction, `${arrow} ${formatPercent(change.pct)}`);
  if (suffix) node.append(el("span", "flat", ` ${suffix}`));
  return node;
}

async function fetchJson(path) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 12000);
  try {
    const response = await fetch(path, { cache: "no-store", headers: { Accept: "application/json" }, signal: controller.signal });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return await response.json();
  } finally {
    clearTimeout(timer);
  }
}

// Cached per series, range and latest observation: a refresh refetches only after a new rate is published.
function fetchHistory(quote, days) {
  const key = `${quote.series_id}|${days}|${quote.collected_at}`;
  if (state.history.has(key)) return state.history.get(key);
  const end = new Date(Math.max(Date.now(), Date.parse(quote.collected_at) + 1000));
  const start = new Date(end.getTime() - days * 86400000);
  const params = new URLSearchParams({ series_id: quote.series_id, from: start.toISOString(), to: end.toISOString(), limit: "2000" });
  const request = fetchJson(`/api/v1/history?${params}`).catch((error) => {
    state.history.delete(key);
    throw error;
  });
  state.history.set(key, request);
  return request;
}

/* ---------- Status ---------- */

function renderStatus() {
  const status = byId("status");
  const text = byId("status-text");
  const newest = Math.max(0, ...state.quotes.map((q) => Date.parse(q.collected_at)));
  if (state.error) {
    status.dataset.state = "error";
    text.textContent = state.quotes.length
      ? "اتصال به سرور نرخ‌ها قطع شد. آخرین نرخ‌های دریافت‌شده را می‌بینید؛ صفحه هر دقیقه دوباره تلاش می‌کند."
      : "اتصال به سرور نرخ‌ها برقرار نشد. صفحه هر دقیقه دوباره تلاش می‌کند.";
  } else if (!state.lastFetched) {
    status.dataset.state = "loading";
    text.textContent = "در حال دریافت نرخ‌ها…";
  } else if (!state.quotes.length) {
    status.dataset.state = "warn";
    text.textContent = "هنوز نرخی منتشر نشده است.";
  } else {
    status.dataset.state = Date.now() - newest > 3 * 3600000 ? "warn" : "ok";
    text.replaceChildren("آخرین نرخ: ", timeNode(new Date(newest).toISOString()));
  }
}

/* ---------- Board ---------- */

const BOARD = [
  {
    name: "دلار آمریکا", meta: () => "تومان · بازار آزاد",
    find: (qs) => ({ quote: bestQuote(qs, (q) => q.category === "iran_fx" && q.base_asset === "USD", state.connected) }),
  },
  {
    name: "لیر ترکیه", meta: () => "تومان · بازار آزاد",
    find: (qs) => ({ quote: bestQuote(qs, (q) => q.category === "iran_fx" && q.base_asset === "TRY", state.connected) }),
  },
  {
    name: "تتر",
    find: (qs) => cheapestAsk(qs, (q) => q.category === "usdt_exchange", state.connected) || { quote: null },
    meta: (pick) => `تومان · ${splitName(pick.quote).name}، ارزان‌ترین از ${pick.count.toLocaleString("fa-IR")} صرافی`,
  },
  {
    name: "دلار در استانبول", twoSided: true, meta: () => "لیر · بازار کاپالی‌چارشی",
    find: (qs) => ({ quote: bestQuote(qs, (q) => q.category === "turkey_fx" && q.base_asset === "USD" && q.series_id.includes("kapalicarsi"), state.connected) }),
  },
  {
    name: "طلای ۱۸ عیار", meta: () => "تومان برای هر گرم",
    find: (qs) => ({ quote: bestQuote(qs, (q) => q.instrument_id === "gold:iran:gold-18k", state.connected) }),
  },
];

function sparkline(points) {
  const node = svg("svg", { class: "board-spark", viewBox: "0 0 200 30", preserveAspectRatio: "none", "aria-hidden": "true" });
  if (points.length < 2) return node;
  const values = points.map((p) => p.value);
  const low = Math.min(...values), high = Math.max(...values);
  const t0 = points[0].time, t1 = points[points.length - 1].time;
  const x = (p) => ((p.time - t0) / (t1 - t0 || 1)) * 196 + 2;
  const y = (p) => high === low ? 15 : 27 - ((p.value - low) / (high - low)) * 24;
  for (const segment of observationSegments(points)) {
    if (segment.length < 2) continue;
    node.append(svg("path", {
      d: segment.map((p, i) => `${i ? "L" : "M"}${x(p).toFixed(1)},${y(p).toFixed(1)}`).join(""),
      "vector-effect": "non-scaling-stroke",
    }));
  }
  return node;
}

function renderBoard() {
  byId("board").replaceChildren(...BOARD.map((item) => {
    const pick = state.quotes.length ? item.find(state.quotes) : { quote: null };
    const quote = pick.quote;
    const cell = el(quote ? "button" : "div", quote ? "board-cell" : "board-cell is-empty");
    cell.append(el("span", "board-name", item.name));
    if (!quote) {
      cell.append(el("span", "board-value", "—"), el("span", "board-meta", state.lastFetched ? "نرخ منتشرشده‌ای نیست" : ""));
      return cell;
    }
    cell.type = "button";
    cell.setAttribute("aria-label", `${item.name}، نمایش نمودار`);
    cell.addEventListener("click", () => selectSeries(quote.series_id, true));
    if (item.twoSided) {
      const pair = el("span", "board-pair");
      pair.append(el("span", "", "خرید"), num(quote, quote.bid, ""), el("span", "", "فروش"), num(quote, quote.ask, ""));
      cell.append(pair);
    } else {
      cell.append(num(quote, numericPrice(quote).raw, "board-value"));
    }
    cell.append(el("span", "board-meta", item.meta(pick)));
    const change = el("span", "board-change");
    const spark = el("span");
    const foot = el("span", "board-foot");
    foot.append(timeNode(quote.collected_at));
    const tag = ageTag(quote);
    if (tag) foot.append(tag);
    cell.append(change, spark, foot);
    fetchHistory(quote, 7).then((payload) => {
      const points = chartObservations(payload, item.twoSided ? "ask" : undefined);
      const index = points.findIndex((p) => p.time === Date.parse(quote.collected_at));
      const result = index > 0 ? changeBetween(points[index - 1], points[index]) : null;
      if (result) {
        change.replaceChildren(changeNode(result, `از ثبت قبلی (${relativeAge(result.from.time)})`));
        if (item.twoSided) change.title = "تغییر قیمت فروش";
      }
      spark.replaceWith(sparkline(points));
    }).catch(() => {});
    return cell;
  }));
}

/* ---------- Tables ---------- */

function quoteMatches(quote) {
  const meta = CATEGORY_META[quote.category];
  if (state.filter !== "all" && (meta?.family || "other") !== state.filter) return false;
  if (!state.search) return true;
  return searchKey([quote.display_name_fa, quote.base_asset, quote.instrument_id, quote.quote_currency, meta?.title].join(" "))
    .includes(state.search);
}

const COLUMNS = {
  reference: ["نام", "نرخ", "زمان ثبت"],
  ask_only: ["صرافی", "قیمت خرید هر تتر", "زمان ثبت"],
  two_sided: ["نام", "خرید", "فروش", "زمان ثبت"],
  customer: ["نام", "نرخ", "اعتبار"],
};

function priceCell(quote, raw, label) {
  const cell = el("td", "col-price");
  if (label) cell.dataset.label = label;
  cell.append(typeof raw === "string" ? num(quote, raw) : el("span", "flat", "—"));
  return cell;
}

function marketRow(quote, kind, cheapestId, sharedTime) {
  const row = el("tr");
  row.dataset.series = quote.series_id;
  row.dataset.state = freshness(quote, Date.now(), state.connected);
  if (quote.series_id === state.series) row.setAttribute("aria-current", "true");
  const { name, code } = splitName(quote);
  const nameCell = el("td", "col-name");
  const button = el("button", "row-name", name);
  button.type = "button";
  button.setAttribute("aria-label", `${name}${code ? " " + code : ""}، نمایش نمودار`);
  nameCell.append(button);
  if (code && kind !== "ask_only") nameCell.append(el("span", "row-code", code));
  row.append(nameCell);

  if (kind === "two_sided") {
    row.append(priceCell(quote, quote.bid, "خرید"), priceCell(quote, quote.ask, "فروش"));
  } else {
    const cell = priceCell(quote, numericPrice(quote).raw);
    if (quote.series_id === cheapestId) cell.prepend(el("span", "best-tag", "ارزان‌ترین"));
    const unit = quoteUnit(quote);
    if (unit !== currencyName(quote)) cell.append(el("span", "unit-note", unit.replace(currencyName(quote), "").trim()));
    row.append(cell);
  }

  if (!sharedTime) {
    const ageCell = el("td", "col-age");
    ageCell.append(...timeParts(quote, kind));
    row.append(ageCell);
  }
  return row;
}

// "registered N minutes ago", plus validity for customer prices and an old/expired tag when needed.
function timeParts(quote, kind) {
  const parts = [];
  const status = freshness(quote, Date.now(), state.connected);
  if (kind === "customer" && quote.valid_until && status !== "expired") {
    parts.push(`معتبر تا ${tehranClock.format(new Date(quote.valid_until))} · `);
  }
  parts.push("ثبت ", timeNode(quote.collected_at));
  const tag = ageTag(quote);
  if (tag) parts.push(tag);
  return parts;
}

function marketGroup(category, quotes) {
  const meta = CATEGORY_META[category] || { title: category.replaceAll("_", " "), kind: "reference", note: "" };
  const section = el("section", "market-group");
  section.setAttribute("aria-labelledby", `group-${category}`);
  const head = el("div", "group-head");
  const title = el("h3", "", meta.title);
  title.id = `group-${category}`;
  const tag = el("span", "kind-tag", KIND_LABEL[meta.kind]);
  tag.dataset.kind = meta.kind;
  // Rows from one publication share a timestamp; show it once in the heading instead of on every row.
  const sharedTime = quotes.every((q) => q.collected_at === quotes[0].collected_at && q.valid_until === quotes[0].valid_until);
  const side = el("div", "head-side");
  if (sharedTime) side.append(el("span", "group-time"));
  side.append(tag);
  if (sharedTime) side.firstChild.append(...timeParts(quotes[0], meta.kind));
  head.append(title, el("p", "", meta.note), side);

  const table = el("table", meta.kind === "two_sided" ? "rate-table two-sided" : "rate-table");
  const headRow = el("tr");
  const columns = sharedTime ? COLUMNS[meta.kind].slice(0, -1) : COLUMNS[meta.kind];
  columns.forEach((label, i, all) => {
    const th = el("th", i === 0 ? "col-name" : !sharedTime && i === all.length - 1 ? "col-age" : "col-price", label);
    th.scope = "col";
    headRow.append(th);
  });
  const thead = el("thead");
  thead.append(headRow);
  const cheapest = meta.kind === "ask_only" ? cheapestAsk(quotes, () => true, state.connected) : null;
  const cheapestId = cheapest && !cheapest.allStale && cheapest.count > 1 ? cheapest.quote.series_id : "";
  const tbody = el("tbody");
  for (const quote of sortQuotes(category, quotes)) tbody.append(marketRow(quote, meta.kind, cheapestId, sharedTime));
  table.append(thead, tbody);
  const box = el("div", "table-box");
  box.append(table);
  section.append(head, box);
  return section;
}

function renderMarkets() {
  const visible = state.quotes.filter(quoteMatches);
  byId("rate-count").textContent = state.quotes.length ? `(${visible.length.toLocaleString("fa-IR")})` : "";
  const container = byId("market-content");
  if (!visible.length) {
    const empty = el("div", "empty-state");
    if (state.quotes.length) {
      const query = byId("rate-search").value.trim();
      empty.append(el("p", "", query ? `نرخی با «${query}» در این بخش پیدا نشد.` : "در این بخش نرخی وجود ندارد."));
      const reset = el("button", "", "نمایش همهٔ نرخ‌ها");
      reset.type = "button";
      reset.addEventListener("click", () => { byId("rate-search").value = ""; state.search = ""; setFilter("all"); });
      empty.append(reset);
    } else {
      empty.textContent = state.lastFetched ? "هنوز نرخی منتشر نشده است." : "در حال دریافت نرخ‌ها…";
    }
    container.replaceChildren(empty);
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

function setFilter(filter) {
  state.filter = filter;
  for (const item of byId("category-tabs").querySelectorAll("button")) {
    item.setAttribute("aria-pressed", String(item.dataset.filter === filter));
  }
  renderMarkets();
}

/* ---------- Chart ---------- */

function currentQuote() {
  return state.quotes.find((q) => q.series_id === state.series) || null;
}

function syncSeries() {
  const select = byId("series-select");
  const seen = new Map();
  for (const quote of state.quotes) if (!seen.has(quote.series_id)) seen.set(quote.series_id, quote);
  if (!seen.has(state.series)) {
    state.series = bestQuote([...seen.values()], (q) => q.category === "iran_fx" && q.base_asset === "USD", state.connected)?.series_id
      || [...seen.keys()][0] || "";
  }
  const groups = new Map();
  for (const quote of seen.values()) {
    if (!groups.has(quote.category)) groups.set(quote.category, []);
    groups.get(quote.category).push(quote);
  }
  const order = [...CATEGORY_ORDER, ...[...groups.keys()].filter((k) => !CATEGORY_ORDER.includes(k))];
  select.replaceChildren(...order.filter((k) => groups.has(k)).map((category) => {
    const group = el("optgroup");
    group.label = CATEGORY_META[category]?.title || category;
    for (const quote of sortQuotes(category, groups.get(category))) {
      const { name, code } = splitName(quote);
      const option = el("option", "", code ? `${name} (${code})` : name);
      option.value = quote.series_id;
      group.append(option);
    }
    return group;
  }));
  select.disabled = !seen.size;
  if (!seen.size) select.append(el("option", "", "در انتظار داده"));
  select.value = state.series;
}

function selectSeries(seriesId, scroll = false) {
  state.series = seriesId;
  state.chart = null;
  byId("series-select").value = seriesId;
  try {
    const url = new URL(location.href);
    url.searchParams.set("s", seriesId);
    window.history.replaceState(null, "", url);
  } catch { /* previews without a real origin */ }
  for (const row of document.querySelectorAll("tr[data-series]")) {
    if (row.dataset.series === seriesId) row.setAttribute("aria-current", "true"); else row.removeAttribute("aria-current");
  }
  loadChart();
  if (scroll) {
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    byId("history").scrollIntoView({ behavior: reduce ? "auto" : "smooth" });
  }
}

function chartStatus(text) {
  byId("chart-status").textContent = text;
}

async function loadChart() {
  const request = ++state.chartRequest;
  const quote = currentQuote();
  renderChartHeader(quote, null);
  if (!quote) {
    state.chart = null;
    drawChart();
    chartStatus(state.error ? "نمودار پس از برقراری اتصال نمایش داده می‌شود."
      : state.lastFetched ? "نرخی برای نمودار وجود ندارد." : "در حال دریافت نرخ‌ها…");
    return;
  }
  if (!state.chart) chartStatus("در حال دریافت تاریخچه…");
  try {
    const payload = await fetchHistory(quote, state.days);
    if (request !== state.chartRequest) return;
    const twoSided = CATEGORY_META[quote.category]?.kind === "two_sided";
    const lines = twoSided
      ? [{ label: "فروش", points: chartObservations(payload, "ask"), primary: true }, { label: "خرید", points: chartObservations(payload, "bid") }]
      : [{ label: "", points: chartObservations(payload), primary: true }];
    state.chart = { quote, lines };
    state.cursor = -1;
    renderChartHeader(quote, lines[0].points);
    drawChart();
    chartStatus(lines[0].points.length ? "" : "در این بازه نرخی منتشر نشده است. بازهٔ طولانی‌تری را انتخاب کنید.");
  } catch {
    if (request !== state.chartRequest) return;
    state.chart = null;
    drawChart();
    chartStatus("تاریخچه دریافت نشد. چند لحظه بعد دوباره امتحان کنید.");
  }
}

function renderChartHeader(quote, points) {
  const subtitle = byId("chart-subtitle");
  const summary = byId("chart-summary");
  if (!quote) {
    subtitle.textContent = "یک نرخ را از جدول یا فهرست زیر انتخاب کنید.";
    summary.replaceChildren();
    return;
  }
  const meta = CATEGORY_META[quote.category];
  const { name, code } = splitName(quote);
  subtitle.textContent = `${name}${code ? ` (${code})` : ""} · ${meta?.title || ""} · ${quoteUnit(quote)}`;
  const value = el("span", "summary-value");
  if (meta?.kind === "two_sided") {
    value.append("خرید ", num(quote, quote.bid, ""), " · فروش ", num(quote, quote.ask, ""));
  } else {
    value.append(num(quote, numericPrice(quote).raw, ""));
  }
  const nodes = [value];
  if (points && points.length > 1) {
    const line = el("span", "summary-change");
    const side = meta?.kind === "two_sided" ? " (فروش)" : "";
    line.append(changeNode(changeBetween(points[0], points[points.length - 1]), `از ${tehranDay.format(new Date(points[0].time))} تا آخرین ثبت${side}`));
    nodes.push(line);
  }
  summary.replaceChildren(...nodes);
}

function niceTicks(low, high, count = 4) {
  if (high === low) return [low];
  const raw = (high - low) / count;
  const step = 10 ** Math.floor(Math.log10(raw));
  const nice = [1, 2, 2.5, 5, 10].map((m) => m * step).find((s) => s >= raw) || raw;
  const ticks = [];
  for (let v = Math.ceil(low / nice) * nice; v <= high + nice * 1e-9; v += nice) ticks.push(Number(v.toPrecision(12)));
  return ticks;
}
function axisNumber(value, spread) {
  const decimals = spread >= 50 ? 0 : spread >= 1 ? 2 : Math.min(10, Math.ceil(-Math.log10(spread)) + 2);
  return value.toLocaleString("en-US", { maximumFractionDigits: decimals });
}

function drawChart() {
  const frame = byId("chart-frame");
  const chartSvg = byId("history-chart");
  const axis = byId("chart-axis");
  chartSvg.replaceChildren();
  axis.replaceChildren();
  byId("chart-tip").hidden = true;
  const data = state.chart;
  const primary = data?.lines.find((l) => l.primary)?.points || [];
  state.scale = null;
  if (!primary.length) return;

  const width = frame.clientWidth, height = frame.clientHeight;
  const pad = { left: 14, right: width < 520 ? 60 : 78, top: 30, bottom: 34 };
  chartSvg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  const all = data.lines.flatMap((l) => l.points);
  const rawLow = Math.min(...all.map((p) => p.value)), rawHigh = Math.max(...all.map((p) => p.value));
  const spread = rawHigh - rawLow || rawHigh * 0.01;
  const low = rawLow - spread * 0.12, high = rawHigh + spread * 0.12;
  const t0 = Math.min(...all.map((p) => p.time)), t1 = Math.max(...all.map((p) => p.time));
  const plotW = width - pad.left - pad.right, plotH = height - pad.top - pad.bottom;
  const x = (t) => t1 === t0 ? pad.left + plotW / 2 : pad.left + ((t - t0) / (t1 - t0)) * plotW;
  const y = (v) => pad.top + (1 - (v - low) / (high - low)) * plotH;

  for (const tick of niceTicks(low, high)) {
    if (tick < low || tick > high) continue;
    chartSvg.append(svg("line", { class: "grid", x1: pad.left, x2: width - pad.right + 6, y1: y(tick), y2: y(tick) }));
    const label = el("span", "", axisNumber(tick, spread));
    label.style.cssText = `right:10px;top:${y(tick) - 10}px;direction:ltr`;
    axis.append(label);
  }
  const labelCount = t1 === t0 ? 1 : Math.max(2, Math.min(5, Math.floor(plotW / 120)));
  const shortRange = t1 - t0 < 36 * 3600000;
  for (let i = 0; i < labelCount; i += 1) {
    const t = labelCount === 1 ? t0 : t0 + ((t1 - t0) * i) / (labelCount - 1);
    const label = el("span", "", shortRange ? tehranClock.format(new Date(t)) : tehranDay.format(new Date(t)));
    const shift = labelCount === 1 ? "-50%" : i === 0 ? "0" : i === labelCount - 1 ? "-100%" : "-50%";
    label.style.cssText = `bottom:8px;left:${x(t)}px;transform:translateX(${shift})`;
    axis.append(label);
  }

  for (const line of data.lines) {
    for (const segment of observationSegments(line.points)) {
      if (segment.length > 1) {
        const path = svg("path", { class: line.primary ? "line" : "line secondary", d: segment.map((p, i) => `${i ? "L" : "M"}${x(p.time).toFixed(1)},${y(p.value).toFixed(1)}`).join("") });
        chartSvg.append(path);
      }
      if (segment.length === 1 || line.points.length <= 60) {
        for (const p of segment) {
          chartSvg.append(svg("circle", { class: line.primary ? "dot" : "dot secondary", cx: x(p.time), cy: y(p.value), r: segment.length === 1 ? 3.5 : 2.5 }));
        }
      }
    }
  }
  const last = primary[primary.length - 1];
  chartSvg.append(svg("circle", { class: "cursor-dot", cx: x(last.time), cy: y(last.value), r: 4.5 }));
  if (data.lines.length > 1) {
    const legend = el("span", "chart-legend");
    legend.append(el("i", "legend-primary", "فروش"), el("i", "legend-secondary", "خرید"));
    axis.append(legend);
  }
  state.scale = { x, y, pad, height };
  chartSvg.setAttribute("aria-label", `${byId("chart-subtitle").textContent}. ${primary.length.toLocaleString("fa-IR")} نرخ منتشرشده. برای حرکت بین نقاط از کلیدهای جهت‌دار استفاده کنید.`);
  if (state.cursor >= 0) showCursor(state.cursor);
}

function showCursor(index) {
  const data = state.chart;
  const primary = data?.lines.find((l) => l.primary)?.points;
  if (!primary?.length || !state.scale) return;
  index = Math.max(0, Math.min(primary.length - 1, index));
  state.cursor = index;
  const point = primary[index];
  const { x, y, pad, height } = state.scale;
  const chartSvg = byId("history-chart");
  chartSvg.querySelectorAll(".cursor-layer").forEach((n) => n.remove());
  const layer = svg("g", { class: "cursor-layer" });
  layer.append(svg("line", { class: "cursor", x1: x(point.time), x2: x(point.time), y1: pad.top - 8, y2: height - pad.bottom }));
  layer.append(svg("circle", { class: "cursor-dot", cx: x(point.time), cy: y(point.value), r: 5 }));
  chartSvg.append(layer);

  const tip = byId("chart-tip");
  tip.replaceChildren();
  for (const line of data.lines) {
    const match = line.points.find((p) => p.time === point.time);
    if (!match) continue;
    const row = el("strong");
    if (line.label) row.append(`${line.label} `);
    row.append(num(data.quote, match.raw, ""), el("span", "unit-note", quoteUnit(data.quote)));
    tip.append(row);
  }
  tip.append(`${tehranFull.format(new Date(point.time))} تهران`);
  tip.hidden = false;
  const frameWidth = byId("chart-frame").clientWidth;
  const px = x(point.time);
  const tipWidth = tip.offsetWidth;
  tip.style.left = `${px + 14 + tipWidth > frameWidth - 8 ? Math.max(8, px - 14 - tipWidth) : px + 14}px`;
}

function nearestIndex(clientX) {
  const primary = state.chart?.lines.find((l) => l.primary)?.points;
  if (!primary?.length || !state.scale) return -1;
  const px = clientX - byId("history-chart").getBoundingClientRect().left;
  let best = 0, bestDistance = Infinity;
  primary.forEach((p, i) => {
    const d = Math.abs(state.scale.x(p.time) - px);
    if (d < bestDistance) { bestDistance = d; best = i; }
  });
  return best;
}

/* ---------- Load and wire up ---------- */

function render() {
  renderStatus();
  renderBoard();
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
  if (button) setFilter(button.dataset.filter);
});
byId("rate-search").addEventListener("input", (event) => {
  state.search = searchKey(event.target.value.trim());
  renderMarkets();
});
byId("market-content").addEventListener("click", (event) => {
  const row = event.target.closest("tr[data-series]");
  if (row) selectSeries(row.dataset.series, true);
});
byId("series-select").addEventListener("change", (event) => selectSeries(event.target.value));
for (const button of document.querySelectorAll(".segmented button")) {
  button.addEventListener("click", () => {
    state.days = Number(button.dataset.days);
    for (const item of document.querySelectorAll(".segmented button")) item.setAttribute("aria-pressed", String(item === button));
    state.chart = null;
    loadChart();
  });
}
const chartSvg = byId("history-chart");
chartSvg.addEventListener("pointermove", (event) => { const i = nearestIndex(event.clientX); if (i >= 0) showCursor(i); });
chartSvg.addEventListener("pointerleave", () => { if (document.activeElement !== chartSvg) { state.cursor = -1; drawChart(); } });
chartSvg.addEventListener("keydown", (event) => {
  const primary = state.chart?.lines.find((l) => l.primary)?.points;
  const moves = { ArrowRight: 1, ArrowLeft: -1 };
  if (!primary?.length || !(event.key in moves || event.key === "Home" || event.key === "End")) return;
  event.preventDefault();
  const start = state.cursor < 0 ? primary.length - 1 : state.cursor;
  showCursor(event.key === "Home" ? 0 : event.key === "End" ? primary.length - 1 : start + moves[event.key]);
});
chartSvg.addEventListener("blur", () => { state.cursor = -1; drawChart(); });
new ResizeObserver(() => drawChart()).observe(byId("chart-frame"));

document.addEventListener("visibilitychange", () => { if (!document.hidden) loadQuotes(); });
setInterval(() => { if (!document.hidden) loadQuotes(); }, 60000);
setInterval(() => {
  for (const node of document.querySelectorAll("time[data-at]")) node.textContent = relativeAge(Date.parse(node.dataset.at));
}, 30000);
loadQuotes();

