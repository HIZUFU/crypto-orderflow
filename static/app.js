const $ = (id) => document.getElementById(id);
const fmt = (value, digits = 2) => value == null || Number.isNaN(Number(value)) ? "-" : Number(value).toFixed(digits);
const pct = (value, digits = 1) => `${(Number(value || 0) * 100).toFixed(digits)}%`;
const esc = (value) => String(value ?? "").replace(/[&<>\"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#039;"}[c]));
let lastAlertIds = new Set();

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || "Request failed");
  return body;
}
function toast(message, kind = "info") { const node = $("toast"); node.textContent = message; node.className = `toast visible ${kind}`; clearTimeout(window.toastTimer); window.toastTimer = setTimeout(() => { node.className = "toast"; }, 3500); }
function sideClass(direction) { return direction === "LONG" ? "long" : "short"; }
function sourceLabel(item) { return `${item.exchange || "-"} · ${item.market || "-"}`; }
function renderSummary(health, stats, analytics) {
  const sourceCount = Object.keys(health.sources || {}).length;
  const readyCount = Object.values(health.books_ready || {}).filter(Boolean).length;
  $("summary").innerHTML = [
    ["Stream", health.stream_connected ? "Connected" : "Offline", health.stream_connected ? "positive" : "negative", `${sourceCount} public source${sourceCount === 1 ? "" : "s"}`],
    ["Books ready", `${readyCount}/${sourceCount}`, "", "independent order books"],
    ["Issued alerts", analytics.total_alerts, "", `${pct(analytics.conversion_rate)} opened`],
    ["Paper equity", `${fmt(stats.equity)} USDT`, stats.equity >= stats.initial_balance ? "positive" : "negative", `realized ${fmt(stats.realized_pnl)} USDT`],
    ["Win rate", pct(stats.win_rate), stats.win_rate >= 0.5 ? "positive" : "negative", `${stats.closed_trades} closed trades`],
    ["Max drawdown", `${fmt(stats.max_drawdown)} USDT`, stats.max_drawdown < 0 ? "negative" : "positive", "closed-trade equity"],
  ].map(([label, value, cls, hint]) => `<div class="metric-card"><span>${label}</span><strong class="${cls}">${value}</strong><small>${hint}</small></div>`).join("");
}
function renderMarket(payload) {
  const market = Object.values(payload.sources || {});
  $("market").innerHTML = market.length ? market.map((item) => {
    const features = item.features || {};
    const pressure = Number(features.imbalance || 0) >= 0 ? "LONG" : "SHORT";
    const pressurePct = Math.min(100, Math.abs(Number(features.imbalance || 0)) * 100);
    const href = `/chart.html?source_key=${encodeURIComponent(item.source_key)}&symbol=${encodeURIComponent(item.symbol)}`;
    return `<article class="market-card"><div class="market-card-head"><div><b>${esc(item.symbol)}</b><span class="market-sub">${esc(sourceLabel(item))} · mid ${fmt(features.mid_price)}</span></div><span class="signal-pill ${sideClass(pressure)}">${pressure} bias</span></div><div class="pressure"><div class="pressure-label"><span>book pressure</span><b>${fmt(features.imbalance, 3)}</b></div><div class="pressure-track"><i class="${sideClass(pressure)}" style="width:${pressurePct}%"></i></div></div><div class="feature-grid"><div><span>Spread</span><b>${fmt(features.spread_bps)} bps</b></div><div><span>Delta / 3s</span><b class="${Number(features.delta_ratio_3s) >= 0 ? "positive" : "negative"}">${fmt(features.delta_ratio_3s, 3)}</b></div><div><span>Microprice</span><b>${fmt(features.microprice_offset_bps)} bps</b></div><div><span>Trades / 3s</span><b>${fmt(features.trades_3s, 0)}</b></div></div><a class="card-link" href="${href}">Inspect this source <span>-&gt;</span></a></article>`;
  }).join("") : `<div class="empty">Waiting for the first order book snapshot.</div>`;
}
function renderAlerts(alerts) {
  const active = alerts.filter((alert) => !alert.expired && alert.outcome_type === "pending");
  $("alerts").innerHTML = alerts.length ? alerts.slice(0, 12).map((alert) => {
    const actionable = !alert.expired && alert.status === "new" && alert.outcome_type === "pending";
    const outcome = alert.outcome_type !== "pending" ? `<span class="outcome ${alert.outcome_type}">${esc(alert.outcome_type.replaceAll("_", " "))}</span>` : alert.expired ? `<span class="outcome expired">expired</span>` : "";
    return `<article class="alert-row"><div class="alert-main"><div class="alert-title"><span class="signal-pill ${sideClass(alert.direction)}">${alert.direction}</span><b>${esc(alert.symbol)}</b><span class="score">${pct(alert.score)}</span><time>${new Date(alert.created_at).toLocaleTimeString()}</time></div><p>${esc(sourceLabel(alert))} · ${esc(alert.reason)}</p><div class="alert-levels"><span>Entry <b>${fmt(alert.reference_price)}</b></span><span>Stop <b>${fmt(alert.stop_loss)}</b></span><span>Target <b>${fmt(alert.take_profit)}</b></span><span>Risk <b>${fmt(alert.risk_amount, 4)} USDT</b></span></div></div><div class="alert-actions">${outcome}<button class="button tiny" onclick="showAlert(${alert.id})">Details</button>${actionable ? `<button class="button tiny primary" onclick="openPaper(${alert.id})">Open paper</button><button class="button tiny ghost" onclick="skipAlert(${alert.id})">Skip</button>` : ""}</div></article>`;
  }).join("") : `<div class="empty">No signals yet. The strategy waits for aligned book pressure, delta and microprice.</div>`;
  const fresh = new Set(active.map((alert) => alert.id));
  if (lastAlertIds.size && [...fresh].some((id) => !lastAlertIds.has(id))) toast("New order-flow alert", "success");
  lastAlertIds = fresh;
}
function renderTrades(trades) {
  const open = trades.filter((trade) => trade.status === "open");
  $("trades").innerHTML = open.length ? open.map((trade) => `<div class="position-row"><div><b>${esc(trade.symbol)}</b><span class="market-sub ${sideClass(trade.direction)}">${esc(sourceLabel(trade))} · ${trade.direction} · ${fmt(trade.entry_price)}</span></div><div class="position-right"><b class="${(trade.unrealized_pnl || 0) >= 0 ? "positive" : "negative"}">${fmt(trade.unrealized_pnl, 4)} USDT</b><span>${fmt(trade.current_price)} mark</span><button class="icon-action" title="Close paper position" onclick="closeTrade(${trade.id}, ${trade.current_price})">Close</button></div></div>`).join("") : `<div class="empty">No open paper positions.</div>`;
}
function renderOutcomeMix(analytics) { const entries = Object.entries(analytics.by_outcome || {}); $("outcome-mix").innerHTML = entries.length ? entries.map(([name, count]) => `<div class="mix-row"><span>${esc(name.replaceAll("_", " "))}</span><b>${count}</b></div>`).join("") : `<div class="empty">Outcomes will appear as alerts expire or are traded.</div>`; }
async function showAlert(id) {
  try {
    const data = await api(`/api/alerts/${id}`); const alert = data.alert;
    $("alert-detail").innerHTML = `<p class="eyebrow">ALERT #${alert.id} · ${esc(sourceLabel(alert))}</p><h2><span class="signal-pill ${sideClass(alert.direction)}">${alert.direction}</span> ${esc(alert.symbol)}</h2><p class="dialog-reason">${esc(alert.reason)}</p><div class="detail-grid">${[["Rule score", pct(alert.score)], ["ML probability", alert.ml_probability == null ? "Rule-only" : pct(alert.ml_probability)], ["Entry", fmt(alert.reference_price)], ["Stop", fmt(alert.stop_loss)], ["Target", fmt(alert.take_profit)], ["Risk", `${fmt(alert.risk_amount, 4)} USDT`], ["Outcome", alert.outcome_type.replaceAll("_", " ")], ["Source", alert.source_key || "legacy"]].map(([label, value]) => `<div><span>${label}</span><b>${esc(value)}</b></div>`).join("")}</div><h3>Evidence at signal time</h3><div class="evidence-grid">${Object.entries(alert.features || {}).map(([key, value]) => `<div><span>${key.replaceAll("_", " ")}</span><b>${fmt(value, Math.abs(Number(value)) < 10 ? 3 : 2)}</b></div>`).join("")}</div>${alert.outcome ? `<h3>Recorded result</h3><div class="result-box"><b>${esc(alert.outcome.outcome_type.replaceAll("_", " "))}</b><span>price ${fmt(alert.outcome.price_at_outcome)} · hypothetical ${fmt(alert.outcome.hypothetical_pnl, 4)} USDT</span></div>` : ""}<h3>Paper trades</h3>${data.trades.length ? data.trades.map((trade) => `<div class="result-box"><b>${esc(trade.status)}</b><span>${fmt(trade.pnl ?? trade.unrealized_pnl, 4)} USDT · ${esc(trade.exit_reason || "open")}</span></div>`).join("") : `<div class="empty">No paper trade was created.</div>`}`;
    $("alert-dialog").showModal();
  } catch (error) { toast(error.message, "error"); }
}
function closeDialog() { $("alert-dialog").close(); }
async function openPaper(id) { try { await api(`/api/alerts/${id}/paper`, { method: "POST" }); toast("Paper position opened", "success"); await refresh(); } catch (error) { toast(error.message, "error"); await refresh(); } }
async function skipAlert(id) { try { await api(`/api/alerts/${id}/skip`, { method: "POST" }); toast("Alert marked as skipped"); await refresh(); } catch (error) { toast(error.message, "error"); } }
async function closeTrade(id, price) { if (!price) return toast("Current price is not available", "error"); try { await api(`/api/paper-trades/${id}/close`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ exit_price: price, reason: "manual" }) }); toast("Paper position closed", "success"); await refresh(); } catch (error) { toast(error.message, "error"); } }
async function refresh() {
  try {
    const [health, market, alerts, trades, stats, analytics] = await Promise.all([api("/api/health"), api("/api/market"), api("/api/alerts?limit=50"), api("/api/paper-trades?limit=50"), api("/api/stats/pnl"), api("/api/alerts/analytics")]);
    $("exchange-badge").textContent = `${Object.keys(health.sources || {}).length} SOURCES`;
    $("connection-dot").innerHTML = `<i></i> ${health.stream_connected ? "live" : "offline"}`;
    $("connection-dot").className = `connection ${health.stream_connected ? "online" : "offline"}`;
    $("last-update").textContent = new Date().toLocaleTimeString();
    renderSummary(health, stats, analytics); renderMarket(market); renderAlerts(alerts); renderTrades(trades); renderOutcomeMix(analytics);
  } catch (error) { $("connection-dot").className = "connection offline"; $("connection-dot").innerHTML = "<i></i> API unavailable"; toast(error.message, "error"); }
}
refresh();
setInterval(refresh, 2500);
