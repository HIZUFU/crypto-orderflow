const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#039;"}[c]));
const fmt = (value, digits = 4) => value == null ? "-" : Number(value).toFixed(digits);

let chart = null;
let candleSeries = null;
let alertMarkers = [];
let currentSymbol = "BTCUSDT";
let currentTimeframe = "1m";

async function get(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

function initChart() {
  const container = $("chart");
  chart = LightweightCharts.createChart(container, {
    width: container.clientWidth,
    height: 600,
    layout: {
      background: { color: "#171d21" },
      textColor: "#e8edf2",
    },
    grid: {
      vertLines: { color: "#293239" },
      horzLines: { color: "#293239" },
    },
    crosshair: {
      mode: LightweightCharts.CrosshairMode.Normal,
    },
    rightPriceScale: {
      borderColor: "#293239",
    },
    timeScale: {
      borderColor: "#293239",
      timeVisible: true,
      secondsVisible: false,
    },
  });

  candleSeries = chart.addCandlestickSeries({
    upColor: "#49d18d",
    downColor: "#ff6f6f",
    borderVisible: false,
    wickUpColor: "#49d18d",
    wickDownColor: "#ff6f6f",
  });

  // Resize chart on window resize
  window.addEventListener("resize", () => {
    chart.applyOptions({ width: container.clientWidth });
  });
}

async function loadCandles() {
  try {
    const data = await get(`/api/candles/${currentSymbol}?timeframe=${currentTimeframe}&limit=200`);
    if (data.candles && data.candles.length > 0) {
      candleSeries.setData(data.candles);
      chart.timeScale().fitContent();
    }
  } catch (error) {
    console.error("Failed to load candles:", error);
  }
}

async function loadAlerts() {
  try {
    const alerts = await get("/api/alerts?limit=50");
    const filtered = alerts.filter(a => a.symbol === currentSymbol);
    
    // Display in table
    renderAlertsTable(filtered);
    
    // Show on chart if enabled
    if ($("show-alerts").checked) {
      const markers = filtered.map(alert => {
        const timestamp = Math.floor(new Date(alert.created_at).getTime() / 1000);
        return {
          time: timestamp,
          position: alert.direction === "LONG" ? "belowBar" : "aboveBar",
          color: alert.direction === "LONG" ? "#49d18d" : "#ff6f6f",
          shape: alert.direction === "LONG" ? "arrowUp" : "arrowDown",
          text: `${alert.direction} ${(alert.score * 100).toFixed(0)}%`,
        };
      });
      candleSeries.setMarkers(markers);
    } else {
      candleSeries.setMarkers([]);
    }
  } catch (error) {
    console.error("Failed to load alerts:", error);
  }
}

function renderAlertsTable(alerts) {
  const container = $("chart-alerts");
  if (alerts.length === 0) {
    container.innerHTML = '<div class="empty">No alerts for this symbol</div>';
    return;
  }
  
  container.innerHTML = `<table>
    <thead>
      <tr>
        <th>Time</th>
        <th>Direction</th>
        <th>Score</th>
        <th>Entry</th>
        <th>Stop</th>
        <th>Target</th>
      </tr>
    </thead>
    <tbody>${alerts.slice(0, 10).map(alert => `
      <tr>
        <td>${new Date(alert.created_at).toLocaleTimeString()}</td>
        <td class="${alert.direction === "LONG" ? "positive" : "negative"}">${alert.direction}</td>
        <td>${(alert.score * 100).toFixed(1)}%</td>
        <td>${fmt(alert.reference_price, 2)}</td>
        <td>${fmt(alert.stop_loss, 2)}</td>
        <td>${fmt(alert.take_profit, 2)}</td>
      </tr>
    `).join("")}</tbody>
  </table>`;
}

function onSymbolChange() {
  currentSymbol = $("symbol-select").value;
  refresh();
}

function onTimeframeChange() {
  currentTimeframe = $("timeframe-select").value;
  refresh();
}

function onShowAlertsChange() {
  loadAlerts();
}

async function refresh() {
  await Promise.all([loadCandles(), loadAlerts()]);
}

// Initialize
initChart();
refresh();

// Auto-refresh every 5 seconds
setInterval(refresh, 5000);

// Event listeners
$("symbol-select").addEventListener("change", onSymbolChange);
$("timeframe-select").addEventListener("change", onTimeframeChange);
$("show-alerts").addEventListener("change", onShowAlertsChange);
