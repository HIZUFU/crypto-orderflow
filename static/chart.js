const $ = (id) => document.getElementById(id);
const fmt = (value, digits = 2) => value == null || Number.isNaN(Number(value)) ? "-" : Number(value).toFixed(digits);
const esc = (value) => String(value ?? "").replace(/[&<>\"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#039;"}[c]));
let chart; let series; let currentSource = new URLSearchParams(location.search).get("source_key") || ""; let timeframe = "1m"; let lastCandles = []; let sources = {};
async function api(path) { const response = await fetch(path); const body = await response.json().catch(() => ({})); if (!response.ok) throw Error(body.detail || "Request failed"); return body; }
function init() { const node = $("chart"); chart = LightweightCharts.createChart(node, { width: node.clientWidth, height: 590, layout: { background: { color: "#121a23" }, textColor: "#e7edf5" }, grid: { vertLines: { color: "#263442" }, horzLines: { color: "#263442" } }, rightPriceScale: { borderColor: "#263442" }, timeScale: { borderColor: "#263442", timeVisible: true, secondsVisible: false } }); series = chart.addCandlestickSeries({ upColor: "#36d399", downColor: "#ff6b7a", borderVisible: false, wickUpColor: "#36d399", wickDownColor: "#ff6b7a" }); addEventListener("resize", () => chart.applyOptions({ width: node.clientWidth })); }
function sourceName(source) { return `${source.exchange} ${source.market} · ${source.symbol} · ${source.label}`; }
async function loadSources() {
  const market = await api("/api/market"); sources = market.sources || {};
  const values = Object.values(sources);
  if (!values.length) throw Error("No enabled market sources");
  if (!currentSource || !sources[currentSource]) currentSource = values[0].source_key;
  $("source-select").innerHTML = values.map((source) => `<option value="${esc(source.source_key)}">${esc(sourceName(source))}</option>`).join("");
  $("source-select").value = currentSource;
}
async function load() {
  try {
    await loadSources(); const source = sources[currentSource]; const encoded = encodeURIComponent(currentSource);
    const [candles, book, market, alerts] = await Promise.all([api(`/api/candles/${source.symbol}?source_key=${encoded}&timeframe=${timeframe}&limit=300`), api(`/api/orderbook/${source.symbol}?source_key=${encoded}&levels=20`), api("/api/market"), api("/api/alerts?limit=200")]);
    lastCandles = candles.candles || []; series.setData(lastCandles); chart.timeScale().fitContent(); renderBook(book); renderFeatures((market.sources || {})[currentSource]?.features); renderAlerts(alerts.filter((alert) => alert.source_key === currentSource));
    $("chart-status").textContent = `${sourceName(candles)} · ${lastCandles.length} candles · ${new Date().toLocaleTimeString()}`; $("exchange-badge").textContent = `${candles.exchange.toUpperCase()} ${candles.market.toUpperCase()}`;
    history.replaceState({}, "", `/chart.html?source_key=${encoded}&symbol=${encodeURIComponent(source.symbol)}`);
  } catch (error) { $("chart-status").textContent = error.message; }
}
function renderBook(book) { const render = (items, cls) => items.map((item) => `<div class="book-row ${cls}"><i style="width:${Math.min(100, (item.size / (items[0]?.size || 1)) * 100)}%"></i><span>${fmt(item.price)}</span><span>${fmt(item.size, 4)}</span></div>`).join(""); $("asks").innerHTML = render(book.asks.slice().reverse(), "ask"); $("bids").innerHTML = render(book.bids, "bid"); $("book-mid").textContent = `mid ${fmt((book.best_bid + book.best_ask) / 2)}`; $("book-meta").textContent = `${book.exchange} · ${book.market} · top ${book.bids.length} levels`; }
function renderFeatures(features) { $("feature-panel").innerHTML = features && Object.keys(features).length ? Object.entries(features).map(([key, value]) => `<div class="setting"><span>${esc(key.replaceAll("_", " "))}</span><b>${fmt(value, Math.abs(Number(value)) < 10 ? 3 : 2)}</b></div>`).join("") : "<div class=empty>Waiting for market features.</div>"; }
function renderAlerts(alerts) { if ($("show-alerts").checked && lastCandles.length) { const times = lastCandles.map((item) => item.time); const markers = alerts.map((alert) => { const target = Math.floor(new Date(alert.created_at).getTime() / 1000); const nearest = times.reduce((previous, current) => Math.abs(current - target) < Math.abs(previous - target) ? current : previous, times[0]); return { time: nearest, position: alert.direction === "LONG" ? "belowBar" : "aboveBar", color: alert.direction === "LONG" ? "#36d399" : "#ff6b7a", shape: alert.direction === "LONG" ? "arrowUp" : "arrowDown", text: alert.direction }; }); series.setMarkers(markers); } else { series.setMarkers([]); } $("chart-alerts").innerHTML = alerts.length ? `<table><thead><tr><th>Time</th><th>Direction</th><th>Score</th><th>Entry</th><th>Stop</th><th>Target</th></tr></thead><tbody>${alerts.slice(0, 12).map((alert) => `<tr><td>${new Date(alert.created_at).toLocaleTimeString()}</td><td class="${alert.direction === "LONG" ? "positive" : "negative"}">${alert.direction}</td><td>${fmt(alert.score * 100, 1)}%</td><td>${fmt(alert.reference_price)}</td><td>${fmt(alert.stop_loss)}</td><td>${fmt(alert.take_profit)}</td></tr>`).join("")}</tbody></table>` : "<div class=empty>No alerts for this source.</div>"; }
$("source-select").addEventListener("change", (event) => { currentSource = event.target.value; load(); }); $("timeframe-select").addEventListener("change", (event) => { timeframe = event.target.value; load(); }); $("show-alerts").addEventListener("change", load); init(); load(); setInterval(load, 5000);
