const $ = (id) => document.getElementById(id);
const fmt = (value, digits = 4) => value == null ? "-" : Number(value).toFixed(digits);
const esc = (value) => String(value ?? "").replace(/[&<>\"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#039;"}[c]));

async function get(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

function renderStatus(health, alerts, trades) {
  const open = trades.filter((trade) => trade.status === "open").length;
  $("status").innerHTML = [
    ["stream", health.stream_connected ? "connected" : "offline"],
    ["books ready", Object.values(health.books_ready).filter(Boolean).length + "/" + health.symbols.length],
    ["alerts", alerts.length],
    ["open paper", open],
  ].map(([label, value]) => `<div class="stat"><div class="stat-label">${label}</div><div class="stat-value">${esc(value)}</div></div>`).join("");
}

function renderMarket(market) {
  const symbols = Object.keys(market);
  $("market").innerHTML = symbols.length ? symbols.map((symbol) => {
    const item = market[symbol];
    const imbalanceClass = item.imbalance >= 0 ? "positive" : "negative";
    return `<div class="market-card"><div class="market-title"><span>${esc(symbol)}</span><span class="${imbalanceClass}">${item.imbalance >= 0 ? "LONG BIAS" : "SHORT BIAS"}</span></div><div class="metrics">
      <div><div class="metric-label">mid</div><div class="metric-value">${fmt(item.mid_price, 2)}</div></div>
      <div><div class="metric-label">spread</div><div class="metric-value">${fmt(item.spread_bps, 2)} bps</div></div>
      <div><div class="metric-label">imbalance</div><div class="metric-value ${imbalanceClass}">${fmt(item.imbalance, 3)}</div></div>
      <div><div class="metric-label">delta / 3s</div><div class="metric-value ${item.delta_ratio_3s >= 0 ? "positive" : "negative"}">${fmt(item.delta_ratio_3s, 3)}</div></div>
      <div><div class="metric-label">microprice offset</div><div class="metric-value">${fmt(item.microprice_offset_bps, 2)} bps</div></div>
      <div><div class="metric-label">trades / 3s</div><div class="metric-value">${fmt(item.trades_3s, 0)}</div></div>
    </div></div>`;
  }).join("") : '<div class="empty">Waiting for market data...</div>';
}

function renderTrades(trades) {
  const open = trades.filter((trade) => trade.status === "open");
  $("trades").innerHTML = open.length ? `<table><thead><tr><th>symbol</th><th>side</th><th>entry</th><th>stop</th><th>target</th></tr></thead><tbody>${open.map((trade) => `<tr><td>${esc(trade.symbol)}</td><td class="${trade.direction === "LONG" ? "positive" : "negative"}">${trade.direction}</td><td>${fmt(trade.entry_price, 2)}</td><td>${fmt(trade.stop_loss, 2)}</td><td>${fmt(trade.take_profit, 2)}</td></tr>`).join("")}</tbody></table>` : '<div class="empty">No open paper trades</div>';
}

function renderAlerts(alerts) {
  $("alerts").innerHTML = alerts.length ? `<table><thead><tr><th>time</th><th>symbol</th><th>side</th><th>score</th><th>entry</th><th>risk</th><th>action</th></tr></thead><tbody>${alerts.map((alert) => `<tr><td>${new Date(alert.created_at).toLocaleTimeString()}</td><td>${esc(alert.symbol)}</td><td class="${alert.direction === "LONG" ? "positive" : "negative"}">${alert.direction}</td><td>${fmt(alert.score * 100, 1)}%</td><td>${fmt(alert.reference_price, 2)}</td><td>${fmt(alert.risk_amount, 4)} USDT</td><td>${alert.status === "paper_opened" ? '<span class="muted">opened</span>' : `<button class="button" onclick="openPaper(${alert.id})">paper</button>`}</td></tr>`).join("")}</tbody></table>` : '<div class="empty">No alerts yet</div>';
}

async function openPaper(id) {
  try { await get(`/api/alerts/${id}/paper`, {method:"POST"}); await refresh(); }
  catch (error) { window.alert(error.message); }
}

async function refresh() {
  try {
    const [health, market, alerts, trades] = await Promise.all([get("/api/health"), get("/api/market"), get("/api/alerts"), get("/api/paper-trades")]);
    renderStatus(health, alerts, trades); renderMarket(market); renderAlerts(alerts); renderTrades(trades);
    $("updated").textContent = new Date().toLocaleTimeString();
  } catch (error) { $("updated").textContent = "API unavailable"; }
}
refresh();
setInterval(refresh, 2000);
